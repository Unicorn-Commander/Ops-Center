import json
from contextlib import asynccontextmanager

import pytest

import os
from pathlib import Path

from billing_settlement import BillingReconciler, enqueue_unsettled_charge, estimate_chat_tokens, settle_or_queue


class Message:
    def __init__(self, content):
        self.content = content




class FakeConn:
    def __init__(self, *, fail_insert=False, rows=None):
        self.fail_insert = fail_insert
        self.rows = rows or []
        self.executed = []

    async def execute(self, query, *args):
        self.executed.append((query, args))
        if self.fail_insert and query.startswith("INSERT"):
            raise RuntimeError("database unavailable")

    async def fetch(self, query, *args):
        return self.rows


class FakePool:
    def __init__(self, conn):
        self.conn = conn

    @asynccontextmanager
    async def acquire(self):
        yield self.conn


@pytest.mark.parametrize("maximum,expected", [(7, 10), (None, 1027), (0, 1027), (-5, 1027)])
def test_preflight_estimate_includes_completion_allowance(maximum, expected):
    messages = [Message("one two")]
    assert estimate_chat_tokens(messages, maximum) == expected


@pytest.mark.asyncio
async def test_stream_false_deduction_queues_without_raising(monkeypatch):
    queued = []

    async def fake_enqueue(pool, record):
        queued.append(record)

    monkeypatch.setattr("billing_settlement.enqueue_unsettled_charge", fake_enqueue)
    result = await settle_or_queue(
        pool=None,
        settle=lambda: _async_value((False, "org-1", None)),
        record={"request_id": "00000000-0000-0000-0000-000000000001", "user_id": "u", "org_id": "o", "amount_credits": 2},
    )
    assert result is None
    assert queued[0]["amount_credits"] == 2


@pytest.mark.asyncio
async def test_debit_exception_queues_without_raising(monkeypatch):
    queued = []

    async def fake_enqueue(pool, record):
        queued.append(record)

    monkeypatch.setattr("billing_settlement.enqueue_unsettled_charge", fake_enqueue)

    async def fail():
        raise RuntimeError("write failed")

    assert await settle_or_queue(
        pool=None, settle=fail,
        record={"request_id": "00000000-0000-0000-0000-000000000002", "user_id": "u", "amount_credits": 3},
    ) is None
    assert "write failed" in queued[0]["error"]


@pytest.mark.asyncio
async def test_db_failure_spools_valid_json(monkeypatch, tmp_path):
    monkeypatch.setenv("BILLING_SPOOL_DIR", str(tmp_path))
    record = {
        "request_id": "00000000-0000-0000-0000-000000000003",
        "user_id": "u", "amount_credits": 1.25, "service": "litellm",
        "metadata": {"task_type": "chat"},
    }
    assert not await enqueue_unsettled_charge(FakePool(FakeConn(fail_insert=True)), record)
    line = (tmp_path / "billing_spool.jsonl").read_text().strip()
    assert json.loads(line)["metadata"]["task_type"] == "chat"


@pytest.mark.asyncio
async def test_reconciler_settles_once_and_second_run_does_not_debit_again():
    request_id = "00000000-0000-0000-0000-000000000004"
    row = {
        "id": "row-1", "request_id": request_id, "user_id": "u", "org_id": None,
        "amount_credits": 4, "provider": "p", "model": "m", "tokens": 2,
        "service": "litellm", "metadata": {}, "created_at": None,
    }
    conn = FakeConn(rows=[row])
    debits = []

    async def debit(**kwargs):
        debits.append(kwargs)
        return (10, "tx")

    credits = type("Credits", (), {"debit_credits": staticmethod(debit)})()
    reconciler = BillingReconciler(FakePool(conn), credits, object())
    assert await reconciler.reconcile_once() == 1
    conn.rows = []
    assert await reconciler.reconcile_once() == 0
    assert len(debits) == 1


@pytest.mark.asyncio
async def test_reconciler_drains_spool_into_table(monkeypatch, tmp_path):
    monkeypatch.setenv("BILLING_SPOOL_DIR", str(tmp_path))
    record = {"request_id": "00000000-0000-0000-0000-000000000005", "user_id": "u", "amount_credits": 1, "service": "litellm"}
    (tmp_path / "billing_spool.jsonl").write_text(json.dumps(record) + "\n")
    conn = FakeConn()
    assert await BillingReconciler(FakePool(conn), object(), object()).drain_spool() == 1
    assert not (tmp_path / "billing_spool.jsonl").exists()
    assert any(call[0].startswith("INSERT") for call in conn.executed)


