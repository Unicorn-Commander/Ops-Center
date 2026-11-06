"""Regression coverage for organization-create plan-tier authorization."""

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
import sys

import pytest
from fastapi import HTTPException

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import org_api


class _CreateConnection:
    """Small asyncpg-shaped fixture for the org-create transaction."""

    def __init__(self, valid_tiers):
        self.valid_tiers = set(valid_tiers)
        self.created_org = None
        self.member_inserted = False
        self.closed = False
        self.queries = []

    async def fetchrow(self, query, *params):
        self.queries.append((query, params))
        if "FROM subscription_tiers" in query:
            tier_code = params[0]
            return {"tier_code": tier_code} if tier_code in self.valid_tiers else None
        if "LOWER(name)" in query:
            return None
        if "INSERT INTO organizations" in query:
            self.created_org = {
                "id": "00000000-0000-4000-8000-000000000001",
                "name": params[0],
                "plan_tier": params[1],
                "status": "active",
                "created_at": datetime.now(timezone.utc),
                "lago_customer_id": None,
                "stripe_customer_id": None,
            }
            return self.created_org
        raise AssertionError(f"unexpected fetchrow query: {query}")

    @asynccontextmanager
    async def transaction(self):
        yield self

    async def execute(self, query, *params):
        if "INSERT INTO organization_members" in query:
            self.member_inserted = True
            assert params[1] in {"fictional-user", "fictional-admin"}

    async def close(self):
        self.closed = True


async def _create(name, plan_tier=None, request_user=None, monkeypatch=None):
    connection = _CreateConnection(valid_tiers={"managed"})

    async def current_user(_request):
        return request_user or {"id": "fictional-user", "role": "user"}

    async def db_connection():
        return connection

    monkeypatch.setattr(org_api, "get_current_user", current_user)
    monkeypatch.setattr(org_api, "get_db_connection", db_connection)
    payload = {"name": name}
    if plan_tier is not None:
        payload["plan_tier"] = plan_tier
    result = await org_api.create_organization(
        org_api.OrganizationCreate(**payload),
        object(),
    )
    return result, connection


@pytest.mark.asyncio
async def test_non_admin_cannot_create_managed_org(monkeypatch):
    with pytest.raises(HTTPException) as exc_info:
        await _create(
            "Fictional Managed Workspace",
            plan_tier="managed",
            monkeypatch=monkeypatch,
        )

    assert exc_info.value.status_code == 403
    assert "free" in exc_info.value.detail


@pytest.mark.asyncio
async def test_admin_valid_tier_is_stored(monkeypatch):
    result, connection = await _create(
        "Fictional Managed Workspace",
        plan_tier="managed",
        request_user={"id": "fictional-admin", "role": "admin"},
        monkeypatch=monkeypatch,
    )

    assert result["organization"]["plan_tier"] == "managed"
    assert connection.created_org["plan_tier"] == "managed"
    assert connection.member_inserted is True
    assert connection.closed is True
    assert any("FROM subscription_tiers" in query for query, _ in connection.queries)


@pytest.mark.asyncio
async def test_admin_unknown_tier_is_rejected_before_insert(monkeypatch):
    connection = _CreateConnection(valid_tiers={"managed"})

    async def current_user(_request):
        return {"id": "fictional-admin", "role": "admin"}

    async def db_connection():
        return connection

    monkeypatch.setattr(org_api, "get_current_user", current_user)
    monkeypatch.setattr(org_api, "get_db_connection", db_connection)

    with pytest.raises(HTTPException) as exc_info:
        await org_api.create_organization(
            org_api.OrganizationCreate(
                name="Fictional Unknown Tier Workspace",
                plan_tier="not-a-catalog-tier",
            ),
            object(),
        )

    assert exc_info.value.status_code == 400
    assert "Unknown organization plan_tier" in exc_info.value.detail
    assert connection.created_org is None
    assert connection.member_inserted is False
    assert connection.closed is True


@pytest.mark.asyncio
async def test_default_plan_tier_remains_free(monkeypatch):
    result, connection = await _create(
        "Fictional Free Workspace",
        monkeypatch=monkeypatch,
    )

    assert result["organization"]["plan_tier"] == "free"
    assert connection.created_org["plan_tier"] == "free"
    assert not any("FROM subscription_tiers" in query for query, _ in connection.queries)
