"""Unit coverage for the dashboard cursor and pending organization invites."""

from datetime import datetime, timedelta, timezone
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

import org_api


ORG_ID = "00000000-0000-4000-8000-000000000101"
OWNER_ID = "kc-owner-fictional"
INVITED_ID = "kc-invited-fictional"


class FakeTransaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False


class FakeConnection:
    def __init__(self, *, member_count=1, pending_count=0, existing_role=None, pending=False):
        self.org = {
            "id": ORG_ID,
            "name": "Fictional Lantern Labs",
            "plan_tier": "founder_workspace",
            "max_seats": 5,
            "seat_cap": 5,
            "included_seats": 5,
        }
        self.member_count = member_count
        self.pending_count = pending_count
        self.existing_role = existing_role
        self.pending = pending
        self.pending_invitations = []
        self.invitation_inserted = None
        self.invitation_accepted = []
        self.member_inserted = None
        self.cursor_inserted = None
        self.cursor_value = None
        self.fetch_params = []
        self.closed = False

    async def fetchrow(self, query, *params):
        if "FROM organizations" in query:
            return self.org
        if "FROM organization_invitations" in query and "SELECT id" in query:
            return {"id": "invite-existing"} if self.pending else None
        if "SELECT role" in query:
            return {"role": self.existing_role} if self.existing_role else None
        if "INSERT INTO organization_invitations" in query:
            self.invitation_inserted = params
            return {
                "id": "invite-fictional",
                "expires_at": datetime(2026, 11, 15, tzinfo=timezone.utc),
            }
        if "SELECT 1" in query and "organization_members" in query:
            return None
        if "details->>'last_seen_at'" in query:
            if self.cursor_value:
                return {"last_seen_at": self.cursor_value}
            return None
        raise AssertionError(f"unexpected fetchrow query: {query}")

    async def fetch(self, query, *params):
        self.fetch_params.append(params)
        if "SELECT id, org_id::text AS org_id, role" in query:
            assert "LOWER(email)" in query
            return self.pending_invitations
        if "SELECT 1" in query and "organization_members" in query:
            return []
        raise AssertionError(f"unexpected fetch query: {query}")

    def transaction(self):
        return FakeTransaction()

    async def fetchval(self, query, *params):
        if "organization_invitations" in query:
            return self.pending_count
        if "organization_members" in query:
            return self.member_count
        raise AssertionError(f"unexpected fetchval query: {query}")

    async def execute(self, query, *params):
        if "INSERT INTO organization_members" in query:
            self.member_inserted = params
            return "INSERT 0 1"
        if "INSERT INTO organization_audit_log" in query:
            self.cursor_inserted = params
            return "INSERT 0 1"
        if "UPDATE organization_invitations" in query:
            self.invitation_accepted.append(params[0])
            return "UPDATE 1"
        raise AssertionError(f"unexpected execute query: {query}")

    async def close(self):
        self.closed = True


class FakeRequest:
    state = SimpleNamespace()
    cookies = {}


@pytest.fixture
def owner_actor(monkeypatch):
    actor = {"id": OWNER_ID, "email": "owner@example.com", "role": "user"}
    monkeypatch.setattr(org_api, "get_current_user", AsyncMock(return_value=actor))
    monkeypatch.setattr(org_api, "verify_org_access", AsyncMock(return_value=actor))
    return actor


@pytest.mark.asyncio
async def test_owner_invite_creates_pending_record_without_membership(monkeypatch, owner_actor):
    connection = FakeConnection()
    monkeypatch.setattr(org_api, "get_db_connection", AsyncMock(return_value=connection))
    monkeypatch.setattr(org_api, "get_user_by_email", AsyncMock(return_value=None))
    create_user = AsyncMock()
    monkeypatch.setattr(org_api, "keycloak_create_user", create_user)

    result = await org_api.add_organization_member(
        ORG_ID,
        org_api.OrganizationMemberAdd(email="mira@example.com", role="member"),
        FakeRequest(),
    )

    assert result["pending"] is True
    assert result["membership_added"] is False
    assert result["email"] == "mira@example.com"
    assert connection.member_inserted is None
    assert connection.invitation_inserted == (
        ORG_ID,
        "mira@example.com",
        "member",
        OWNER_ID,
    )
    create_user.assert_not_awaited()