async def _async_value(value):
    return value


# --- Orchestrator review fixes (Claude Code, 2026-09-28) -------------------------------------------


@pytest.mark.asyncio
async def test_enqueue_without_pool_still_persists_to_spool(monkeypatch, tmp_path):
    """No pool must not mean 'logged as queued but written nowhere'."""
    monkeypatch.setenv("BILLING_SPOOL_DIR", str(tmp_path))
    record = {"request_id": "00000000-0000-0000-0000-000000000010", "user_id": "u", "amount_credits": 2, "service": "litellm"}
    assert not await enqueue_unsettled_charge(None, record)
    lines = (tmp_path / "billing_spool.jsonl").read_text().splitlines()
    assert [json.loads(l)["request_id"] for l in lines] == [record["request_id"]]


@pytest.mark.asyncio
async def test_drain_never_drops_a_line_appended_while_draining(monkeypatch, tmp_path):
    """DB still down during the drain + a new charge spooled mid-drain: both must survive."""
    monkeypatch.setenv("BILLING_SPOOL_DIR", str(tmp_path))
    spool = tmp_path / "billing_spool.jsonl"
    old = {"request_id": "00000000-0000-0000-0000-000000000011", "user_id": "u", "amount_credits": 1, "service": "litellm"}
    new = {"request_id": "00000000-0000-0000-0000-000000000012", "user_id": "u", "amount_credits": 1, "service": "litellm"}
    spool.write_text(json.dumps(old) + "\n")

    async def insert_while_db_down(pool, record):
        # a request finishes and spools its charge while the reconciler is mid-drain
        with spool.open("a") as fh:
            fh.write(json.dumps(new) + "\n")
        raise RuntimeError("database unavailable")

    monkeypatch.setattr("billing_settlement._insert_record", insert_while_db_down)
    assert await BillingReconciler(object(), object(), object()).drain_spool() == 0
    ids = sorted(json.loads(l)["request_id"] for l in spool.read_text().splitlines())
    assert ids == sorted([old["request_id"], new["request_id"]])
    assert not (tmp_path / "billing_spool.jsonl.draining").exists()


@pytest.mark.asyncio
async def test_drain_moves_unparseable_lines_to_deadletter(monkeypatch, tmp_path):
    monkeypatch.setenv("BILLING_SPOOL_DIR", str(tmp_path))
    (tmp_path / "billing_spool.jsonl").write_text("{not json\n")
    assert await BillingReconciler(FakePool(FakeConn()), object(), object()).drain_spool() == 0
    assert (tmp_path / "billing_spool.deadletter.jsonl").read_text().strip() == "{not json"
    assert not (tmp_path / "billing_spool.jsonl").exists()


def test_server_does_not_hand_the_shared_pool_to_org_billing():
    """OrgCreditIntegration acquires from db_pool but never releases (it only closes direct
    connections). Giving it the app pool leaks one connection per org-billed request."""
    server = (Path(__file__).resolve().parents[2] / "server.py").read_text()
    assert "get_org_credit_integration().db_pool =" not in server


# --- BILLING-DEPLOY lane fixes (Claude Code subagent, 2026-09-28) ------------------------------
# Each of these pins a defect that the fake-connection suite above could not see and that was
# reproduced against a real PostgreSQL 16.9 restore of the live schema (see
# tests/integration/test_billing_settlement_pg.py for the real-database versions).

import asyncio
import fcntl
import uuid
from datetime import datetime, timezone
from decimal import Decimal

import billing_settlement


class AsyncpgStyleUUID(uuid.UUID):
    """Stands in for asyncpg.pgproto.UUID: organization_members.org_id is a uuid column."""


def test_insert_args_are_types_asyncpg_accepts():
    """asyncpg refused the ISO strings ($12 timestamptz) and the UUID org_id ($3 varchar)."""
    record = {
        "request_id": uuid.UUID("00000000-0000-0000-0000-000000000020"),
        "user_id": "u", "org_id": AsyncpgStyleUUID("11111111-1111-1111-1111-111111111111"),
        "amount_credits": 0.000271, "provider": "p", "model": "m", "tokens": 12.0,
        "service": "litellm", "metadata": {"k": "v"},
        "created_at": "2026-09-28T07:00:00+00:00",
        "last_attempt_at": datetime(2026, 9, 28, 7, 1, tzinfo=timezone.utc),
        "settled_at": None,
    }
    args = billing_settlement._insert_args(record)
    assert args[0] == "00000000-0000-0000-0000-000000000020"
    assert args[2] == "11111111-1111-1111-1111-111111111111" and type(args[2]) is str
    assert args[3] == Decimal("0.000271")
    assert args[6] == 12
    assert json.loads(args[8]) == {"k": "v"}
    assert args[11] == "2026-09-28T07:00:00+00:00"
    assert args[12] == "2026-09-28T07:01:00+00:00"
    assert args[13] is None
    # timestamps are bound as text and cast in SQL
    assert "$12::text::timestamptz" in billing_settlement._INSERT_SQL


