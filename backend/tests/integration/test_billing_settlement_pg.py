"""Real-PostgreSQL proof of the billing settlement queue.

SKIPPED unless BILLING_PGTEST_DSN is set. Point it at a THROWAWAY database
restored from a schema-only dump (``pg_dump -s --no-owner --no-privileges``) of
the Ops-Center database, never at a live one. The tests create the queue table
and lookup indexes the way startup does (ensure_feature_tables.sql), seed their
own synthetic org / users / allocation, and delete them afterwards.

Why this exists: the first version of the queue passed 15 fake-connection unit
tests and failed on its first real statement. asyncpg refused the ISO-string
timestamps and the UUID org_id, and PostgreSQL has no make_interval(mins =>
double precision), so every enqueue fell back to the spool and the reconciler
never settled a row. Five concurrent settlers of one request_id also charged
the org five times. Only a real database shows any of that.

    BILLING_PGTEST_DSN=postgresql://user@host:5432/db python -m pytest \
        tests/integration/test_billing_settlement_pg.py
"""

import asyncio
import json
import os
import pathlib
import uuid
from contextlib import asynccontextmanager
from decimal import Decimal
from urllib.parse import urlparse

import pytest

DSN = os.environ.get("BILLING_PGTEST_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="BILLING_PGTEST_DSN not set (needs a throwaway PostgreSQL)")

try:  # pytest-asyncio strict mode needs its decorator for async fixtures
    import pytest_asyncio
    async_fixture = pytest_asyncio.fixture
except ImportError:  # pragma: no cover
    async_fixture = pytest.fixture

BACKEND = pathlib.Path(__file__).resolve().parents[2]
ORG_CREDITS = 100_000     # millicredits in the synthetic pool
ALLOCATION = 50_000       # millicredits allocated to the synthetic org user
INDIV_BALANCE = Decimal("10")


def _split_sql(sql):
    """The same splitter server.py uses for ensure_feature_tables.sql."""
    stmts, buf, in_dollar = [], [], False
    for line in sql.splitlines():
        buf.append(line)
        if line.count("$$") % 2 == 1:
            in_dollar = not in_dollar
        if not in_dollar and line.rstrip().endswith(";"):
            stmts.append("\n".join(buf))
            buf = []
    if any(s.strip() for s in buf):
        stmts.append("\n".join(buf))
    return stmts


BILLING_DDL_MARKERS = ("billing_unsettled_charges", "idx_credit_usage_request_id", "idx_credit_transactions_request_id")


class FakeRedis:
    async def get(self, *a):
        return None

    async def setex(self, *a):
        return True

    async def delete(self, *a):
        return 1


class DeadPool:
    """A pool whose database is down."""

    @asynccontextmanager
    async def acquire(self):
        raise ConnectionRefusedError("database unavailable")
        yield  # pragma: no cover


@async_fixture
async def env(monkeypatch, tmp_path):
    import asyncpg

    url = urlparse(DSN)
    monkeypatch.setenv("POSTGRES_HOST", url.hostname or "localhost")
    monkeypatch.setenv("POSTGRES_PORT", str(url.port or 5432))
    monkeypatch.setenv("POSTGRES_USER", url.username or "postgres")
    monkeypatch.setenv("POSTGRES_PASSWORD", url.password or "")
    monkeypatch.setenv("POSTGRES_DB", (url.path or "/postgres").lstrip("/"))
    monkeypatch.setenv("BILLING_SPOOL_DIR", str(tmp_path))
    monkeypatch.setenv("BILLING_SETTLE_FAILURE_MODE", "queue")

    pool = await asyncpg.create_pool(DSN, min_size=1, max_size=8)
    sql = (BACKEND / "migrations" / "ensure_feature_tables.sql").read_text()
    async with pool.acquire() as conn:
        for stmt in _split_sql(sql):
            if any(marker in stmt for marker in BILLING_DDL_MARKERS):
                await conn.execute(stmt)

    ns = type("Env", (), {})()
    ns.pool, ns.spool_dir = pool, tmp_path
    ns.org_id = uuid.uuid4()
    ns.org_user = f"pgtest-org-user-{uuid.uuid4()}"
    ns.indiv_user = f"pgtest-indiv-{uuid.uuid4()}"
    ns.zero_user = f"pgtest-zero-{uuid.uuid4()}"
    users = [ns.org_user, ns.indiv_user, ns.zero_user]
    async with pool.acquire() as conn:
        await conn.execute("INSERT INTO organizations (id, name, slug) VALUES ($1, $2, $3)",
                           ns.org_id, f"pgtest-{ns.org_id}", f"pgtest-{ns.org_id}")
        await conn.execute("INSERT INTO organization_members (org_id, user_id, role) VALUES ($1, $2, 'owner')",
                           ns.org_id, ns.org_user)
        await conn.execute("INSERT INTO organization_credit_pools (org_id, total_credits) VALUES ($1, $2)",
                           ns.org_id, ORG_CREDITS)
        await conn.fetchval("SELECT allocate_credits_to_user($1, $2, $3, $4)",
                            ns.org_id, ns.org_user, ALLOCATION, "pgtest")
        await conn.execute("INSERT INTO user_credits (user_id, credits_remaining, credits_allocated, tier) "
                           "VALUES ($1, $2, $2, 'professional')", ns.indiv_user, INDIV_BALANCE)
        await conn.execute("INSERT INTO user_credits (user_id, credits_remaining, credits_allocated, tier) "
                           "VALUES ($1, 1.5, 1.5, 'professional')", ns.zero_user)
        # the live path gets org_id from organization_members.org_id: an asyncpg UUID, not a str
        ns.org_id_as_live = await conn.fetchval("SELECT org_id FROM organization_members WHERE user_id = $1", ns.org_user)

    from litellm_credit_system import CreditSystem
    from org_credit_integration import OrgCreditIntegration
    ns.credits = CreditSystem(pool, FakeRedis())
    ns.org = OrgCreditIntegration()  # the live singleton has no pool: one connection per call

    async def org_used():
        return await pool.fetchval("SELECT used_credits FROM user_credit_allocations WHERE org_id = $1 AND user_id = $2",
                                   ns.org_id, ns.org_user)

    async def attribution_rows(request_id):
        return await pool.fetchval("SELECT count(*) FROM credit_usage_attribution WHERE request_id = $1", request_id)

    async def balance(user):
        return await pool.fetchval("SELECT credits_remaining FROM user_credits WHERE user_id = $1", user)

    async def txn_rows(user, request_id):
        return await pool.fetchval("SELECT count(*) FROM credit_transactions WHERE user_id = $1 "
                                   "AND metadata->>'request_id' = $2", user, request_id)

    async def queue_row(request_id):
        return await pool.fetchrow("SELECT * FROM billing_unsettled_charges WHERE request_id = $1::uuid", request_id)

    ns.org_used, ns.attribution_rows, ns.balance = org_used, attribution_rows, balance
    ns.txn_rows, ns.queue_row = txn_rows, queue_row
    try:
        yield ns
    finally:
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM billing_unsettled_charges WHERE user_id = ANY($1::varchar[])", users)
            await conn.execute("DELETE FROM credit_transactions WHERE user_id = ANY($1::varchar[])", users)
            await conn.execute("DELETE FROM user_credits WHERE user_id = ANY($1::varchar[])", users)
            for table in ("credit_usage_attribution", "user_credit_allocations",
                          "organization_credit_pools", "organization_members"):
                await conn.execute(f"DELETE FROM {table} WHERE org_id = $1", ns.org_id)
            await conn.execute("DELETE FROM organizations WHERE id = $1", ns.org_id)
        await pool.close()


def _org_charge(env, amount=0.25, request_id=None):
    """The record chat_completions queues for an org-billed call (org_id as the live path has it)."""
    return {
        "request_id": request_id or str(uuid.uuid4()), "user_id": env.org_user, "org_id": env.org_id_as_live,
        "amount_credits": amount, "provider": "pgtest-provider", "model": "pgtest-model", "tokens": 30,
        "service": "litellm",
        "metadata": {"power_level": "balanced", "task_type": "chat", "service_name": "pgtest/served-model"},
    }


def _indiv_charge(env, amount=0.5, request_id=None, user=None):
    return {
        "request_id": request_id or str(uuid.uuid4()), "user_id": user or env.indiv_user, "org_id": None,
        "amount_credits": amount, "provider": "pgtest-provider", "model": "pgtest-model", "tokens": 12,
        "service": "litellm", "metadata": {"power_level": "balanced", "task_type": "chat", "streaming": True},
    }


def _reconciler(env, pool=None):
    from billing_settlement import BillingReconciler
    return BillingReconciler(pool or env.pool, env.credits, env.org)


@pytest.mark.asyncio
async def test_enqueue_lands_a_row_with_the_types_the_live_path_passes(env):
    from billing_settlement import enqueue_unsettled_charge

    record = _org_charge(env, amount=0.000271)
    assert type(record["org_id"]).__name__ == "UUID" and not isinstance(record["org_id"], str)
    assert await enqueue_unsettled_charge(env.pool, record) is True
    row = await env.queue_row(record["request_id"])
    assert row is not None
    assert row["org_id"] == str(env.org_id) and row["amount_credits"] == Decimal("0.00027100")
    assert row["created_at"] is not None and row["settled_at"] is None and row["attempts"] == 0
    assert json.loads(row["metadata"])["service_name"] == "pgtest/served-model"
    assert not (env.spool_dir / "billing_spool.jsonl").exists()
    # the same request queued twice stays one row
    assert await enqueue_unsettled_charge(env.pool, record) is True
    assert await env.pool.fetchval("SELECT count(*) FROM billing_unsettled_charges WHERE request_id = $1::uuid",
                                   record["request_id"]) == 1


@pytest.mark.asyncio
async def test_spool_fallback_then_drain_into_the_table(env):
    from billing_settlement import enqueue_unsettled_charge

    record = _org_charge(env)
    assert await enqueue_unsettled_charge(DeadPool(), record) is False
    spooled = (env.spool_dir / "billing_spool.jsonl").read_text().splitlines()
    assert [json.loads(line)["request_id"] for line in spooled] == [record["request_id"]]
    assert await env.queue_row(record["request_id"]) is None

    assert await _reconciler(env, pool=DeadPool()).drain_spool() == 0  # still down: the line is kept
    assert (env.spool_dir / "billing_spool.jsonl").exists()
    assert await _reconciler(env).drain_spool() == 1
    assert not (env.spool_dir / "billing_spool.jsonl").exists()
    row = await env.queue_row(record["request_id"])
    assert row["org_id"] == str(env.org_id) and row["settled_at"] is None
    assert await _reconciler(env).drain_spool() == 0


@pytest.mark.asyncio
async def test_reconciler_claims_and_settles_each_ledger_exactly_once(env):
    from billing_settlement import enqueue_unsettled_charge

    org_charge, indiv_charge = _org_charge(env), _indiv_charge(env)
    used0, bal0 = await env.org_used(), await env.balance(env.indiv_user)
    await enqueue_unsettled_charge(env.pool, org_charge)
    await enqueue_unsettled_charge(env.pool, indiv_charge)

    assert await _reconciler(env).reconcile_once() == 2
    assert await env.org_used() == used0 + 250
    assert await env.attribution_rows(org_charge["request_id"]) == 1
    assert await env.balance(env.indiv_user) == bal0 - Decimal("0.5")
    assert await env.txn_rows(env.indiv_user, indiv_charge["request_id"]) == 1
    for charge in (org_charge, indiv_charge):
        row = await env.queue_row(charge["request_id"])
        assert row["settled_at"] is not None and row["attempts"] == 1
    attribution = await env.pool.fetchrow(
        "SELECT service_name, request_metadata FROM credit_usage_attribution WHERE request_id = $1",
        org_charge["request_id"])
    assert attribution["service_name"] == "pgtest/served-model"
    txn = await env.pool.fetchrow("SELECT provider, model, tokens_used, metadata FROM credit_transactions "
                                  "WHERE metadata->>'request_id' = $1", indiv_charge["request_id"])
    assert (txn["provider"], txn["model"], txn["tokens_used"]) == ("pgtest-provider", "pgtest-model", 12)

    assert await _reconciler(env).reconcile_once() == 0  # nothing left due
    assert await env.org_used() == used0 + 250
    assert await env.balance(env.indiv_user) == bal0 - Decimal("0.5")


@pytest.mark.asyncio
async def test_a_charge_that_landed_inline_is_not_charged_again_by_the_reconciler(env):
    """The deduction committed but its caller saw an error (lost response): the queue must only mark it."""
    from billing_settlement import enqueue_unsettled_charge

    org_charge, indiv_charge = _org_charge(env), _indiv_charge(env)
    ok, _, _ = await env.org.deduct_org_credits(
        user_id=env.org_user, credits_used=0.25, service_name="pgtest/served-model", provider="p", model="m",
        tokens_used=30, power_level="balanced", task_type="chat",
        request_id=org_charge["request_id"], org_id=env.org_id_as_live)
    assert ok is True
    await env.credits.debit_credits(user_id=env.indiv_user, amount=0.5,
                                    metadata={"request_id": indiv_charge["request_id"], "cost": 0.5})
    used1, bal1 = await env.org_used(), await env.balance(env.indiv_user)
    await enqueue_unsettled_charge(env.pool, org_charge)
    await enqueue_unsettled_charge(env.pool, indiv_charge)

    assert await _reconciler(env).reconcile_once() == 2
    assert await env.org_used() == used1
    assert await env.attribution_rows(org_charge["request_id"]) == 1
    assert await env.balance(env.indiv_user) == bal1
    assert await env.txn_rows(env.indiv_user, indiv_charge["request_id"]) == 1


@pytest.mark.asyncio
async def test_concurrent_settlers_of_one_request_id_move_each_ledger_once(env):
    """Before the advisory lock, 5 concurrent org settlers of one request_id charged 5x."""
    org_charge, indiv_charge = _org_charge(env), _indiv_charge(env)
    used0, bal0 = await env.org_used(), await env.balance(env.indiv_user)
    reconcilers = [_reconciler(env) for _ in range(5)]
    # simulate claims that raced (e.g. a retry outliving its backoff): all five settle the same row
    org_row = {**org_charge, "org_id": str(env.org_id), "metadata": json.dumps(org_charge["metadata"])}
    indiv_row = {**indiv_charge, "metadata": json.dumps(indiv_charge["metadata"])}
    results = await asyncio.gather(*[r._settle(dict(org_row)) for r in reconcilers],
                                   *[r._settle(dict(indiv_row)) for r in reconcilers])
    assert all(results)
    assert await env.org_used() == used0 + 250
    assert await env.attribution_rows(org_charge["request_id"]) == 1
    assert await env.balance(env.indiv_user) == bal0 - Decimal("0.5")
    assert await env.txn_rows(env.indiv_user, indiv_charge["request_id"]) == 1


@pytest.mark.asyncio
async def test_two_concurrent_reconcilers_claim_disjoint_rows(env):
    from billing_settlement import enqueue_unsettled_charge

    charges = [_org_charge(env) for _ in range(4)] + [_indiv_charge(env, amount=0.25) for _ in range(4)]
    used0, bal0 = await env.org_used(), await env.balance(env.indiv_user)
    for charge in charges:
        await enqueue_unsettled_charge(env.pool, charge)
    settled = await asyncio.gather(_reconciler(env).reconcile_once(), _reconciler(env).reconcile_once())
    assert sum(settled) == len(charges)
    assert await env.org_used() == used0 + 4 * 250
    assert await env.balance(env.indiv_user) == bal0 - Decimal("1.0")
    for charge in charges:
        row = await env.queue_row(charge["request_id"])
        assert row["settled_at"] is not None and row["attempts"] == 1  # claimed exactly once
    for charge in charges[:4]:
        assert await env.attribution_rows(charge["request_id"]) == 1
    for charge in charges[4:]:
        assert await env.txn_rows(env.indiv_user, charge["request_id"]) == 1


@pytest.mark.asyncio
async def test_failed_retry_backs_off_and_records_the_error(env):
    from billing_settlement import enqueue_unsettled_charge

    too_big = _org_charge(env, amount=1_000.0)  # more than the allocation: deduct_credits raises
    await enqueue_unsettled_charge(env.pool, too_big)
    assert await _reconciler(env).reconcile_once() == 0
    row = await env.queue_row(too_big["request_id"])
    assert row["settled_at"] is None and row["attempts"] == 1 and row["error"]
    assert await _reconciler(env).reconcile_once() == 0
    assert (await env.queue_row(too_big["request_id"]))["attempts"] == 1  # inside its backoff: not re-claimed
    await env.pool.execute("UPDATE billing_unsettled_charges SET last_attempt_at = NOW() - INTERVAL '3 minutes', "
                           "attempts = 1000 WHERE request_id = $1::uuid", too_big["request_id"])
    assert await _reconciler(env).reconcile_once() == 0  # the backoff expression cannot overflow
    assert (await env.queue_row(too_big["request_id"]))["attempts"] == 1000  # 60 min cap applies
    await env.pool.execute("UPDATE billing_unsettled_charges SET last_attempt_at = NOW() - INTERVAL '61 minutes' "
                           "WHERE request_id = $1::uuid", too_big["request_id"])
    assert await _reconciler(env).reconcile_once() == 0
    assert (await env.queue_row(too_big["request_id"]))["attempts"] == 1001


@pytest.mark.asyncio
async def test_concurrent_drains_insert_each_spooled_charge_once(env):
    from billing_settlement import enqueue_unsettled_charge

    charges = [_org_charge(env) for _ in range(5)]
    for charge in charges:
        await enqueue_unsettled_charge(DeadPool(), charge)
    drained = await asyncio.gather(_reconciler(env).drain_spool(), _reconciler(env).drain_spool())
    assert sum(drained) == 5
    for charge in charges:
        assert await env.pool.fetchval("SELECT count(*) FROM billing_unsettled_charges WHERE request_id = $1::uuid",
                                       charge["request_id"]) == 1
    assert not (env.spool_dir / "billing_spool.jsonl").exists()


@pytest.mark.asyncio
async def test_a_debit_that_leaves_a_zero_balance_keeps_its_transaction_id(env):
    from billing_settlement import settle_or_queue

    request_id = str(uuid.uuid4())
    settlement = await settle_or_queue(
        pool=env.pool,
        settle=lambda: env.credits.debit_credits(user_id=env.zero_user, amount=1.5,
                                                 metadata={"request_id": request_id, "cost": 1.5}),
        result_ok=lambda _result: True,
        record=_indiv_charge(env, amount=1.5, request_id=request_id, user=env.zero_user),
    )
    assert settlement  # (0, txn_id) is a truthy tuple: the handler keeps the id
    new_balance, transaction_id = settlement
    assert new_balance == 0 and transaction_id
    assert await env.pool.fetchval("SELECT id::text FROM credit_transactions WHERE metadata->>'request_id' = $1",
                                   request_id) == transaction_id
    assert await env.queue_row(request_id) is None  # nothing queued


@pytest.mark.asyncio
async def test_service_org_debit_lands_even_when_the_usage_log_insert_fails(env):
    """A caught failing INSERT inside the debit transaction aborted it, so COMMIT became
    ROLLBACK: every service-org debit on a schema without service_usage_log reported success
    and moved nothing. The optional log insert now runs in a savepoint. endpoint=None makes
    the insert fail server-side on any schema (NOT NULL, or the table is missing)."""
    service_org = uuid.uuid4()
    async with env.pool.acquire() as conn:
        await conn.execute("INSERT INTO organizations (id, name, slug, plan_tier) VALUES ($1, $2, $3, 'managed')",
                           service_org, f"pgtest-svc-{service_org}", f"pgtest-svc-{service_org}")
        await conn.execute("INSERT INTO organization_credit_pools (org_id, total_credits) VALUES ($1, 1000)", service_org)
    try:
        new_balance, _ = await env.credits.debit_credits(
            user_id=f"org_{service_org}", amount=2.0,
            metadata={"model": "pgtest-model", "request_id": str(uuid.uuid4()), "endpoint": None},
        )
        assert new_balance == 998.0
        assert await env.pool.fetchval("SELECT used_credits FROM organization_credit_pools WHERE org_id = $1",
                                       service_org) == 2
    finally:
        async with env.pool.acquire() as conn:
            if await conn.fetchval("SELECT to_regclass('service_usage_log') IS NOT NULL"):
                await conn.execute("DELETE FROM service_usage_log WHERE service_org_id = $1", service_org)
            await conn.execute("DELETE FROM organization_credit_pools WHERE org_id = $1", service_org)
            await conn.execute("DELETE FROM organizations WHERE id = $1", service_org)
