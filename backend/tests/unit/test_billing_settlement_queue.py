import json
from contextlib import asynccontextmanager

import pytest

from billing_settlement import BillingReconciler, enqueue_unsettled_charge, settle_or_queue
from litellm_api import ChatMessage, estimate_chat_tokens


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


@pytest.mark.parametrize("maximum,expected", [(7, 10), (None, 1027)])
def test_preflight_estimate_includes_completion_allowance(maximum, expected):
    messages = [ChatMessage(role="user", content="one two")]
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
        "request_id": request_id, "user_id": "u", "org_id": None,
        "amount_credits": 4, "provider": "p", "model": "m", "tokens": 2,
        "service": "litellm", "metadata": {}, "created_at": None,
    }
    conn = FakeConn(rows=[row])
    debits = []

    async def debit(**kwargs):
        debits.append(kwargs)
        return (10, "tx")

    reconciler = BillingReconciler(FakePool(conn), type("Credits", (), {"debit_credits": debit})(), object())
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
