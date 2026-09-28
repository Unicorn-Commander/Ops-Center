"""Durable, fail-open settlement for charges made after provider delivery."""

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

BILLING_SETTLE_FAILURE_MODE = os.getenv("BILLING_SETTLE_FAILURE_MODE", "queue").lower()


def settlement_failure_mode() -> str:
    mode = os.getenv("BILLING_SETTLE_FAILURE_MODE", BILLING_SETTLE_FAILURE_MODE).lower()
    return mode if mode in {"queue", "legacy"} else "queue"


def _spool_path() -> Path:
    return Path(os.getenv("BILLING_SPOOL_DIR", str(Path(__file__).parent / "data"))) / "billing_spool.jsonl"


def _record_json(record: Dict[str, Any]) -> str:
    return json.dumps(record, default=str, separators=(",", ":"))


async def _append_spool(record: Dict[str, Any]) -> None:
    path = _spool_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    line = _record_json(record) + "\n"
    def append():
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line)
    await asyncio.to_thread(append)


async def _insert_record(pool: Any, record: Dict[str, Any]) -> bool:
    if pool is None:
        return False
    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO billing_unsettled_charges
            (request_id, user_id, org_id, amount_credits, provider, model, tokens,
             service, metadata, error, attempts, created_at, last_attempt_at, settled_at)
            VALUES ($1::uuid, $2, $3, $4, $5, $6, $7, $8, $9::jsonb, $10, $11,
                    COALESCE($12::timestamptz, NOW()), $13::timestamptz, $14::timestamptz)
            ON CONFLICT (request_id) DO NOTHING""",
            str(record["request_id"]), record.get("user_id"), record.get("org_id"),
            record.get("amount_credits", 0), record.get("provider"), record.get("model"),
            record.get("tokens", 0), record.get("service"), _record_json(record.get("metadata", {})),
            record.get("error", "unknown settlement failure"), record.get("attempts", 0),
            record.get("created_at"), record.get("last_attempt_at"), record.get("settled_at"),
        )
    return True


async def enqueue_unsettled_charge(pool: Any, record: Dict[str, Any]) -> bool:
    """Try Postgres first, then durable JSONL; never raises to the caller."""
    record = dict(record)
    record.setdefault("created_at", datetime.now(timezone.utc).isoformat())
    record.setdefault("attempts", 0)
    record.setdefault("last_attempt_at", None)
    record.setdefault("settled_at", None)
    inserted = False
    try:
        inserted = await _insert_record(pool, record)
    except Exception as exc:
        logger.warning("Unable to persist unsettled charge in database: %s", exc)
        try:
            await _append_spool(record)
        except Exception as spool_exc:
            logger.critical("Unable to persist billing spool record request_id=%s: %s", record.get("request_id"), spool_exc)
    logger.error(
        "UNSETTLED CHARGE queued request_id=%s org=%s user=%s amount=%s",
        record.get("request_id"), record.get("org_id"), record.get("user_id"), record.get("amount_credits"),
    )
    return inserted


async def settle_or_queue(*, settle, pool: Any, record: Dict[str, Any], result_ok=None):
    """One policy gate used by stream, chat, and image billing paths."""
    try:
        result = await settle()
        ok = result_ok(result) if result_ok else (bool(result[0]) if isinstance(result, tuple) else bool(result))
        if ok:
            return result
        if settlement_failure_mode() == "legacy":
            return result
        await enqueue_unsettled_charge(pool, {**record, "error": "deduction returned false"})
        return None
    except Exception as exc:
        if settlement_failure_mode() == "legacy":
            raise
        await enqueue_unsettled_charge(pool, {**record, "error": str(exc)})
        return None


class BillingReconciler:
    def __init__(self, pool: Any, credit_system: Any, org_integration: Any):
        self.pool = pool
        self.credit_system = credit_system
        self.org_integration = org_integration
        self._critical_logged = set()

    async def drain_spool(self) -> int:
        path = _spool_path()
        if not path.exists():
            return 0
        lines = await asyncio.to_thread(path.read_text, encoding="utf-8")
        kept, drained = [], 0
        for line in lines.splitlines():
            try:
                record = json.loads(line)
                if await _insert_record(self.pool, record):
                    drained += 1
                else:
                    kept.append(line)
            except Exception:
                kept.append(line)
        if kept:
            await asyncio.to_thread(path.write_text, "\n".join(kept) + "\n", encoding="utf-8")
        else:
            await asyncio.to_thread(path.unlink)
        return drained

    async def reconcile_once(self) -> int:
        await self.drain_spool()
        if self.pool is None:
            return 0
        settled = 0
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT * FROM billing_unsettled_charges
                   WHERE settled_at IS NULL
                     AND (last_attempt_at IS NULL OR last_attempt_at < NOW() -
                          make_interval(mins => LEAST(POWER(2, attempts), 60)))"""
            )
        for row in rows:
            record = dict(row)
            try:
                async with self.pool.acquire() as conn:
                    await conn.execute(
                        "UPDATE billing_unsettled_charges SET attempts=attempts+1, last_attempt_at=NOW() WHERE request_id=$1",
                        record["request_id"],
                    )
                metadata = record.get("metadata") or {}
                if isinstance(metadata, str):
                    metadata = json.loads(metadata)
                if record.get("org_id"):
                    result = await self.org_integration.deduct_org_credits(
                        user_id=record["user_id"], credits_used=float(record["amount_credits"]),
                        service_name=record["service"], provider=record["provider"], model=record["model"],
                        tokens_used=record.get("tokens", 0), power_level=metadata.get("power_level", "balanced"),
                        task_type=metadata.get("task_type"), request_id=str(record["request_id"]), org_id=record["org_id"],
                    )
                else:
                    result = await self.credit_system.debit_credits(
                        user_id=record["user_id"], amount=float(record["amount_credits"]),
                        metadata={**metadata, "request_id": str(record["request_id"])},
                    )
                success = bool(result[0]) if record.get("org_id") and isinstance(result, tuple) else result is not None
                if success:
                    async with self.pool.acquire() as conn:
                        await conn.execute("UPDATE billing_unsettled_charges SET settled_at=NOW() WHERE request_id=$1", record["request_id"])
                    settled += 1
            except Exception as exc:
                logger.error("Billing reconciliation failed request_id=%s: %s", record.get("request_id"), exc)
                created = record.get("created_at")
                if isinstance(created, str):
                    try:
                        created = datetime.fromisoformat(created.replace("Z", "+00:00"))
                    except ValueError:
                        created = None
                if created and created.tzinfo is None:
                    created = created.replace(tzinfo=timezone.utc)
                if created and (datetime.now(timezone.utc) - created).total_seconds() > 3600:
                    key = str(record.get("request_id"))
                    if key not in self._critical_logged:
                        logger.critical("Unsettled billing charge older than 60 minutes request_id=%s", key)
                        self._critical_logged.add(key)
        return settled

    async def run(self):
        while True:
            try:
                await self.reconcile_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error("Billing reconciler failed: %s", exc)
            await asyncio.sleep(60)
