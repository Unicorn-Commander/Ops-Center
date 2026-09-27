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


class FakeConnection:
    def __init__(self):
        self.calls = []

    async def fetchval(self, query, *args):
        self.calls.append((query, args))
        if query.startswith("SELECT deduct_credits"):
            return True
        return 9876


class FakePool:
    def __init__(self, connection):
        self.connection = connection

    async def acquire(self):
        return self.connection


async def _deduct(credits_used):
    connection = FakeConnection()
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
    deduction_call = connection.calls[0]
    metadata = deduction_call[1][-1]
    assert isinstance(metadata, str)
    assert json.loads(metadata)["model"] == "unit-model"


@pytest.mark.asyncio
async def test_deduction_rounds_and_floors_nonzero_charge():
    (_, _, _), tiny_connection = await _deduct(0.000271)
    (_, _, _), zero_connection = await _deduct(0.0)

    assert tiny_connection.calls[0][1][2] == 1
    assert zero_connection.calls[0][1][2] == 0


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