def test_claim_is_atomic_and_backoff_query_is_valid_sql():
    """make_interval(mins => <double>) does not exist in PostgreSQL: the old query failed every cycle."""
    sql = billing_settlement._CLAIM_SQL
    assert "make_interval" not in sql
    assert "FOR UPDATE SKIP LOCKED" in sql
    assert "attempts = b.attempts + 1" in sql and "RETURNING b.*" in sql
    assert "LEAST(c.attempts, 6)" in sql  # POWER(2, attempts) cannot overflow


class HangingPool:
    @asynccontextmanager
    async def acquire(self):
        await asyncio.sleep(3600)
        yield None


@pytest.mark.asyncio
async def test_enqueue_is_bounded_and_spools_when_the_database_hangs(monkeypatch, tmp_path):
    monkeypatch.setenv("BILLING_SPOOL_DIR", str(tmp_path))
    monkeypatch.setenv("BILLING_ENQUEUE_TIMEOUT_S", "0.05")
    record = {"request_id": "00000000-0000-0000-0000-000000000021", "user_id": "u", "amount_credits": 1, "service": "litellm"}
    assert await asyncio.wait_for(enqueue_unsettled_charge(HangingPool(), record), timeout=2) is False
    assert json.loads((tmp_path / "billing_spool.jsonl").read_text())["request_id"] == record["request_id"]


@pytest.mark.asyncio
async def test_a_hung_settlement_is_queued_in_queue_mode(monkeypatch):
    monkeypatch.setenv("BILLING_SETTLE_TIMEOUT_S", "0.05")
    monkeypatch.setenv("BILLING_SETTLE_FAILURE_MODE", "queue")
    queued = []

    async def fake_enqueue(pool, record):
        queued.append(record)

    monkeypatch.setattr("billing_settlement.enqueue_unsettled_charge", fake_enqueue)

    async def hang():
        await asyncio.sleep(3600)

    assert await asyncio.wait_for(settle_or_queue(settle=hang, pool=None, record={"request_id": "r"}), timeout=2) is None
    assert queued and "TimeoutError" in queued[0]["error"]


@pytest.mark.asyncio
async def test_legacy_mode_still_raises(monkeypatch):
    monkeypatch.setenv("BILLING_SETTLE_FAILURE_MODE", "legacy")

    async def fail():
        raise RuntimeError("write failed")

    with pytest.raises(RuntimeError):
        await settle_or_queue(settle=fail, pool=None, record={"request_id": "r"})
    assert await settle_or_queue(settle=lambda: _async_value((False, "o", None)), pool=None, record={}) == (False, "o", None)


@pytest.mark.asyncio
async def test_second_drainer_skips_while_the_first_holds_the_drain_lock(monkeypatch, tmp_path):
    """Two workers must not read, insert and unlink the same .draining file."""
    monkeypatch.setenv("BILLING_SPOOL_DIR", str(tmp_path))
    record = {"request_id": "00000000-0000-0000-0000-000000000022", "user_id": "u", "amount_credits": 1, "service": "litellm"}
    (tmp_path / "billing_spool.jsonl").write_text(json.dumps(record) + "\n")
    with open(tmp_path / "billing_spool.drain.lock", "a") as held:
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        conn = FakeConn()
        assert await BillingReconciler(FakePool(conn), object(), object()).drain_spool() == 0
        assert conn.executed == []
        assert (tmp_path / "billing_spool.jsonl").exists()
        fcntl.flock(held, fcntl.LOCK_UN)
    conn = FakeConn()
    assert await BillingReconciler(FakePool(conn), object(), object()).drain_spool() == 1


