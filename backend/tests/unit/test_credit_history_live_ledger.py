"""Focused tests for the credits history's live-ledger read boundary."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import credit_api
import credit_system


ORG_A = "11111111-1111-4111-8111-111111111111"
ORG_B = "22222222-2222-4222-8222-222222222222"


def manager_with_rows(rows):
    conn = MagicMock()
    conn.fetch = AsyncMock(return_value=rows)
    acquire = MagicMock()
    acquire.__aenter__ = AsyncMock(return_value=conn)
    acquire.__aexit__ = AsyncMock(return_value=False)
    manager = credit_system.CreditManager()
    manager.db_pool = SimpleNamespace(acquire=lambda: acquire)
    return manager, conn


def transaction_row(user_id, org_id, transaction_id):
    return {
        "id": transaction_id,
        "user_id": user_id,
        "amount": "-1.25",
        "transaction_type": "usage",
        "provider": "tts",
        "model": "kokoro",
        "cost": "1.25",
        "metadata": {"org_id": org_id},
        "created_at": "2026-11-07T00:00:00Z",
        "total_count": 1,
    }


@pytest.mark.asyncio
async def test_history_reads_live_ledger_and_binds_current_org_and_user():
    manager, conn = manager_with_rows([transaction_row("user-a", ORG_A, "tx-a")])

    history = await manager.get_transaction_history(
        user_id="user-a", org_id=f"org_{ORG_A}", limit=10, offset=20
    )

    query, *params = conn.fetch.await_args.args
    assert "FROM credit_transactions AS ct" in query
    assert "FROM transactions" not in query
    assert "ct.user_id::text = $1" in query
    assert "om.org_id::text = $2" in query
    assert params == ["user-a", ORG_A, 10, 20]
    assert history["total"] == 1
    assert history["transactions"][0]["service"] == "tts"


@pytest.mark.asyncio
async def test_history_does_not_return_another_org_or_user():
    rows = [
        transaction_row("user-a", ORG_A, "tx-a"),
        transaction_row("user-b", ORG_B, "tx-b"),
    ]

    async def rows_for_bound_identity(query, user_id, org_id, limit, offset):
        return [row for row in rows if row["user_id"] == user_id and row["metadata"]["org_id"] == org_id]

    manager, conn = manager_with_rows([])
    conn.fetch.side_effect = rows_for_bound_identity

    history = await manager.get_transaction_history(
        user_id="user-a", org_id=ORG_A, limit=10, offset=0
    )

    assert [row["id"] for row in history["transactions"]] == ["tx-a"]


@pytest.mark.asyncio
async def test_empty_history_is_a_successful_empty_list_response(monkeypatch):
    manager = AsyncMock()
    manager.get_transaction_history.return_value = {"transactions": [], "total": 0}
    monkeypatch.setattr(credit_api, "credit_manager", manager)

    response = await credit_api.get_transactions(
        limit=50,
        offset=0,
        transaction_type=None,
        legacy_transaction_type=None,
        current_user={"user_id": "user-a", "org_id": ORG_A},
    )

    assert response.transactions == []
    assert response.total == 0
    assert response.total_count == 0
    manager.get_transaction_history.assert_awaited_once_with(
        user_id="user-a",
        org_id=ORG_A,
        limit=50,
        offset=0,
        transaction_type=None,
    )


@pytest.mark.asyncio
async def test_endpoint_keeps_frontend_transaction_shape(monkeypatch):
    manager = AsyncMock()
    manager.get_transaction_history.return_value = {
        "transactions": [
            {
                "id": "tx-a",
                "user_id": "user-a",
                "amount": "-1.25",
                "balance_after": None,
                "transaction_type": "usage",
                "service": "tts",
                "model": "kokoro",
                "cost_breakdown": None,
                "metadata": {},
                "description": "usage",
                "created_at": "2026-11-07T00:00:00Z",
            }
        ],
        "total": 1,
    }
    monkeypatch.setattr(credit_api, "credit_manager", manager)

    response = await credit_api.get_transactions(
        limit=25,
        offset=0,
        transaction_type=None,
        legacy_transaction_type=None,
        current_user={"user_id": "user-a", "org_id": ORG_A},
    )

    payload = response.model_dump()
    assert payload["total"] == 1
    assert payload["transactions"][0]["transaction_type"] == "usage"
    assert payload["transactions"][0]["service"] == "tts"
    assert payload["transactions"][0]["description"] == "usage"
