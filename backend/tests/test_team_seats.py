"""Focused fictional fixtures for Team invitations and extra-seat billing."""

import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException

import org_api


BACKEND = Path(__file__).resolve().parents[1]


ORG_ID = "00000000-0000-4000-8000-000000000101"
OWNER_SUB = "kc-owner-fictional"
INVITED_SUB = "kc-invited-fictional"
EXISTING_EMAIL = "mira@example.com"
NEW_EMAIL = "tomas@example.com"


class FakeOrgConnection:
    def __init__(
        self,
        *,
        member_count=1,
        max_seats=5,
        included_seats=5,
        plan_tier="founder_workspace",
        existing_role=None,
        pending_count=0,
    ):
        self.member_count = member_count
        self.pending_count = pending_count
        self.invitation_inserted = None
        self.org = {
            "id": ORG_ID,
            "name": "Fictional Lantern Labs",
            "plan_tier": plan_tier,
            "max_seats": max_seats,
            "seat_cap": max_seats,
            "included_seats": included_seats,
        }
        self.existing_role = existing_role
        self.inserted = None
        self.closed = False

    async def fetchval(self, query, *params):
        assert "COUNT(*)" in query
        assert params == (ORG_ID,)
        if "organization_invitations" in query:
            return self.pending_count
        return self.member_count

    async def fetchrow(self, query, *params):
        if "organization_invitations" in query and "SELECT id" in query:
            return None
        if "INSERT INTO organization_invitations" in query:
            self.invitation_inserted = params
            return {
                "id": "invite-fictional",
                "expires_at": datetime(2026, 11, 15, tzinfo=timezone.utc),
            }
        if "SELECT role" in query:
            return {"role": self.existing_role} if self.existing_role else None
        if "FROM organizations" in query:
            return self.org
        raise AssertionError(f"unexpected query: {query}")

    async def execute(self, query, *params):
        if "INSERT INTO organization_members" in query:
            self.inserted = params
            return "INSERT 0 1"
        raise AssertionError(f"unexpected execute: {query}")

    async def close(self):
        self.closed = True


def allow_org_write(monkeypatch):
    monkeypatch.setattr(org_api, "verify_org_access", AsyncMock())


def owner_session(monkeypatch):
    actor = {"id": OWNER_SUB, "email": "owner@example.com", "role": "user"}
    monkeypatch.setattr(org_api, "get_current_user", AsyncMock(return_value=actor))
    return actor
    monkeypatch.setattr(
        org_api,
        "get_current_user",
        AsyncMock(return_value={
            "id": OWNER_SUB,
            "email": "owner@example.com",
            "role": "admin",
        }),
    )


def fake_module(monkeypatch, name, **attributes):
    module = ModuleType(name)
    module.__dict__.update(attributes)
    monkeypatch.setitem(sys.modules, name, module)
    return module


