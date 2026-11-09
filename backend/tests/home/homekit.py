"""Shared helpers for the home-state tests.

Everything here is fictional: Rivergreen Coffee Co., its people, Harbor Market
and every host under example.com. Upstream payloads follow the real response
shapes of each app's origin/main (see the adapter docstrings for path:line).
No test reads live state, a database, Redis or any network service.
"""

from __future__ import annotations

import asyncio
import base64
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

import httpx

BACKEND = Path(__file__).resolve().parents[2]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from home.context import HomeContext, HomeProviders  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"

ORG_ID = "5f2b9c1e-7a3d-4e6f-9b20-1c8d4a6e3f70"
PERSON_SUB = "8d1e2f3a-4b5c-4d6e-8f70-9a0b1c2d3e4f"
NOW = datetime(2026, 11, 9, 15, 0, tzinfo=timezone.utc)  # 10:00 in New York
CURSOR = "2026-11-06T23:12:00+00:00"

API_HOSTS = {
    "HOME_PROJECT_OPS_API_URL": "https://api.projectops.example.com",
    "HOME_MEETING_OPS_API_URL": "https://meetings.example.com",
    "HOME_EMAIL_OPS_API_URL": "https://mail-ops.example.com",
    "HOME_ACCOUNTING_OPS_API_URL": "https://ledger-api.example.com",
    "HOME_CUSTOMER_OPS_API_URL": "https://api.customers.example.com",
    "HOME_CENTER_DEEP_API_URL": "https://research.example.com",
}
WEB_HOSTS = {
    "HOME_PROJECT_OPS_WEB_URL": "https://projectops.example.com",
    "HOME_MEETING_OPS_WEB_URL": "https://meetings.example.com",
    "HOME_EMAIL_OPS_WEB_URL": "https://mail-ops.example.com",
    "HOME_ACCOUNTING_OPS_WEB_URL": "https://ledger.example.com",
    "HOME_CUSTOMER_OPS_WEB_URL": "https://customers.example.com",
    "HOME_CENTER_DEEP_WEB_URL": "https://research.example.com",
}
HOME_ENV = [
    "HOME_STATE_ENABLED",
    "HOME_ACTIONS_ENABLED",
    "HOME_ACTION_TIMEOUT_SECONDS",
    "HOME_RING",
    "HOME_APP_TIMEOUT_SECONDS",
    "HOME_TOTAL_BUDGET_SECONDS",
    "HOME_DEFAULT_TIMEZONE",
    "HOME_OPS_CENTER_WEB_URL",
    *API_HOSTS,
    *WEB_HOSTS,
]


def load(name: str) -> Any:
    with open(FIXTURES / f"{name}.json", encoding="utf-8") as handle:
        text = handle.read().replace("{{ORG_ID}}", ORG_ID).replace("{{PERSON_SUB}}", PERSON_SUB)
    return json.loads(text)


def fake_jwt(exp: datetime) -> str:
    """A token-shaped string with an exp claim. Not signed, not a credential."""

    def part(data: Dict[str, Any]) -> str:
        raw = base64.urlsafe_b64encode(json.dumps(data).encode()).decode()
        return raw.rstrip("=")

    return ".".join(
        [part({"alg": "none"}), part({"sub": PERSON_SUB, "exp": int(exp.timestamp())}), "unsigned-test"]
    )


# Far past the wall clock: the real request binding (test_home_route,
# test_home_actions) decides with the real clock whether the token is fresh.
VALID_TOKEN = fake_jwt(datetime(2036, 11, 9, 16, 0, tzinfo=timezone.utc))
EXPIRED_TOKEN = fake_jwt(datetime(2026, 11, 9, 14, 0, tzinfo=timezone.utc))


def make_ctx(
    *,
    role: Optional[str] = "owner",
    ring: str = "customer",
    token: Optional[str] = VALID_TOKEN,
    now: datetime = NOW,
    ops_center_web: str = "https://home.example.com",
) -> HomeContext:
    return HomeContext(
        person_id=PERSON_SUB,
        display_name="Mara Okonkwo",
        org_id=ORG_ID,
        org_name="Rivergreen Coffee Co.",
        org_role=role,
        ring=ring,
        tz=ZoneInfo("America/New_York"),
        tz_name="America/New_York",
        now=now,
        ops_center_web=ops_center_web,
        email="mara@rivergreen.example",
        access_token=token,
    )


Handler = Callable[[httpx.Request], Any]


