"""Durable, fail-open settlement for charges made after provider delivery.

Policy (Project-Ops 1ecbf92f): a billable request is refused with 402 at the door
on a prompt + completion estimate. Once the provider has delivered, the response
stands; a charge that cannot be written is queued in ``billing_unsettled_charges``
(or, when the database itself is unreachable, a JSONL spool beside the app data)
and retried by ``BillingReconciler`` under the same ``request_id``, so each
ledger moves exactly once.

Rollback switches: ``BILLING_SETTLE_FAILURE_MODE=legacy`` restores the previous
behaviour (500 on non-streaming chat and image, a log line on streaming) and
``BILLING_RECONCILER_ENABLED=false`` stops the retries.
"""

import asyncio
import fcntl
import json
import logging
import os
import time
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

logger = logging.getLogger(__name__)

BILLING_SETTLE_FAILURE_MODE = os.getenv("BILLING_SETTLE_FAILURE_MODE", "queue").lower()


def _env_number(name: str, default: float) -> float:
    try:
        value = float(os.getenv(name, default))
    except (TypeError, ValueError):
        return float(default)
    return value if value > 0 else float(default)


def settlement_failure_mode() -> str:
    mode = os.getenv("BILLING_SETTLE_FAILURE_MODE", BILLING_SETTLE_FAILURE_MODE).lower()
    return mode if mode in {"queue", "legacy"} else "queue"


def _enqueue_timeout() -> float:
    """Bound on one queue INSERT, so a hung database cannot hang a stream's tail."""
    return _env_number("BILLING_ENQUEUE_TIMEOUT_S", 5.0)


def _settle_timeout() -> float:
    """Bound on one settlement attempt (queue mode only; legacy is unbounded as before)."""
    return _env_number("BILLING_SETTLE_TIMEOUT_S", 15.0)


# ---------------------------------------------------------------------------
# Door-check estimate
# ---------------------------------------------------------------------------

def estimate_prompt_tokens(messages) -> int:
    """The historical rough prompt estimate (words x 1.5).

    Billing fallbacks (a provider that returns no usage) and the local-pricing
    quota gate keep using exactly this, so widening the door check does not
    change what anyone is billed.
    """
    return int(sum(len((msg.content or "").split()) * 1.5 for msg in messages))


def completion_allowance(max_tokens: Optional[int] = None) -> int:
    """Completion tokens the door reserves: the caller's max_tokens, else the default.

    A zero or negative max_tokens is not a real cap (the upstream call falls
    back to the power-level default), so it gets the default allowance too.
    """
    if max_tokens is not None and max_tokens > 0:
        return int(max_tokens)
    return int(_env_number("BILLING_DEFAULT_COMPLETION_TOKENS", 1024))


def estimate_chat_tokens(messages, max_tokens: Optional[int] = None) -> int:
    """Conservative door-check estimate: prompt plus the completion allowance."""
    return estimate_prompt_tokens(messages) + completion_allowance(max_tokens)


# ---------------------------------------------------------------------------
# Spool (the fallback when the database is unreachable)
# ---------------------------------------------------------------------------

def _spool_dir() -> Path:
    return Path(os.getenv("BILLING_SPOOL_DIR", str(Path(__file__).parent / "data")))


def _spool_path() -> Path:
    return _spool_dir() / "billing_spool.jsonl"


def _spool_lock_path(directory: Path) -> Path:
    # Held briefly by every append and by the drain's rename, so a line can never
    # be written into a file the drain has already taken.
    return directory / "billing_spool.lock"


def _drain_lock_path(directory: Path) -> Path:
    # Held for a whole drain; a second drainer (another worker) skips its cycle.
    return directory / "billing_spool.drain.lock"


def _record_json(record: Dict[str, Any]) -> str:
    return json.dumps(record, default=str, separators=(",", ":"))


