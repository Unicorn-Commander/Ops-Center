"""Unit coverage for entitlement-backed app cards.

These tests use an in-memory asyncpg-shaped connection. They never call a live
database or app endpoint.
"""

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest


BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

if importlib.util.find_spec("asyncpg") is None:
    asyncpg_stub = ModuleType("asyncpg")
    asyncpg_stub.PostgresError = Exception
    asyncpg_stub.connect = None
    sys.modules["asyncpg"] = asyncpg_stub

import my_apps_api  # noqa: E402


def _metadata(*, companion=True, readiness="none", extra=None):
    dashboard = {
        "purpose": "A focused workspace for a fictional team.",
        "primary_action": {"label": "Open app", "route_id": "home"},
        "readiness": {"check": readiness},
    }
    if companion:
        dashboard["companion"] = {
            "label": "Connect your AI",
            "mcp_url": "https://app.magicunicorn.dev/mcp",
            "chatgpt_url": "https://app.magicunicorn.dev/mcp",
            "desktop": [],
            "mobile": [],
        }
    if extra:
        dashboard.update(extra)
    return {"dashboard": dashboard}


def _row(slug, feature_key, *, launch_url="https://app.magicunicorn.dev", metadata=None, features=None):
    return {
        "id": slug,
        "name": slug.replace("-", " ").title(),
        "slug": slug,
        "description": "A fictional app for unit tests.",
        "icon_url": "/logos/test.png",
        "launch_url": launch_url,
        "category": "productivity",
        "feature_key": feature_key,
        "base_price": 0,
        "metadata": metadata or _metadata(),
        "features": features or {},
    }


class FakeConnection:
    def __init__(self, rows, tier_features=(), org_features=()):
        self.rows = rows
        self.tier_features = set(tier_features)
        self.org_features = set(org_features)
        self.requested_org_ids = []
        self.closed = False

    async def fetchrow(self, query, *params):
        if "subscription_tiers" in query:
            return {"id": 7}
        raise AssertionError(f"Unexpected fetchrow: {query}")

    async def fetch(self, query, *params):
        if "tier_features" in query:
            return [{"feature_key": key} for key in self.tier_features]
        if "org_features" in query:
            self.requested_org_ids.append(params[0])
            return [{"feature_key": key} for key in self.org_features]
        if "FROM add_ons" in query:
            return self.rows
        raise AssertionError(f"Unexpected fetch: {query}")

    async def close(self):
        self.closed = True


def request():
    return SimpleNamespace(cookies={}, state=SimpleNamespace())


async def authorized(monkeypatch, connection, *, org_id="org-current", tier="trial", session=None, org_name=None):
    async def db_connection():
        return connection

    monkeypatch.setattr(my_apps_api, "get_db_connection", db_connection)
    async def current_org(_request):
        if org_name:
            _request.state.current_org_name = org_name
        return org_id

    monkeypatch.setattr(my_apps_api, "get_user_org_from_session", current_org)
    monkeypatch.setattr(my_apps_api, "_session_data_from_request", lambda _request: session or {})
    return await my_apps_api.get_my_apps(request(), user_tier=tier)


@pytest.mark.asyncio
async def test_tier_only_entitlement_returns_only_tier_app(monkeypatch):
    connection = FakeConnection(
        [_row("tier-app", "tier_access"), _row("org-app", "org_access")],
        tier_features={"tier_access"},
    )

    apps = await authorized(monkeypatch, connection)

    assert [app["slug"] for app in apps] == ["tier-app"]
    assert apps[0]["access_type"] == "tier_included"


@pytest.mark.asyncio
async def test_org_grant_uses_the_current_org(monkeypatch):
    connection = FakeConnection(
        [_row("org-app", "org_access")],
        org_features={"org_access"},
    )

    apps = await authorized(monkeypatch, connection, org_id="org-current")

    assert [app["slug"] for app in apps] == ["org-app"]
    assert connection.requested_org_ids == ["org-current"]
    assert apps[0]["access_type"] == "org_granted"


