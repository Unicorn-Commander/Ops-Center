"""GET /api/v1/home/state through FastAPI: the flag, negotiation, auth glue.

The router is mounted on a bare FastAPI app (server.py is never imported).
The request-to-context binding is exercised with fake ``my_apps_api``,
``org_api`` and ``org_billing_api`` modules placed in ``sys.modules``, so no
database, Redis or Keycloak is touched.
"""

from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace

import pytest
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

import home_api
from home.context import HomeContext
from homekit import (
    ORG_ID,
    PERSON_SUB,
    VALID_TOKEN,
    FakeSuite,
    make_ctx,
    make_providers,
    module_by_id,
    suite_routes,
)


def app_with(ctx=None, providers=None, *, override=True):
    app = FastAPI()
    app.include_router(home_api.router)
    if override:
        app.dependency_overrides[home_api.get_home_context] = lambda: ctx or make_ctx()
        app.dependency_overrides[home_api.get_home_providers] = lambda: providers
    return app


def client_for(routes=None, **ctx_kwargs):
    suite = FakeSuite(routes or suite_routes())
    providers = make_providers(suite)
    return TestClient(app_with(make_ctx(**ctx_kwargs), providers)), suite


def test_flag_off_returns_404_before_any_session_or_app_call(monkeypatch):
    monkeypatch.delenv("HOME_STATE_ENABLED", raising=False)
    # No dependency overrides: if the flag check did not run first, the real
    # context builder would try to read a session and fail differently.
    client = TestClient(app_with(override=False))
    response = client.get("/api/v1/home/state")
    assert response.status_code == 404
    assert response.json() == {"detail": "Not Found"}

    monkeypatch.setenv("HOME_STATE_ENABLED", "false")
    client, suite = client_for()
    assert client.get("/api/v1/home/state").status_code == 404
    assert suite.calls == []


def test_flag_on_returns_the_document(monkeypatch):
    monkeypatch.setenv("HOME_STATE_ENABLED", "true")
    client, suite = client_for()
    response = client.get("/api/v1/home/state")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert body["schema"] == "uc.home.state/1"
    for module in body["modules"]:
        assert {"status", "as_of", "source"} <= set(module)
    assert suite.calls


def test_upstream_401_is_a_200_with_reauth_modules_never_a_500(monkeypatch):
    monkeypatch.setenv("HOME_STATE_ENABLED", "1")
    routes = {path: (401, {"detail": "invalid token"}) for path in suite_routes()}
    client, _ = client_for(routes)
    response = client.get("/api/v1/home/state")
    assert response.status_code == 200
    body = response.json()
    for module_id in ("needs_you", "today", "recent_meetings", "watched_topics", "money"):
        module = module_by_id(body, module_id)
        assert module["status"] == "unavailable" and module["reason"] == "reauth", module_id


def test_markdown_negotiation_returns_the_same_items(monkeypatch):
    monkeypatch.setenv("HOME_STATE_ENABLED", "true")
    client, _ = client_for()
    as_json = client.get("/api/v1/home/state", headers={"Accept": "application/json"}).json()
    response = client.get("/api/v1/home/state", headers={"Accept": "text/markdown"})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/markdown")
    markdown = response.text
    assert markdown.startswith("# Home for Mara Okonkwo, Rivergreen Coffee Co.")
    assert as_json["status_line"]["text"] in markdown

    # Same modules, in the same order.
    positions = [markdown.index(f"## {module['title']}") for module in as_json["modules"]]
    assert positions == sorted(positions)

    # Every item appears with its identifier, and each line carries a link.
    for module in as_json["modules"]:
        for item in module.get("items") or []:
            ident = item.get("id") or item.get("monitor_id")
            if ident:
                line = next(l for l in markdown.splitlines() if f"`{ident}`" in l)
                assert "](https://" in line, line
            else:  # app tiles
                assert item["name"] in markdown
    assert "(third party)" in markdown
    assert "—" not in markdown  # no em dashes
    assert "!" not in markdown.replace("](", "")