def import_backend_module(monkeypatch, name):
    spec = importlib.util.spec_from_file_location(name, BACKEND / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def stripe_api_module(monkeypatch):
    fake_module(monkeypatch, "get_credential", get_credential=lambda name: None)
    fake_module(monkeypatch, "stripe_integration", stripe_integration=SimpleNamespace())
    fake_module(
        monkeypatch,
        "keycloak_integration",
        get_user_by_email=AsyncMock(),
        get_user_tier_info=AsyncMock(),
    )
    fake_module(monkeypatch, "subscription_manager", subscription_manager=SimpleNamespace())
    fake_module(monkeypatch, "redis_session", redis_session_manager=SimpleNamespace(get=lambda token: None))
    return import_backend_module(monkeypatch, "stripe_api")


@pytest.fixture
def webhooks_module(monkeypatch):
    fake_module(monkeypatch, "get_credential", get_credential=lambda name: None)
    fake_module(
        monkeypatch,
        "keycloak_integration",
        get_user_by_email=AsyncMock(),
        update_user_attributes=AsyncMock(),
    )
    fake_module(
        monkeypatch,
        "lago_integration",
        **{
            name: AsyncMock()
            for name in ("create_subscription", "terminate_subscription", "get_subscription", "update_subscription_plan")
        },
    )
    fake_module(monkeypatch, "email_notifications", EmailNotificationService=Mock())
    fake_module(
        monkeypatch,
        "paid_org_provisioning",
        provision_paid_org=AsyncMock(),
        downgrade_org=AsyncMock(),
    )
    fake_module(monkeypatch, "database", get_db_connection=AsyncMock())
    return import_backend_module(monkeypatch, "webhooks")


@pytest.mark.asyncio
async def test_invite_existing_keycloak_user_stays_pending(monkeypatch):
    connection = FakeOrgConnection()
    allow_org_write(monkeypatch)
    owner_session(monkeypatch)
    monkeypatch.setattr(org_api, "get_db_connection", AsyncMock(return_value=connection))
    lookup = AsyncMock(return_value={"id": INVITED_SUB, "email": EXISTING_EMAIL})
    create = AsyncMock()
    action_email = AsyncMock()
    monkeypatch.setattr(org_api, "get_user_by_email", lookup)
    monkeypatch.setattr(org_api, "keycloak_create_user", create)
    monkeypatch.setattr(org_api, "send_account_action_email", action_email)

    result = await org_api.add_organization_member(
        ORG_ID,
        org_api.OrganizationMemberAdd(email=EXISTING_EMAIL, role="member"),
        object(),
    )

    assert result["success"] is True
    assert result["pending"] is True
    assert result["membership_added"] is False
    assert result["email"] == EXISTING_EMAIL
    assert "sign in" in result["message"]
    assert connection.inserted is None
    assert connection.invitation_inserted[:3] == (ORG_ID, EXISTING_EMAIL, "member")
    create.assert_not_awaited()
    action_email.assert_not_awaited()
    assert connection.closed is True


@pytest.mark.asyncio
async def test_platform_admin_new_user_is_passwordless_and_sends_actions(monkeypatch):
    connection = FakeOrgConnection()
    monkeypatch.setattr(
        org_api,
        "get_current_user",
        AsyncMock(return_value={
            "id": "platform-admin-fictional",
            "email": "admin@example.com",
            "role": "platform_admin",
        }),
    )
    monkeypatch.setattr(org_api, "get_db_connection", AsyncMock(return_value=connection))
    monkeypatch.setattr(org_api, "get_user_by_email", AsyncMock(return_value=None))
    create = AsyncMock(return_value=INVITED_SUB)
    action_email = AsyncMock(return_value={"success": True})
    monkeypatch.setattr(org_api, "keycloak_create_user", create)
    monkeypatch.setattr(org_api, "send_account_action_email", action_email)

    result = await org_api.add_organization_member(
        ORG_ID,
        org_api.OrganizationMemberAdd(
            email=NEW_EMAIL,
            role="member",
            firstName="Tomas",
            lastName="Vale",
        ),
        object(),
    )

    kwargs = create.await_args.kwargs
    assert result["created"] is True
    assert result["pending"] is False
    assert "pending" not in result["message"].lower()
    assert kwargs["email"] == NEW_EMAIL
    assert kwargs["email_verified"] is False
    assert kwargs["attributes"] == {
        "org_id": [ORG_ID],
        "org_name": ["Fictional Lantern Labs"],
        "org_role": ["member"],
    }
    assert "password" not in kwargs
    action_email.assert_awaited_once_with(INVITED_SUB, ["UPDATE_PASSWORD", "VERIFY_EMAIL"])
    assert connection.inserted == (ORG_ID, INVITED_SUB, "member")


@pytest.mark.asyncio
async def test_member_cannot_invite(monkeypatch):
    owner_session(monkeypatch)
    denied = AsyncMock(side_effect=HTTPException(403, "Role 'admin' or higher required"))
    monkeypatch.setattr(org_api, "verify_org_access", denied)
    monkeypatch.setattr(
        org_api,
        "get_current_user",
        AsyncMock(return_value={"id": "kc-member-fictional", "email": "member@example.com", "role": "user"}),
    )
    db = AsyncMock()
    monkeypatch.setattr(org_api, "get_db_connection", db)

    with pytest.raises(HTTPException) as exc_info:
        await org_api.add_organization_member(
            ORG_ID,
            org_api.OrganizationMemberAdd(email=NEW_EMAIL),
            object(),
        )

    assert exc_info.value.status_code == 403
    db.assert_not_awaited()


@pytest.mark.asyncio
async def test_invite_over_cap_returns_seat_details(monkeypatch):
    connection = FakeOrgConnection(member_count=5, max_seats=5)
    allow_org_write(monkeypatch)
    owner_session(monkeypatch)
    monkeypatch.setattr(org_api, "get_db_connection", AsyncMock(return_value=connection))
    lookup = AsyncMock()
    monkeypatch.setattr(org_api, "get_user_by_email", lookup)

    response = await org_api.add_organization_member(
        ORG_ID,
        org_api.OrganizationMemberAdd(email=NEW_EMAIL),
        object(),
    )

    body = json.loads(response.body)
    assert response.status_code == 402
    assert body == {
        "detail": "Organization has reached its seat limit (5/5).",
        "seats_used": 5,
        "max_seats": 5,
        "add_seat_url": "/api/v1/billing/seats",
    }
    lookup.assert_not_awaited()
    assert connection.inserted is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("plan_tier", "max_seats", "included_seats"),
    [
        ("free", 1, 1),
        ("founder_friend", 1, 5),
    ],
)
async def test_uncapped_tiers_allow_invites_past_persisted_seat_value(
    monkeypatch, plan_tier, max_seats, included_seats
):
    connection = FakeOrgConnection(
        member_count=1,
        max_seats=max_seats,
        included_seats=included_seats,
        plan_tier=plan_tier,
    )
    allow_org_write(monkeypatch)
    owner_session(monkeypatch)
    monkeypatch.setattr(org_api, "get_db_connection", AsyncMock(return_value=connection))
    monkeypatch.setattr(
        org_api,
        "get_user_by_email",
        AsyncMock(return_value={"id": INVITED_SUB, "email": NEW_EMAIL}),
    )

    result = await org_api.add_organization_member(
        ORG_ID,
        org_api.OrganizationMemberAdd(email=NEW_EMAIL),
        object(),
    )

    assert result["success"] is True
    assert result["pending"] is True
    assert connection.inserted is None
    assert connection.invitation_inserted[:3] == (ORG_ID, NEW_EMAIL, "member")