@pytest.mark.asyncio
async def test_admin_sees_active_launchable_apps_but_not_internal_ring(monkeypatch):
    public = _row("public-app", "public_access")
    internal = _row("legal-ops", "legal_ops_access", metadata=_metadata(extra={"internal_ring": True}))
    connection = FakeConnection([public, internal])

    apps = await authorized(
        monkeypatch,
        connection,
        session={"user": {"role": "admin"}},
    )

    assert [app["slug"] for app in apps] == ["public-app"]


@pytest.mark.asyncio
async def test_internal_ring_receives_legal_ops_org_grant(monkeypatch):
    connection = FakeConnection(
        [_row("legal-ops", "legal_ops_access", metadata=_metadata(extra={"internal_ring": True}))],
        org_features={"legal_ops_access"},
    )

    apps = await authorized(
        monkeypatch,
        connection,
        org_name="ops-center-dogfood",
    )

    assert [app["slug"] for app in apps] == ["legal-ops"]
    assert apps[0]["access_type"] == "org_granted"


@pytest.mark.asyncio
async def test_customer_ring_does_not_receive_internal_legal_ops(monkeypatch):
    connection = FakeConnection(
        [_row("legal-ops", "legal_ops_access", metadata=_metadata(extra={"internal_ring": True}))],
        org_features={"legal_ops_access"},
    )

    apps = await authorized(monkeypatch, connection, org_name="customer-org")

    assert apps == []


@pytest.mark.asyncio
async def test_missing_launch_url_is_not_a_card(monkeypatch):
    connection = FakeConnection(
        [_row("missing-launch", "tier_access", launch_url=None)],
        tier_features={"tier_access"},
    )

    assert await authorized(monkeypatch, connection) == []


@pytest.mark.asyncio
async def test_cross_org_grant_cannot_be_read_from_another_org(monkeypatch):
    connection = FakeConnection([_row("internal-app", "internal_access")], org_features=set())
    seen_orgs = []

    async def current_org(_request):
        seen_orgs.append("org-b")
        return "org-b"

    async def db_connection():
        return connection

    monkeypatch.setattr(my_apps_api, "get_db_connection", db_connection)
    monkeypatch.setattr(my_apps_api, "get_user_org_from_session", current_org)
    monkeypatch.setattr(my_apps_api, "_session_data_from_request", lambda _request: {})

    assert await my_apps_api.get_my_apps(request(), user_tier="trial") == []
    assert seen_orgs == ["org-b"]
    assert connection.requested_org_ids == ["org-b"]


def test_metadata_schema_rejects_placeholder_host_and_preserves_first_open_state():
    valid = _metadata()
    valid["dashboard"]["companion"]["mcp_url"] = "https://app.magicunicorn.dev/api/v1/mcp"
    valid["dashboard"]["companion"]["chatgpt_url"] = "https://app.magicunicorn.dev/api/v1/mcp"
    parsed = my_apps_api.validate_dashboard_metadata(valid)
    assert my_apps_api.app_state_from_metadata(parsed.dashboard) == "ready"

    first_open = my_apps_api.validate_dashboard_metadata(
        _metadata(
            readiness="first_open",
            companion=False,
        )
    )
    assert my_apps_api.app_state_from_metadata(first_open.dashboard) == "needs_first_open"

    invalid = _metadata()
    invalid["dashboard"]["companion"]["mcp_url"] = "https://example.com/mcp"
    with pytest.raises(ValueError, match="placeholder"):
        my_apps_api.validate_dashboard_metadata(invalid)


@pytest.mark.asyncio
async def test_response_contains_only_safe_typed_metadata(monkeypatch):
    connection = FakeConnection(
        [
            _row(
                "safe-app",
                "tier_access",
                features={"api_key": "fixture-secret", "password": "fixture-secret"},
                metadata={
                    **_metadata(),
                    "api_key": "fixture-secret",
                    "dashboard": {
                        **_metadata()["dashboard"],
                        "secret": "fixture-secret",
                        "companion": None,
                    },
                },
            )
        ],
        tier_features={"tier_access"},
    )

    apps = await authorized(monkeypatch, connection)
    response_text = json.dumps(apps)

    assert "api_key" not in response_text
    assert "password" not in response_text
    assert "fixture-secret" not in response_text
    assert "secret" not in response_text
    assert apps[0]["companion"] is None
