"""Focused unit coverage for the 2026-07-31 billing fixes.

These tests deliberately use a fake asyncpg-like connection.  They do not
connect to Postgres or an LLM provider.
"""

import ast
import json
from pathlib import Path

import pytest

from org_credit_integration import OrgCreditIntegration


LITELLM_SOURCE = Path(__file__).parents[2] / "litellm_api.py"


class FakeTransaction:
    def __init__(self, connection):
        self.connection = connection

    async def __aenter__(self):
        self.connection.calls.append(("BEGIN", ()))
        return self

    async def __aexit__(self, exc_type, exc, tb):
        self.connection.calls.append(("ROLLBACK" if exc_type else "COMMIT", ()))
        return False


class FakeConnection:
    def __init__(self, already_recorded=False):
        self.calls = []
        self.already_recorded = already_recorded

    def transaction(self):
        return FakeTransaction(self)

    async def execute(self, query, *args):
        self.calls.append((query, args))

    async def fetchval(self, query, *args):
        self.calls.append((query, args))
        if query.startswith("SELECT deduct_credits"):
            return True
        if "FROM credit_usage_attribution" in query:
            # idempotency pre-check: has this request_id already been charged?
            return self.already_recorded
        return 9876

    def deduction_call(self):
        return next(call for call in self.calls if call[0].startswith("SELECT deduct_credits"))


class FakePool:
    def __init__(self, connection):
        self.connection = connection

    async def acquire(self):
        return self.connection


async def _deduct(credits_used, already_recorded=False):
    connection = FakeConnection(already_recorded)
    integration = OrgCreditIntegration(FakePool(connection))
    result = await integration.deduct_org_credits(
        user_id="unit-user",
        credits_used=credits_used,
        service_name="unit-model",
        provider="unit-provider",
        model="unit-model",
        tokens_used=7,
        power_level="balanced",
        task_type="unit-test",
        request_id="unit-request",
        org_id="unit-org",
    )
    return result, connection


@pytest.mark.asyncio
async def test_deduction_serializes_metadata_and_preserves_json_values():
    (success, _, _), connection = await _deduct(0.25)

    assert success is True
    deduction_call = connection.deduction_call()
    metadata = deduction_call[1][-1]
    assert isinstance(metadata, str)
    assert json.loads(metadata)["model"] == "unit-model"


@pytest.mark.asyncio
async def test_deduction_rounds_and_floors_nonzero_charge():
    (_, _, _), tiny_connection = await _deduct(0.000271)
    (_, _, _), zero_connection = await _deduct(0.0)

    assert tiny_connection.deduction_call()[1][2] == 1
    assert zero_connection.deduction_call()[1][2] == 0


@pytest.mark.asyncio
async def test_retry_of_an_already_charged_request_id_does_not_deduct_again():
    """Reconciler retries pass the original request_id; a charge that already landed must not land twice."""
    (success, org_id, _), connection = await _deduct(0.25, already_recorded=True)

    assert success is True and org_id == "unit-org"
    assert not any(query.startswith("SELECT deduct_credits") for query, _ in connection.calls)


@pytest.mark.asyncio
async def test_dedup_check_and_deduction_are_one_locked_transaction():
    """A check-then-act across two autocommit statements let 5 concurrent settlers of one
    request_id charge 5x on a real database. The advisory lock and the deduction must sit
    inside one transaction, lock first."""
    (_, _, _), connection = await _deduct(0.25)
    queries = [query for query, _ in connection.calls]
    begin = queries.index("BEGIN")
    lock = next(i for i, q in enumerate(queries) if "pg_advisory_xact_lock" in q)
    check = next(i for i, q in enumerate(queries) if "FROM credit_usage_attribution" in q)
    deduct = next(i for i, q in enumerate(queries) if q.startswith("SELECT deduct_credits"))
    commit = queries.index("COMMIT")
    assert begin < lock < check < deduct < commit
    lock_args = connection.calls[lock][1]
    assert lock_args == ("billing:request:unit-request",)


def test_streaming_generator_contains_org_deduction_call():
    """The post-SSE settlement must remain in the live streaming path."""
    source = LITELLM_SOURCE.read_text(encoding="utf-8")
    tree = ast.parse(source)
    chat_functions = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "chat_completions"
    ]

    assert len(chat_functions) == 1
    stream_generators = [
        node
        for node in ast.walk(chat_functions[0])
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "stream_generator"
    ]
    assert len(stream_generators) == 1
    assert any(
        isinstance(node, ast.Attribute) and node.attr == "deduct_org_credits"
        for node in ast.walk(stream_generators[0])
    )