class FakeSuite:
    """Routes upstream calls by path to fixture responses.

    ``routes`` maps a path (no query) to a JSON body, an ``(status, body)``
    pair, or a callable taking the request. Every request is recorded, and
    the Bearer header is checked so a missing token fails the test.
    """

    def __init__(self, routes: Optional[Dict[str, Any]] = None):
        self.routes: Dict[str, Any] = dict(routes or {})
        self.calls: List[httpx.Request] = []

    async def handle(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        assert request.headers.get("authorization", "").startswith("Bearer "), "no Bearer token"
        assert "cookie" not in request.headers, "cookies must never be forwarded"
        route = self.routes.get(request.url.path)
        if route is None:
            return httpx.Response(404, json={"detail": "not found"})
        if callable(route):
            route = route(request)
            if asyncio.iscoroutine(route):
                route = await route
        if isinstance(route, httpx.Response):
            return route
        if isinstance(route, tuple):
            status, body = route
            return httpx.Response(status, json=body)
        return httpx.Response(200, json=route)

    def factory(self, timeout: float) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=httpx.MockTransport(self.handle), timeout=timeout, follow_redirects=False
        )

    def paths(self) -> List[str]:
        return [request.url.path for request in self.calls]

    def hosts(self) -> List[str]:
        return [request.url.host for request in self.calls]


def suite_routes() -> Dict[str, Any]:
    """A fully set-up org: every app answers with fixture data."""

    ws = ORG_ID
    return {
        # Project-Ops
        "/api/v1/auth/profile": load("po_profile"),
        "/api/v1/tasks/my-tasks": load("po_my_tasks"),
        "/api/v1/triage/proposals": load("po_triage"),
        # Meeting-Ops
        "/api/auth/orgs": load("mo_orgs"),
        "/api/analytics/sessions": load("mo_sessions"),
        "/api/action-items": load("mo_action_items"),
        # Email-Ops and Customer-Ops share the my-workspaces path on different hosts
        "/api/v1/auth/me/workspaces": lambda request: (
            load("co_workspaces") if "customers" in request.url.host else load("eo_workspaces")
        ),
        f"/api/v1/workspaces/{ws}/agent-inbox": load("eo_agent_inbox"),
        f"/api/v1/workspaces/{ws}/customers": load("co_customers"),
        # Accounting-Ops
        f"/api/workspaces/{ws}": load("ao_workspace"),
        f"/api/workspaces/{ws}/approvals": load("ao_approvals"),
        f"/api/workspaces/{ws}/cfo-brief": load("ao_cfo_brief"),
        f"/api/workspaces/{ws}/invoices": load("ao_invoices"),
        # Center Deep Research
        "/api/briefs": load("cdr_briefs"),
        "/api/notifications": load("cdr_notifications"),
    }


class Recorder:
    def __init__(self):
        self.calls: List[Tuple[str, Any]] = []


def make_providers(
    suite: FakeSuite,
    *,
    cards: Optional[List[Dict[str, Any]]] = None,
    cursor: Optional[str] = CURSOR,
    rows: Optional[Dict[str, str]] = None,
    usage: Optional[Dict[int, Dict[str, Any]]] = None,
    pool: Optional[Dict[str, Any]] = None,
    recorder: Optional[Recorder] = None,
    apps_error: Optional[BaseException] = None,
) -> HomeProviders:
    recorder = recorder or Recorder()
    card_list = load("oc_apps") if cards is None else cards
    mapping = {"meeting-ops": "rivergreen-coffee"} if rows is None else rows
    usage_by_days = usage or {
        30: {"org_id": ORG_ID, "total_credits_used": 312, "user_count": 3,
             "service_breakdown": {"llm": 290, "embeddings": 22}, "top_users": []},
        1: {"org_id": ORG_ID, "total_credits_used": 14, "user_count": 2,
            "service_breakdown": {"llm": 14}, "top_users": []},
    }
    pool_value = pool if pool is not None else {
        "total_credits": 1000, "allocated_credits": 0, "used_credits": 312, "available_credits": 688,
    }

    async def apps():
        recorder.calls.append(("apps", None))
        if apps_error is not None:
            raise apps_error
        return card_list

    async def cursor_fn():
        recorder.calls.append(("cursor", None))
        return cursor

    async def usage_fn(days: int):
        recorder.calls.append(("usage", days))
        return usage_by_days[days]

    async def pool_fn():
        recorder.calls.append(("pool", None))
        return pool_value

    async def rows_fn():
        recorder.calls.append(("rows", None))
        return mapping

    return HomeProviders(
        apps=apps, cursor=cursor_fn, usage=usage_fn, pool=pool_fn, workspace_rows=rows_fn,
        client_factory=suite.factory,
    )


def module_by_id(document: Dict[str, Any], module_id: str) -> Optional[Dict[str, Any]]:
    return next((m for m in document["modules"] if m["id"] == module_id), None)


def source_for(module: Dict[str, Any], app: str, route_fragment: str = "") -> Dict[str, Any]:
    for source in module["source"]:
        if source["app"] == app and route_fragment in (source.get("route") or ""):
            return source
    raise AssertionError(f"no {app} source with {route_fragment!r} in {module['id']}")
