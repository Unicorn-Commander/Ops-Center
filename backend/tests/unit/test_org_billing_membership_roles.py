"""Registered org billing mutations authorize before any business DB effects."""
import importlib.util
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock
import sys

import httpx
import pytest
from fastapi import FastAPI, HTTPException

ORG_A = "11111111-1111-4111-8111-111111111111"
ORG_B = "22222222-2222-4222-8222-222222222222"
BACKEND = Path(__file__).resolve().parents[2]


@pytest.fixture
def org_routes(monkeypatch):
    import billing_org_identity as identity
    user = {"sub": "subject", "user_id": "subject", "org_id": ORG_A,
            "email": "same@example.test", "role": "admin", "roles": ["system_admin"]}
    session = {"org_id": ORG_A, "user": user}
    auth = ModuleType("auth_dependencies")
    auth.require_authenticated_user = lambda: user
    auth.require_admin_user = lambda: user
    monkeypatch.setitem(sys.modules, "auth_dependencies", auth)
    spec = importlib.util.spec_from_file_location("org_billing_api", BACKEND / "org_billing_api.py")
    api = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "org_billing_api", api)
    spec.loader.exec_module(api)
    # The real resolver runs; only membership I/O is replaced.
    membership = AsyncMock(return_value=[
        {"org_id": ORG_A, "role": "member"},
        {"org_id": ORG_B, "role": "owner"},
    ])
    monkeypatch.setattr(identity, "_membership_orgs", membership)
    # Stop accepted requests exactly at business I/O, before any writes.
    business = AsyncMock(side_effect=HTTPException(418, "fixture business boundary"))
    monkeypatch.setattr(api, "get_db_connection", business)
    old_admin = AsyncMock(side_effect=AssertionError("No global admin bypass"))
    monkeypatch.setattr(api, "check_system_admin", old_admin)
    monkeypatch.setattr(api, "check_org_admin", old_admin)
    app = FastAPI()
    app.state.sessions = {"fixture": session}
    app.include_router(api.router)
    return SimpleNamespace(app=app, api=api, user=user, session=session,
                           membership=membership, business=business, old_admin=old_admin)


CASES = [
    ("POST", "/subscriptions", {"subscription_plan": "byok", "monthly_price": "1"}),
    ("PUT", "/subscriptions/{org}/upgrade?new_plan=hybrid", None),
    ("POST", "/credits/{org}/add?credits=1", None),
    ("POST", "/credits/{org}/allocate", {"user_id": "recipient", "allocated_credits": 1}),
]


async def request(fixture, case, target=ORG_A):
    method, path, body = case
    if path == "/subscriptions":
        body = dict(body, org_id=target)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=fixture.app), base_url="http://test",
        cookies={"session_token": "fixture"},
    ) as client:
        return await client.request(method, "/api/v1/org-billing" + path.format(org=target), json=body)


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES)
async def test_member_with_global_admin_and_other_org_owner_cannot_mutate(org_routes, case):
    result = await request(org_routes, case)
    assert result.status_code == 403, result.text
    org_routes.business.assert_not_awaited()
    org_routes.old_admin.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES)
@pytest.mark.parametrize("role", ["owner", "admin", "billing_admin"])
async def test_persisted_selected_org_billing_roles_reach_business_boundary(org_routes, case, role):
    org_routes.membership.return_value[0]["role"] = role
    result = await request(org_routes, case)
    assert result.status_code == 418, result.text
    org_routes.business.assert_awaited_once()
    org_routes.old_admin.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES)
async def test_other_authorized_org_target_cannot_override_selection(org_routes, case):
    org_routes.membership.return_value[0]["role"] = "owner"
    result = await request(org_routes, case, ORG_B)
    assert result.status_code == 403, result.text
    org_routes.business.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES)
async def test_selected_org_revoked_membership_denies_before_business_io(org_routes, case):
    org_routes.membership.return_value = [{"org_id": ORG_B, "role": "owner"}]
    result = await request(org_routes, case)
    assert result.status_code == 403, result.text
    org_routes.business.assert_not_awaited()


@pytest.mark.asyncio
async def test_authorized_add_credit_success_uses_canonical_selected_org(org_routes):
    org_routes.membership.return_value[0]["role"] = "billing_admin"
    conn = SimpleNamespace(
        execute=AsyncMock(), fetchrow=AsyncMock(return_value={"total_credits": 1, "available_credits": 1}),
        close=AsyncMock(),
    )
    org_routes.business.side_effect = None
    org_routes.business.return_value = conn
    result = await request(org_routes, CASES[2], "org_" + ORG_A)
    assert result.status_code == 200, result.text
    assert conn.execute.await_args.args[1] == ORG_A
    conn.close.assert_awaited_once()