def test_markdown_is_only_served_when_asked_for(monkeypatch):
    monkeypatch.setenv("HOME_STATE_ENABLED", "true")
    client, _ = client_for()
    for accept in (None, "*/*", "text/html", "application/json, text/markdown;q=0.5",
                   "text/markdown;q=0.4, application/json;q=0.9", "text/markdown;q=0"):
        headers = {"Accept": accept} if accept else {}
        response = client.get("/api/v1/home/state", headers=headers)
        assert response.headers["content-type"].startswith("application/json"), accept
    for accept in ("text/markdown", "text/markdown, */*", "text/markdown;q=0.9, application/json;q=0.5"):
        response = client.get("/api/v1/home/state", headers={"Accept": accept})
        assert response.headers["content-type"].startswith("text/markdown"), accept


def test_wants_markdown_rules():
    assert home_api.wants_markdown("text/markdown") is True
    assert home_api.wants_markdown("text/markdown;q=0.8") is True
    assert home_api.wants_markdown("application/json;q=0.8, text/markdown") is True
    assert home_api.wants_markdown("text/markdown, application/json") is False  # tie keeps JSON
    assert home_api.wants_markdown("") is False
    assert home_api.wants_markdown(None) is False
    assert home_api.wants_markdown("text/markdown;q=abc") is False


# --------------------------------------------------------------------------- #
# The real request-to-context binding, with fake Ops-Center modules
# --------------------------------------------------------------------------- #


class FakeConn:
    def __init__(self, role="owner", rows=None):
        self.role = role
        self.rows = rows if rows is not None else [{"app": "meeting-ops", "workspace_id": "rivergreen-coffee"}]
        self.queries = []
        self.closed = False

    async def fetchrow(self, query, *params):
        self.queries.append((query, params))
        assert "organization_members" in query
        return {"role": self.role} if self.role else None

    async def fetch(self, query, *params):
        self.queries.append((query, params))
        assert "org_app_workspaces" in query
        return self.rows

    async def close(self):
        self.closed = True


def install_fake_ops_center(monkeypatch, *, session, org_id=ORG_ID, org_invalid=False, conn=None,
                            calls=None):
    calls = calls if calls is not None else []
    conn = conn or FakeConn()

    my_apps = ModuleType("my_apps_api")
    my_apps._session_data_from_request = lambda request: session
    my_apps._session_subject = lambda data: (data.get("user") or {}).get("sub")

    async def get_user_org_from_session(request):
        if org_invalid:
            request.state.current_org_invalid = True
            return None
        if org_id:
            request.state.current_org_name = "Rivergreen Coffee Co."
        return org_id

    async def get_db_connection():
        return conn

    async def get_current_user_tier(request):
        calls.append(("tier",))
        return "managed"

    async def get_my_apps(request, user_tier):
        calls.append(("get_my_apps", user_tier))
        return []

    my_apps.get_user_org_from_session = get_user_org_from_session
    my_apps.get_db_connection = get_db_connection
    my_apps.get_current_user_tier = get_current_user_tier
    my_apps.get_my_apps = get_my_apps

    org_api = ModuleType("org_api")

    async def get_dashboard_cursor(org, request):
        calls.append(("cursor", org))
        return {"org_id": org, "last_seen_at": "2026-11-06T23:12:00+00:00", "server_now": "x"}

    org_api.get_dashboard_cursor = get_dashboard_cursor

    billing = ModuleType("org_billing_api")

    async def get_organization_credit_usage(org, days, request):
        calls.append(("usage", org, days))
        return SimpleNamespace(model_dump=lambda mode="json": {
            "org_id": org, "total_credits_used": 5 * days, "user_count": 1,
            "service_breakdown": {"llm": 5 * days}, "top_users": [{"user_id": "someone"}],
        })

    async def get_organization_credit_pool(org, request):
        calls.append(("pool", org))
        raise HTTPException(status_code=404, detail="Credit pool not found")

    billing.get_organization_credit_usage = get_organization_credit_usage
    billing.get_organization_credit_pool = get_organization_credit_pool

    monkeypatch.setitem(sys.modules, "my_apps_api", my_apps)
    monkeypatch.setitem(sys.modules, "org_api", org_api)
    monkeypatch.setitem(sys.modules, "org_billing_api", billing)
    return calls, conn


def session_for(token=VALID_TOKEN):
    return {
        "user": {"sub": PERSON_SUB, "name": "Mara Okonkwo", "email": "mara@rivergreen.example"},
        "access_token": token,
        "org_id": ORG_ID,
        "org_name": "Rivergreen Coffee Co.",
        "org_role": "member",
    }