@pytest.mark.asyncio
async def test_byok_cap_uses_solo_detail_without_add_seat_url(monkeypatch):
    connection = FakeOrgConnection(
        member_count=1,
        max_seats=1,
        included_seats=1,
        plan_tier="byok",
    )
    allow_org_write(monkeypatch)
    owner_session(monkeypatch)
    monkeypatch.setattr(org_api, "get_db_connection", AsyncMock(return_value=connection))
    lookup = AsyncMock()
    monkeypatch.setattr(org_api, "get_user_by_email", lookup)

    response = await org_api.add_organization_member(
        ORG_ID,
        org_api.OrganizationMemberAdd(email=NEW_EMAIL),
        object(),
    )

    body = json.loads(response.body)
    assert response.status_code == 402
    assert body["detail"] == "Solo includes 1 seat; upgrade to the Team workspace to invite teammates."
    assert body["seats_used"] == 1
    assert body["max_seats"] == 1
    assert "add_seat_url" not in body
    lookup.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("max_seats", "included_seats", "expected_cap"),
    [(5, 5, 5), (7, 5, 7), (1, 5, 5)],
)
async def test_founder_workspace_cap_uses_max_of_persisted_and_included_seats(
    monkeypatch, max_seats, included_seats, expected_cap
):
    connection = FakeOrgConnection(
        member_count=expected_cap,
        max_seats=max_seats,
        included_seats=included_seats,
        plan_tier="founder_workspace",
    )
    allow_org_write(monkeypatch)
    owner_session(monkeypatch)
    monkeypatch.setattr(org_api, "get_db_connection", AsyncMock(return_value=connection))
    lookup = AsyncMock()
    monkeypatch.setattr(org_api, "get_user_by_email", lookup)

    response = await org_api.add_organization_member(
        ORG_ID,
        org_api.OrganizationMemberAdd(email=NEW_EMAIL),
        object(),
    )

    body = json.loads(response.body)
    assert response.status_code == 402
    assert body["seats_used"] == expected_cap
    assert body["max_seats"] == expected_cap
    assert body["add_seat_url"] == "/api/v1/billing/seats"
    lookup.assert_not_awaited()