@pytest.mark.asyncio
async def test_pending_invitation_is_accepted_on_first_sign_in():
    connection = FakeConnection()
    connection.pending_invitations = [{
        "id": "invite-fictional",
        "org_id": ORG_ID,
        "role": "member",
    }]

    accepted = await org_api._accept_pending_invitations(
        connection,
        {"id": INVITED_ID, "email": "mira@example.com"},
    )

    assert accepted == 1
    assert connection.member_inserted == (ORG_ID, INVITED_ID, "member")
    assert connection.invitation_accepted == ["invite-fictional"]
    assert connection.fetch_params[0][0] == "mira@example.com"


@pytest.mark.asyncio
async def test_pending_invites_reserve_seats(monkeypatch, owner_actor):
    connection = FakeConnection(member_count=4, pending_count=1)
    monkeypatch.setattr(org_api, "get_db_connection", AsyncMock(return_value=connection))
    lookup = AsyncMock()
    monkeypatch.setattr(org_api, "get_user_by_email", lookup)

    response = await org_api.add_organization_member(
        ORG_ID,
        org_api.OrganizationMemberAdd(email="new@example.com"),
        FakeRequest(),
    )

    assert response.status_code == 402
    assert json.loads(response.body)["seats_used"] == 5
    lookup.assert_not_awaited()
    assert connection.invitation_inserted is None


@pytest.mark.asyncio
async def test_existing_member_is_reported_as_duplicate(monkeypatch, owner_actor):
    connection = FakeConnection(existing_role="member")
    monkeypatch.setattr(org_api, "get_db_connection", AsyncMock(return_value=connection))
    monkeypatch.setattr(
        org_api,
        "get_user_by_email",
        AsyncMock(return_value={"id": INVITED_ID, "email": "mira@example.com"}),
    )

    with pytest.raises(HTTPException) as exc_info:
        await org_api.add_organization_member(
            ORG_ID,
            org_api.OrganizationMemberAdd(email="mira@example.com"),
            FakeRequest(),
        )

    assert exc_info.value.status_code == 400
    assert "already a member" in exc_info.value.detail


@pytest.mark.asyncio
async def test_platform_admin_keeps_immediate_membership(monkeypatch):
    actor = {"id": "platform-admin-fictional", "email": "admin@example.com", "role": "admin"}
    connection = FakeConnection()
    monkeypatch.setattr(org_api, "get_current_user", AsyncMock(return_value=actor))
    monkeypatch.setattr(org_api, "get_db_connection", AsyncMock(return_value=connection))
    monkeypatch.setattr(
        org_api,
        "get_user_by_email",
        AsyncMock(return_value={"id": INVITED_ID, "email": "mira@example.com"}),
    )

    result = await org_api.add_organization_member(
        ORG_ID,
        org_api.OrganizationMemberAdd(email="mira@example.com"),
        FakeRequest(),
    )

    assert result["pending"] is False
    assert result["membership_added"] is True
    assert connection.member_inserted == (ORG_ID, INVITED_ID, "member")
    assert connection.invitation_inserted is None


@pytest.mark.asyncio
async def test_dashboard_cursor_is_user_and_org_scoped(monkeypatch):
    actor = {"id": OWNER_ID, "email": "owner@example.com", "role": "user"}
    connection = FakeConnection()
    monkeypatch.setattr(org_api, "verify_org_access", AsyncMock(return_value=actor))
    monkeypatch.setattr(org_api, "get_db_connection", AsyncMock(return_value=connection))

    seen = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(minutes=1)
    result = await org_api.update_dashboard_cursor(
        ORG_ID,
        org_api.DashboardCursorUpdate(last_seen_at=seen, rendered=True),
        FakeRequest(),
    )

    assert result["advanced"] is True
    assert connection.cursor_inserted == (
        ORG_ID,
        OWNER_ID,
        org_api.DASHBOARD_CURSOR_ACTION,
        seen.isoformat(),
    )


@pytest.mark.asyncio
async def test_accept_leaves_invite_pending_when_seats_are_full(caplog):
    connection = FakeConnection(member_count=1)
    connection.org = {
        **connection.org,
        "plan_tier": "byok",
        "max_seats": 1,
        "included_seats": 1,
    }
    connection.pending_invitations = [{
        "id": "invite-full",
        "org_id": ORG_ID,
        "role": "member",
    }]

    accepted = await org_api._accept_pending_invitations(
        connection,
        {"id": INVITED_ID, "email": "mira@example.com"},
    )

    assert accepted == 0
    assert connection.member_inserted is None
    assert connection.invitation_accepted == []
    assert "mira@example.com" not in caplog.text