def _locked_append(path: Path, lines: Iterable[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(_spool_lock_path(path.parent), "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            with path.open("a", encoding="utf-8") as handle:
                for line in lines:
                    handle.write(line.rstrip("\n") + "\n")
                handle.flush()
                os.fsync(handle.fileno())
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def _take_spool_for_draining(path: Path, draining: Path) -> bool:
    with open(_spool_lock_path(path.parent), "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            if not path.exists():
                return False
            os.replace(path, draining)
            return True
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


async def _append_line(path: Path, line: str) -> None:
    await asyncio.to_thread(_locked_append, path, [line])


async def _append_spool(record: Dict[str, Any]) -> None:
    await _append_line(_spool_path(), _record_json(record))


# ---------------------------------------------------------------------------
# Queue table
# ---------------------------------------------------------------------------

_INSERT_SQL = """INSERT INTO billing_unsettled_charges
    (request_id, user_id, org_id, amount_credits, provider, model, tokens,
     service, metadata, error, attempts, created_at, last_attempt_at, settled_at)
    VALUES ($1::uuid, $2, $3, $4, $5, $6, $7, $8, $9::jsonb, $10, $11,
            COALESCE($12::text::timestamptz, NOW()), $13::text::timestamptz, $14::text::timestamptz)
    ON CONFLICT (request_id) DO NOTHING"""


def _text(value: Any) -> Optional[str]:
    # org_id arrives as an asyncpg UUID (organization_members.org_id is uuid);
    # the queue column is varchar, and asyncpg refuses a UUID for a text param.
    return None if value is None else str(value)


def _timestamp_text(value: Any) -> Optional[str]:
    # Bound as text and cast in SQL: asyncpg refuses an ISO string for a
    # timestamptz parameter, and the spool can only carry strings anyway.
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat()
    return str(value)


def _amount(value: Any) -> Decimal:
    try:
        return Decimal(str(value if value is not None else 0))
    except InvalidOperation as exc:
        raise ValueError(f"amount_credits is not a number: {value!r}") from exc


def _insert_args(record: Dict[str, Any]) -> tuple:
    metadata = record.get("metadata") or {}
    if isinstance(metadata, str):
        try:
            metadata = json.loads(metadata)
        except ValueError:
            metadata = {"raw": metadata}
    return (
        str(record["request_id"]),
        str(record.get("user_id")),
        _text(record.get("org_id")),
        _amount(record.get("amount_credits")),
        _text(record.get("provider")),
        _text(record.get("model")),
        int(record.get("tokens") or 0),
        str(record.get("service") or "unknown"),
        _record_json(metadata),
        str(record.get("error") or "unknown settlement failure")[:2000],
        int(record.get("attempts") or 0),
        _timestamp_text(record.get("created_at")),
        _timestamp_text(record.get("last_attempt_at")),
        _timestamp_text(record.get("settled_at")),
    )


async def _insert_record(pool: Any, record: Dict[str, Any]) -> bool:
    """Persist one record; True once it is in the table (inserted now or already there)."""
    if pool is None:
        return False
    args = _insert_args(record)

    async def _write():
        async with pool.acquire() as conn:
            await conn.execute(_INSERT_SQL, *args)

    await asyncio.wait_for(_write(), timeout=_enqueue_timeout())
    return True


async def enqueue_unsettled_charge(pool: Any, record: Dict[str, Any]) -> bool:
    """Try Postgres first, then the durable JSONL spool; never raises to the caller."""
    record = dict(record)
    record.setdefault("created_at", datetime.now(timezone.utc).isoformat())
    record.setdefault("attempts", 0)
    record.setdefault("last_attempt_at", None)
    record.setdefault("settled_at", None)
    inserted = False
    try:
        inserted = await _insert_record(pool, record)
    except Exception as exc:  # includes the timeout
        logger.warning(
            "Unable to persist unsettled charge in database request_id=%s (spooling): %s: %s",
            record.get("request_id"), type(exc).__name__, exc,
        )
    if not inserted:
        # No pool, or the insert failed: the spool is the durable fallback either way.
        try:
            await _append_spool(record)
        except Exception as spool_exc:
            logger.critical(
                "Unable to persist billing spool record request_id=%s: %s",
                record.get("request_id"), spool_exc,
            )
    logger.error(
        "UNSETTLED CHARGE queued request_id=%s org=%s user=%s amount=%s",
        record.get("request_id"), record.get("org_id"), record.get("user_id"), record.get("amount_credits"),
    )
    return inserted


async def settle_or_queue(*, settle, pool: Any, record: Dict[str, Any], result_ok=None):
    """One policy gate used by stream, chat, and image billing paths."""
    legacy = settlement_failure_mode() == "legacy"
    try:
        if legacy:
            result = await settle()
        else:
            result = await asyncio.wait_for(settle(), timeout=_settle_timeout())
        ok = result_ok(result) if result_ok else (bool(result[0]) if isinstance(result, tuple) else bool(result))
        if ok or legacy:
            return result
        await enqueue_unsettled_charge(pool, {**record, "error": "deduction returned false"})
        return None
    except Exception as exc:
        if legacy:
            raise
        await enqueue_unsettled_charge(pool, {**record, "error": f"{type(exc).__name__}: {exc}"})
        return None


# ---------------------------------------------------------------------------
# Streaming: settlement that a client disconnect cannot cancel
# ---------------------------------------------------------------------------

_BACKGROUND_SETTLEMENTS: set = set()


def _log_settlement_outcome(task: "asyncio.Task") -> None:
    _BACKGROUND_SETTLEMENTS.discard(task)
    if task.cancelled():
        logger.error("Streaming settlement task was cancelled before it finished")
        return
    exc = task.exception()
    if exc is not None:
        logger.error("Streaming settlement failed: %s: %s", type(exc).__name__, exc)


def start_settlement(coro) -> "asyncio.Task":
    """Run a settlement as its own task and keep a strong reference to it.

    A client that disconnects cancels the streaming generator (Starlette cancels
    the response task). Awaiting ``asyncio.shield(task)`` from the generator, or
    starting the task from its ``finally`` when it is torn down, lets the charge
    finish (or reach the queue) regardless.
    """
    task = asyncio.get_running_loop().create_task(coro)
    _BACKGROUND_SETTLEMENTS.add(task)
    task.add_done_callback(_log_settlement_outcome)
    return task


async def wait_for_background_settlements(timeout: float = 10.0) -> int:
    """At shutdown, give in-flight streaming settlements a chance to finish
    before the database pool closes. Returns how many were still pending."""
    pending = [task for task in _BACKGROUND_SETTLEMENTS if not task.done()]
    if not pending:
        return 0
    _, still_pending = await asyncio.wait(pending, timeout=timeout)
    if still_pending:
        logger.critical("%d streaming settlement(s) still running at shutdown", len(still_pending))
    return len(still_pending)


# ---------------------------------------------------------------------------
# Reconciler
# ---------------------------------------------------------------------------

# Claim due rows atomically: SKIP LOCKED keeps two workers off the same row, and
# bumping last_attempt_at in the same statement keeps it out of every other
# worker's next claim until its backoff has passed. The ledger functions also
# dedupe by request_id, so a claim that outlives its backoff cannot double-bill.
_CLAIM_SQL = """
UPDATE billing_unsettled_charges AS b
   SET attempts = b.attempts + 1,
       last_attempt_at = NOW()
 WHERE b.id IN (
       SELECT c.id
         FROM billing_unsettled_charges AS c
        WHERE c.settled_at IS NULL
          AND (c.last_attempt_at IS NULL
               OR c.last_attempt_at < NOW() - INTERVAL '1 minute'
                  * LEAST(POWER(2, LEAST(c.attempts, 6)), 60))
        ORDER BY c.created_at
        LIMIT $1
        FOR UPDATE SKIP LOCKED)
RETURNING b.*"""


def _is_bad_record(exc: BaseException) -> bool:
    """True when retrying cannot help: the record itself is malformed."""
    if isinstance(exc, (ValueError, TypeError, KeyError)):
        return True  # includes asyncpg's client-side DataError
    sqlstate = str(getattr(exc, "sqlstate", "") or "")
    return sqlstate.startswith(("22", "23"))


class BillingReconciler:
    def __init__(self, pool: Any, credit_system: Any, org_integration: Any, batch_size: int = 100):
        self.pool = pool
        self.credit_system = credit_system
        self.org_integration = org_integration
        self.batch_size = batch_size
        self._critical_logged: Dict[str, float] = {}

    async def drain_spool(self) -> int:
        path = _spool_path()
        draining = path.with_name(path.name + ".draining")
        if not path.exists() and not draining.exists():
            return 0
        path.parent.mkdir(parents=True, exist_ok=True)
        drain_lock = open(_drain_lock_path(path.parent), "a")
        try:
            try:
                fcntl.flock(drain_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except (BlockingIOError, PermissionError):
                return 0  # another worker is draining; skip this cycle
            # A .draining file left by a drain that died mid-way is finished first.
            if not draining.exists():
                if not await asyncio.to_thread(_take_spool_for_draining, path, draining):
                    return 0
            lines = (await asyncio.to_thread(draining.read_text, encoding="utf-8")).splitlines()
            drained = 0
            keep: list = []
            deadletter: list = []
            db_unavailable = False
            for line in lines:
                if not line.strip():
                    continue
                if db_unavailable:
                    keep.append(line)
                    continue
                try:
                    record = json.loads(line)
                    if not isinstance(record, dict) or not record.get("request_id"):
                        raise ValueError("spool line is not a charge record")
                except ValueError:
                    deadletter.append(line)
                    continue
                try:
                    ok = await _insert_record(self.pool, record)
                except Exception as exc:
                    if _is_bad_record(exc):
                        logger.critical(
                            "Billing spool record rejected by the database, moved to deadletter request_id=%s: %s",
                            record.get("request_id"), exc,
                        )
                        deadletter.append(line)
                        continue
                    ok = False
                if ok:
                    drained += 1
                else:
                    # Database unreachable: keep this and every later line for the next cycle.
                    db_unavailable = True
                    keep.append(line)
            if deadletter:
                await asyncio.to_thread(
                    _locked_append, path.with_name("billing_spool.deadletter.jsonl"), deadletter
                )
                logger.critical("%d billing spool line(s) moved to billing_spool.deadletter.jsonl", len(deadletter))
            if keep:
                await asyncio.to_thread(_locked_append, path, keep)
            await asyncio.to_thread(draining.unlink)
            if drained:
                logger.info("Billing spool drained %d charge(s) into billing_unsettled_charges", drained)
            return drained
        finally:
            try:
                fcntl.flock(drain_lock, fcntl.LOCK_UN)
            finally:
                drain_lock.close()

    async def _claim(self) -> list:
        async with self.pool.acquire() as conn:
            return await conn.fetch(_CLAIM_SQL, self.batch_size)

    async def _settle(self, record: Dict[str, Any]) -> bool:
        metadata = record.get("metadata") or {}
        if isinstance(metadata, str):
            metadata = json.loads(metadata)
        amount = float(record["amount_credits"])
        request_id = str(record["request_id"])
        if record.get("org_id"):
            result = await self.org_integration.deduct_org_credits(
                user_id=record["user_id"], credits_used=amount,
                service_name=metadata.get("service_name") or record.get("service") or "litellm",
                provider=record.get("provider") or "unknown", model=record.get("model") or "unknown",
                tokens_used=int(record.get("tokens") or 0),
                power_level=metadata.get("power_level") or "balanced",
                task_type=metadata.get("task_type"), request_id=request_id, org_id=str(record["org_id"]),
            )
            return bool(result and result[0])
        ledger_metadata = {k: v for k, v in metadata.items() if k != "service_name"}
        ledger_metadata.update({
            "provider": record.get("provider") or "unknown",
            "model": record.get("model") or "unknown",
            "tokens_used": int(record.get("tokens") or 0),
            "cost": amount,
            "request_id": request_id,
            "settled_by": "billing_reconciler",
        })
        await self.credit_system.debit_credits(
            user_id=record["user_id"], amount=amount, metadata=ledger_metadata,
        )
        return True

    def _log_if_stale(self, record: Dict[str, Any]) -> None:
        created = record.get("created_at")
        if isinstance(created, str):
            try:
                created = datetime.fromisoformat(created.replace("Z", "+00:00"))
            except ValueError:
                created = None
        if created is None:
            return
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        if (datetime.now(timezone.utc) - created).total_seconds() <= 3600:
            return
        key = str(record.get("request_id"))
        now = time.monotonic()
        last = self._critical_logged.get(key)
        if last is None or now - last >= 3600:
            logger.critical(
                "Unsettled billing charge older than 60 minutes request_id=%s org=%s user=%s amount=%s attempts=%s error=%s",
                key, record.get("org_id"), record.get("user_id"), record.get("amount_credits"),
                record.get("attempts"), record.get("error"),
            )
            self._critical_logged[key] = now

    async def reconcile_once(self) -> int:
        try:
            await self.drain_spool()
        except Exception as exc:
            logger.error("Billing spool drain failed: %s: %s", type(exc).__name__, exc)
        if self.pool is None:
            return 0
        rows = await self._claim()
        settled = 0
        for row in rows:
            record = dict(row)
            error = None
            try:
                ok = await asyncio.wait_for(self._settle(record), timeout=_settle_timeout())
            except Exception as exc:
                ok, error = False, f"{type(exc).__name__}: {exc}"
            key = str(record.get("request_id"))
            if ok:
                async with self.pool.acquire() as conn:
                    await conn.execute(
                        "UPDATE billing_unsettled_charges SET settled_at = NOW() WHERE id = $1 AND settled_at IS NULL",
                        record["id"],
                    )
                self._critical_logged.pop(key, None)
                settled += 1
                logger.info(
                    "Billing reconciler settled request_id=%s org=%s user=%s amount=%s attempt=%s",
                    key, record.get("org_id"), record.get("user_id"), record.get("amount_credits"), record.get("attempts"),
                )
                continue
            error = error or "deduction returned false"
            record["error"] = error
            logger.error("Billing reconciliation failed request_id=%s attempt=%s: %s", key, record.get("attempts"), error)
            try:
                async with self.pool.acquire() as conn:
                    await conn.execute(
                        "UPDATE billing_unsettled_charges SET error = $2 WHERE id = $1", record["id"], error[:2000],
                    )
            except Exception as exc:
                logger.warning("Could not record reconciliation error request_id=%s: %s", key, exc)
            self._log_if_stale(record)
        return settled

    async def run(self, interval: float = 60.0):
        while True:
            try:
                await self.reconcile_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error("Billing reconciler failed: %s: %s", type(exc).__name__, exc)
            await asyncio.sleep(interval)