@pytest.mark.asyncio
async def test_seat_endpoint_updates_existing_extra_item(monkeypatch, stripe_api_module):
    stripe_api = stripe_api_module
    class SeatConnection:
        closed = False

        async def fetchrow(self, query, *params):
            assert "extra_seat_stripe_price" in query
            return {"extra_seat_stripe_price": "price_extra_fixture"}

        async def close(self):
            self.closed = True

    connection = SeatConnection()
    monkeypatch.setattr(stripe_api.asyncpg, "connect", AsyncMock(return_value=connection))
    monkeypatch.setattr(
        stripe_api.stripe_integration,
        "get_customer_for_org",
        AsyncMock(return_value={"id": "cus_fixture"}),
        raising=False,
    )
    subscription = {
        "id": "sub_fixture",
        "customer": "cus_fixture",
        "status": "active",
        "metadata": {"suite": "unicorn-commander", "org_id": ORG_ID},
        "items": {
            "data": [
                {"id": "si_base", "price": {"id": "price_team_fixture"}},
                {"id": "si_extra", "price": {"id": "price_extra_fixture"}, "quantity": 2},
            ]
        },
    }
    list_subscriptions = Mock(return_value={"data": [subscription], "has_more": False})
    modify = Mock(return_value=subscription)
    monkeypatch.setattr(stripe_api.stripe.Subscription, "list", list_subscriptions)
    monkeypatch.setattr(stripe_api.stripe.Subscription, "modify", modify)

    result = await stripe_api.update_extra_seat_quantity(
        stripe_api.SeatQuantityRequest(quantity=3), org_id=ORG_ID
    )

    assert result["quantity"] == 3
    modify.assert_called_once_with("sub_fixture", items=[{"quantity": 3, "id": "si_extra"}])
    assert connection.closed is True


@pytest.mark.asyncio
async def test_subscription_update_sets_included_plus_extra_seats(monkeypatch, webhooks_module):
    webhooks = webhooks_module
    latest = {
        "id": "sub_seat_fixture",
        "customer": "cus_seat_fixture",
        "status": "active",
        "metadata": {"suite": "unicorn-commander", "org_id": ORG_ID},
        "items": {
            "data": [
                {"price": {"id": "price_team_fixture"}},
                {"price": {"id": "price_extra_fixture"}, "quantity": 2},
            ],
            "has_more": False,
        },
    }
    event = dict(latest)
    customer = {"id": "cus_seat_fixture", "metadata": {"org_id": ORG_ID}}
    monkeypatch.setattr(webhooks.stripe.Customer, "retrieve", Mock(return_value=customer))
    monkeypatch.setattr(webhooks.stripe.Subscription, "retrieve", Mock(return_value=latest))

    class WebhookConnection:
        def __init__(self):
            self.updates = []

        async def fetchrow(self, query, *params):
            if "extra_seat_stripe_price" in query:
                return {"extra_seat_stripe_price": "price_extra_fixture"}
            assert params == ("price_team_fixture",)
            return {"tier_code": "founder_workspace", "team_seats": 5}

        async def execute(self, query, *params):
            self.updates.append((query, params))
            return "UPDATE 1"

    connection = WebhookConnection()
    class DatabaseContext:
        async def __aenter__(self):
            return connection

        async def __aexit__(self, exc_type, exc_value, traceback):
            return None

    database = sys.modules["database"]
    context = DatabaseContext()
    monkeypatch.setattr(database, "get_db_connection", AsyncMock(return_value=context))
    provision = AsyncMock(
        return_value={"tier_set": True, "lago_sub": True, "key_capped": True, "cloud_cap": None}
    )
    paid = sys.modules["paid_org_provisioning"]
    monkeypatch.setattr(paid, "provision_paid_org", provision)

    first = await webhooks._sync_subscription_with_extra_seats(event)
    second = await webhooks._sync_subscription_with_extra_seats(event)

    assert first["result"]["max_seats"] == 7
    assert second["result"]["max_seats"] == 7
    assert len(connection.updates) == 2
    assert all(update[1] == (7, ORG_ID) for update in connection.updates)
    assert provision.await_count == 2