@pytest.mark.asyncio
async def test_power_user_flag_does_not_create_a_membership(monkeypatch, owner_actor):
    actor = {
        "id": "power-user-fictional",
        "email": "power@example.com",
        "role": "power_user",
        "is_admin": True,
        "platform_admin": True,
    }
    connection = FakeConnection()
    monkeypatch.setattr(org_api, "get_current_user", AsyncMock(return_value=actor))
    monkeypatch.setattr(org_api, "get_db_connection", AsyncMock(return_value=connection))
    monkeypatch.setattr(org_api, "get_user_by_email", AsyncMock(return_value=None))
    create_user = AsyncMock()
    monkeypatch.setattr(org_api, "keycloak_create_user", create_user)

    result = await org_api.add_organization_member(
        ORG_ID,
        org_api.OrganizationMemberAdd(email="mira@example.com"),
        FakeRequest(),
    )

    assert result["pending"] is True
    assert result["membership_added"] is False
    assert connection.member_inserted is None
    create_user.assert_not_awaited()


@pytest.mark.asyncio
async def test_cursor_get_does_not_write(monkeypatch):
    actor = {"id": OWNER_ID, "email": "owner@example.com", "role": "user"}
    connection = FakeConnection()
    monkeypatch.setattr(org_api, "verify_org_access", AsyncMock(return_value=actor))
    monkeypatch.setattr(org_api, "get_db_connection", AsyncMock(return_value=connection))

    result = await org_api.get_dashboard_cursor(ORG_ID, FakeRequest())

    assert result["org_id"] == ORG_ID
    assert result["last_seen_at"] is None
    assert result["server_now"]
    assert connection.cursor_inserted is None


@pytest.mark.asyncio
async def test_cursor_without_rendered_flag_does_not_write(monkeypatch):
    actor = {"id": OWNER_ID, "email": "owner@example.com", "role": "user"}
    database = AsyncMock()
    monkeypatch.setattr(org_api, "verify_org_access", AsyncMock(return_value=actor))
    monkeypatch.setattr(org_api, "get_db_connection", database)

    with pytest.raises(HTTPException) as exc_info:
        await org_api.update_dashboard_cursor(
            ORG_ID,
            org_api.DashboardCursorUpdate(last_seen_at="2026-11-01T13:00:00Z"),
            FakeRequest(),
        )

    assert exc_info.value.status_code == 400
    database.assert_not_awaited()


@pytest.mark.asyncio
async def test_cursor_does_not_rewind_or_accept_a_future_time(monkeypatch):
    actor = {"id": OWNER_ID, "email": "owner@example.com", "role": "user"}
    connection = FakeConnection()
    connection.cursor_value = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    monkeypatch.setattr(org_api, "verify_org_access", AsyncMock(return_value=actor))
    monkeypatch.setattr(org_api, "get_db_connection", AsyncMock(return_value=connection))

    older = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(hours=1)
    rewind = await org_api.update_dashboard_cursor(
        ORG_ID,
        org_api.DashboardCursorUpdate(last_seen_at=older, rendered=True),
        FakeRequest(),
    )
    assert rewind["advanced"] is False
    assert connection.cursor_inserted is None

    database = AsyncMock()
    monkeypatch.setattr(org_api, "get_db_connection", database)
    with pytest.raises(HTTPException) as exc_info:
        await org_api.update_dashboard_cursor(
            ORG_ID,
            org_api.DashboardCursorUpdate(last_seen_at="2099-01-01T00:00:00Z", rendered=True),
            FakeRequest(),
        )
    assert exc_info.value.status_code == 400
    database.assert_not_awaited()


@pytest.mark.asyncio
async def test_my_orgs_continues_when_invitation_storage_is_missing(monkeypatch):
    class MissingInvitations(Exception):
        sqlstate = "42P01"

    class ListingConnection:
        def __init__(self):
            self.fetched = False
            self.closed = False

        async def fetch(self, query, *params):
            self.fetched = True
            assert "organization_members" in query
            return []

        async def close(self):
            self.closed = True

    connection = ListingConnection()

    async def missing_table(conn, user):
        raise MissingInvitations("relation is missing")

    monkeypatch.setattr(
        org_api,
        "get_current_user",
        AsyncMock(return_value={"id": OWNER_ID, "email": "owner@example.com", "role": "user"}),
    )
    monkeypatch.setattr(org_api, "get_db_connection", AsyncMock(return_value=connection))
    monkeypatch.setattr(org_api, "_accept_pending_invitations", missing_table)

    result = await org_api.get_my_organizations(FakeRequest())

    assert result == []
    assert connection.fetched is True
    assert connection.closed is True
