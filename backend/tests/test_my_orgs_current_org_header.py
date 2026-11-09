"""GET /api/v1/org/my-orgs names the organization the backend serves.

The page keeps its selected organization in localStorage while the backend
serves the org in the ``current_org_id`` cookie, else the session org. When the
two disagree, the header and switcher name one organization while My Apps loads
another's apps. The list endpoint therefore carries ``X-Current-Org-Id``, worked
out by the same function GET /api/v1/my-apps/authorized uses, and keeps its
body a plain list.

The requests run through FastAPI with in-memory connections. They never reach
a live database, Redis or app endpoint, and every organization is fictional.
"""

import importlib.machinery
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType
from unittest.mock import AsyncMock

import pytest

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


def _ensure_asyncpg():
    """Use the real driver when installed, else the same stub the other unit tests use."""

    module = sys.modules.get("asyncpg")
    if module is None:
        try:
            import asyncpg as module  # noqa: F401
        except ImportError:
            module = ModuleType("asyncpg")
            # A spec keeps importlib.util.find_spec("asyncpg") working for the
            # test modules that check for the driver after this one.
            module.__spec__ = importlib.machinery.ModuleSpec("asyncpg", None)
            sys.modules["asyncpg"] = module
    for name, value in {"PostgresError": Exception, "Record": dict, "connect": None}.items():
        if not hasattr(module, name):
            setattr(module, name, value)


_ensure_asyncpg()

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import my_apps_api  # noqa: E402
import org_api  # noqa: E402


SUBJECT = "kc-fictional-member"
ALDER = "00000000-0000-4000-8000-0000000000a1"  # first by name
BIRCH = "00000000-0000-4000-8000-0000000000b2"
CEDAR = "00000000-0000-4000-8000-0000000000c3"  # someone else's organization

ORGS = {
    ALDER: "Alder Fictional Remodeling",
    BIRCH: "Birch Fictional Studio",
    CEDAR: "Cedar Fictional Works",
}


class ListingConnection:
    """The my-orgs list query: the member's organizations, by name."""

    def __init__(self, memberships):
        self.memberships = list(memberships)

    async def fetch(self, query, *params):
        assert "organization_members" in query
        assert params == (SUBJECT,)
        return [
            {
                "id": org_id,
                "name": ORGS[org_id],
                "role": "member",
                "plan_tier": "founder_workspace",
                "status": "active",
                "joined_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
                "member_count": 2,
            }
            for org_id in sorted(self.memberships, key=ORGS.get)
        ]

    async def close(self):
        return None


class MembershipConnection:
    """The two queries in my_apps_api.get_user_org_from_session."""

    def __init__(self, memberships, default=None):
        self.memberships = set(memberships)
        self.default = default

    async def fetchrow(self, query, *params):
        assert params[0] == SUBJECT
        if "om.org_id::text = $2" in query:
            org_id = params[1]
        else:
            assert "ORDER BY om.is_default DESC" in query
            org_id = self.default
        if org_id not in self.memberships:
            return None
        return {"org_id": org_id, "plan_tier": "founder_workspace", "org_name": ORGS[org_id]}

    async def close(self):
        return None


@pytest.fixture
def my_orgs(monkeypatch):
    """Serve GET /api/v1/org/my-orgs for one fictional member.

    ``memberships`` are the member's organizations, ``default`` the membership
    flagged is_default, and ``session`` the session record (None: no session).
    """

    def serve(*, memberships=(ALDER, BIRCH), default=BIRCH, session=None):
        monkeypatch.delenv("ORG_INVITES_PENDING", raising=False)
        monkeypatch.setattr(
            org_api,
            "get_current_user",
            AsyncMock(return_value={"id": SUBJECT, "email": "member@example.test"}),
        )
        monkeypatch.setattr(
            org_api, "get_db_connection", AsyncMock(side_effect=lambda: ListingConnection(memberships))
        )
        monkeypatch.setattr(
            my_apps_api,
            "get_db_connection",
            AsyncMock(side_effect=lambda: MembershipConnection(memberships, default)),
        )
        monkeypatch.setattr(my_apps_api, "_session_data_from_request", lambda _request: session)

        app = FastAPI()
        app.include_router(org_api.router)
        return TestClient(app)

    return serve


def _get(client, cookie_org=None):
    cookie = "session_token=fictional-session"
    if cookie_org:
        cookie += f"; current_org_id={cookie_org}"
    return client.get("/api/v1/org/my-orgs", headers={"Cookie": cookie})


def _session(org_id=None):
    session = {"user": {"sub": SUBJECT}}
    if org_id:
        session["org_id"] = org_id
    return session


def test_valid_cookie_org_is_named_and_the_body_stays_a_list(my_orgs):
    client = my_orgs(session=_session(BIRCH))

    response = _get(client, cookie_org=ALDER)

    assert response.status_code == 200
    assert response.headers.get("X-Current-Org-Id") == ALDER
    body = response.json()
    assert isinstance(body, list)
    assert [org["id"] for org in body] == [ALDER, BIRCH]
    assert set(body[0]) == {"id", "name", "role", "plan_tier", "status", "member_count", "joined_at"}


def test_cookie_org_that_is_not_a_membership_sends_no_header(my_orgs):
    # Same rule as my-apps: an explicit cookie never falls back to the session org.
    client = my_orgs(session=_session(BIRCH))

    response = _get(client, cookie_org=CEDAR)

    assert response.status_code == 200
    assert "X-Current-Org-Id" not in response.headers
    assert [org["id"] for org in response.json()] == [ALDER, BIRCH]


def test_without_a_cookie_the_session_org_is_named(my_orgs):
    # The session names Birch. Alder is first by name and is the membership
    # flagged default, so neither shortcut can stand in for the session org.
    client = my_orgs(session=_session(BIRCH), default=ALDER)

    response = _get(client)

    assert response.status_code == 200
    assert response.headers.get("X-Current-Org-Id") == BIRCH


def test_no_organization_sends_no_header(my_orgs):
    client = my_orgs(memberships=(), default=None, session=_session())

    response = _get(client)

    assert response.status_code == 200
    assert response.json() == []
    assert "X-Current-Org-Id" not in response.headers


@pytest.mark.asyncio
async def test_direct_callers_still_get_the_plain_list(my_orgs):
    # The Postgres regression script and older unit tests call the function
    # with the request only.
    my_orgs(session=_session(BIRCH))

    class Request:
        cookies = {"current_org_id": ALDER}

    result = await org_api.get_my_organizations(Request())

    assert [org["id"] for org in result] == [ALDER, BIRCH]