@pytest.mark.asyncio
async def test_a_malformed_spool_record_goes_to_deadletter_and_does_not_block_the_rest(monkeypatch, tmp_path):
    monkeypatch.setenv("BILLING_SPOOL_DIR", str(tmp_path))
    bad = {"request_id": "00000000-0000-0000-0000-000000000023", "user_id": "u", "amount_credits": "not-a-number"}
    good = {"request_id": "00000000-0000-0000-0000-000000000024", "user_id": "u", "amount_credits": 1, "service": "litellm"}
    (tmp_path / "billing_spool.jsonl").write_text(json.dumps(bad) + "\n" + json.dumps(good) + "\n")
    conn = FakeConn()
    assert await BillingReconciler(FakePool(conn), object(), object()).drain_spool() == 1
    assert json.loads((tmp_path / "billing_spool.deadletter.jsonl").read_text())["request_id"] == bad["request_id"]
    assert not (tmp_path / "billing_spool.jsonl").exists()


@pytest.mark.asyncio
async def test_reconciler_replays_the_ledger_fields_of_the_original_charge():
    org_row = {
        "id": "row-org", "request_id": "00000000-0000-0000-0000-000000000025", "user_id": "u", "org_id": "o-1",
        "amount_credits": Decimal("0.25"), "provider": "prov", "model": "mod", "tokens": 42, "service": "litellm",
        "metadata": json.dumps({"power_level": "precision", "task_type": "code", "service_name": "openai/gpt-4o"}),
        "created_at": datetime.now(timezone.utc), "attempts": 1,
    }
    indiv_row = {
        "id": "row-ind", "request_id": "00000000-0000-0000-0000-000000000026", "user_id": "u2", "org_id": None,
        "amount_credits": Decimal("0.5"), "provider": "prov", "model": "mod", "tokens": 7, "service": "litellm",
        "metadata": json.dumps({"streaming": True}), "created_at": datetime.now(timezone.utc), "attempts": 1,
    }
    org_calls, debit_calls = [], []

    class Org:
        async def deduct_org_credits(self, **kwargs):
            org_calls.append(kwargs)
            return True, kwargs["org_id"], 1000

    class Credits:
        async def debit_credits(self, **kwargs):
            debit_calls.append(kwargs)
            return 1.0, "tx"

    conn = FakeConn(rows=[org_row, indiv_row])
    assert await BillingReconciler(FakePool(conn), Credits(), Org()).reconcile_once() == 2
    assert org_calls[0]["service_name"] == "openai/gpt-4o"
    assert org_calls[0]["request_id"] == org_row["request_id"] and org_calls[0]["credits_used"] == 0.25
    assert org_calls[0]["power_level"] == "precision" and org_calls[0]["tokens_used"] == 42
    meta = debit_calls[0]["metadata"]
    assert meta["request_id"] == indiv_row["request_id"] and meta["provider"] == "prov"
    assert meta["model"] == "mod" and meta["tokens_used"] == 7 and meta["cost"] == 0.5
    settled = [args for query, args in conn.executed if "settled_at = NOW()" in query]
    assert sorted(a[0] for a in settled) == ["row-ind", "row-org"]


@pytest.mark.asyncio
async def test_a_stale_failing_charge_logs_critical_once_per_hour(caplog):
    row = {
        "id": "row-stale", "request_id": "00000000-0000-0000-0000-000000000027", "user_id": "u", "org_id": "o",
        "amount_credits": Decimal("1"), "provider": "p", "model": "m", "tokens": 1, "service": "litellm",
        "metadata": "{}", "created_at": datetime(2026, 1, 1, tzinfo=timezone.utc), "attempts": 7,
    }

    class Org:
        async def deduct_org_credits(self, **kwargs):
            return False, "o", None  # e.g. insufficient allocation: no exception, just False

    conn = FakeConn(rows=[row])
    reconciler = BillingReconciler(FakePool(conn), object(), Org())
    with caplog.at_level("CRITICAL", logger="billing_settlement"):
        assert await reconciler.reconcile_once() == 0
        assert await reconciler.reconcile_once() == 0
    critical = [r for r in caplog.records if r.levelname == "CRITICAL" and "older than 60 minutes" in r.getMessage()]
    assert len(critical) == 1
    assert any("SET error" in query for query, _ in conn.executed)


@pytest.mark.asyncio
async def test_start_settlement_survives_cancellation_of_the_awaiting_task():
    """A client disconnect cancels the streaming generator; the charge must still land."""
    release = asyncio.Event()
    landed = []

    async def settle():
        await release.wait()
        landed.append(1)

    async def generator_tail():
        task = billing_settlement.start_settlement(settle())
        await asyncio.shield(task)

    consumer = asyncio.ensure_future(generator_tail())
    await asyncio.sleep(0.01)
    consumer.cancel()
    with pytest.raises(asyncio.CancelledError):
        await consumer
    release.set()
    await billing_settlement.wait_for_background_settlements(timeout=2)
    assert landed == [1]