def real_binding_client(monkeypatch, suite, **fake_kwargs):
    """The real context builder and provider binding; only the HTTP transport
    to the apps is swapped for the fake suite."""

    calls, conn = install_fake_ops_center(monkeypatch, **fake_kwargs)
    app = FastAPI()
    app.include_router(home_api.router)

    async def providers_with_fake_http(
        request: Request, ctx: HomeContext = Depends(home_api.get_home_context)
    ):
        providers = await home_api.get_home_providers(request, ctx)
        providers.client_factory = suite.factory
        return providers

    app.dependency_overrides[home_api.get_home_providers] = providers_with_fake_http
    return TestClient(app), calls, conn


def test_real_context_uses_the_session_token_org_role_ring_and_zone(monkeypatch):
    monkeypatch.setenv("HOME_STATE_ENABLED", "true")
    suite = FakeSuite(suite_routes())
    client, calls, conn = real_binding_client(monkeypatch, suite, session=session_for())
    response = client.get(
        "/api/v1/home/state?tz=America/Chicago",
        headers={"X-Forwarded-Host": "unicorncommander.ai", "Cookie": "session_token=fictional"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["organization"] == {"id": ORG_ID, "name": "Rivergreen Coffee Co.", "ring": "customer"}
    assert body["person"] == {"id": PERSON_SUB, "display_name": "Mara Okonkwo", "role": "owner"}
    assert body["timezone"] == "America/Chicago"
    # The session's own access token went to the apps, and cookies did not.
    assert suite.calls and all(r.headers["authorization"] == f"Bearer {VALID_TOKEN}" for r in suite.calls)
    # In-process sources were called with this org, not over HTTP.
    assert ("cursor", ORG_ID) in calls
    assert ("usage", ORG_ID, 30) in calls and ("usage", ORG_ID, 1) in calls
    assert ("get_my_apps", "managed") in calls
    usage = module_by_id(body, "usage")
    assert usage["credits"]["pool"] is None  # 404 from the pool is "no pool", not an error
    assert "someone" not in response.text  # top_users never leave Ops-Center
    # The Ops-Center links use the browser's own public host.
    since = module_by_id(body, "since_last_visit")
    assert since["source"][0]["url"] == "https://unicorncommander.ai/dashboard"
    # The org role query used the session subject and the selected org.
    role_query = next(params for query, params in conn.queries if "organization_members" in query)
    assert role_query == (PERSON_SUB, ORG_ID)


def test_real_context_member_role_hides_money(monkeypatch):
    monkeypatch.setenv("HOME_STATE_ENABLED", "true")
    suite = FakeSuite(suite_routes())
    client, calls, _ = real_binding_client(
        monkeypatch, suite, session=session_for(), conn=FakeConn(role="member")
    )
    body = client.get("/api/v1/home/state").json()
    assert module_by_id(body, "money") is None and module_by_id(body, "usage") is None
    assert not any(call[0] == "usage" for call in calls)


def test_no_session_is_401(monkeypatch):
    monkeypatch.setenv("HOME_STATE_ENABLED", "true")
    client, _, _ = real_binding_client(monkeypatch, FakeSuite(), session={})
    response = client.get("/api/v1/home/state")
    assert response.status_code == 401


def test_invalid_selected_org_is_403_and_no_org_is_409(monkeypatch):
    monkeypatch.setenv("HOME_STATE_ENABLED", "true")
    client, _, _ = real_binding_client(monkeypatch, FakeSuite(), session=session_for(), org_invalid=True)
    assert client.get("/api/v1/home/state").status_code == 403
    client, _, _ = real_binding_client(monkeypatch, FakeSuite(), session=session_for(), org_id=None)
    assert client.get("/api/v1/home/state").status_code == 409


def test_unknown_zone_falls_back_to_the_default(monkeypatch):
    monkeypatch.setenv("HOME_DEFAULT_TIMEZONE", "Not/AZone")
    zone, name = home_api.resolve_timezone("Also/Bad")
    assert name == "UTC"
    monkeypatch.setenv("HOME_DEFAULT_TIMEZONE", "America/New_York")
    assert home_api.resolve_timezone(None)[1] == "America/New_York"
