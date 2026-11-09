"""The home-state document end to end, with fictional upstream payloads.

Covers the contract (every module has status, as_of and source), a timeout
that leaves every other module intact, money and usage by role, entitlement
gating, and the address rules on both rings.
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import re

import pytest

from home.aggregator import build_home_state
from home.adapters.base import REASONS, STATUSES

from homekit import (
    EXPIRED_TOKEN,
    ORG_ID,
    FakeSuite,
    Recorder,
    load,
    make_ctx,
    make_providers,
    module_by_id,
    source_for,
    suite_routes,
)

EXPECTED_MEMBER_MODULES = [
    "needs_you",
    "today",
    "since_last_visit",
    "apps",
    "recent_meetings",
    "watched_topics",
]
EXPECTED_MANAGER_MODULES = EXPECTED_MEMBER_MODULES + ["money", "usage"]
ISO = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})$")


async def build(ctx=None, suite=None, **provider_kwargs):
    suite = suite or FakeSuite(suite_routes())
    ctx = ctx or make_ctx()
    document = await build_home_state(ctx, make_providers(suite, **provider_kwargs))
    return document, suite


def assert_contract(document):
    assert document["schema"] == "uc.home.state/1"
    assert ISO.match(document["generated_at"])
    assert document["organization"]["id"] == ORG_ID
    assert isinstance(document["status_line"]["text"], str) and document["status_line"]["text"]
    for module in document["modules"]:
        assert module["status"] in STATUSES, module["id"]
        assert ISO.match(module["as_of"]), module["id"]
        if module["status"] == "unavailable":
            assert module["reason"] in REASONS, module["id"]
        else:
            assert "reason" not in module, module["id"]
        assert isinstance(module["source"], list) and module["source"], module["id"]
        for source in module["source"]:
            assert source["app"] and source["label"], module["id"]
            assert source["status"] in STATUSES
            assert ISO.match(source["as_of"])
            assert "url" in source and "route" in source and "workspace" in source
            if source["url"] is not None:
                assert source["url"].startswith("https://"), source
            if source.get("route"):
                assert source["route"].startswith("/") and "://" not in source["route"], source


@pytest.mark.asyncio
async def test_contract_every_module_has_status_as_of_and_source():
    document, _ = await build()
    assert_contract(document)
    assert [m["id"] for m in document["modules"]] == EXPECTED_MANAGER_MODULES
    assert all(m["status"] in ("ok", "empty") for m in document["modules"]), [
        (m["id"], m["status"]) for m in document["modules"]
    ]
    # The document round-trips as JSON (no datetimes or Decimals left in it).
    json.dumps(document)


@pytest.mark.asyncio
async def test_counts_come_straight_from_the_fixtures():
    document, suite = await build()
    needs = module_by_id(document, "needs_you")
    # Email-Ops count is 3 (2 drafts + 1 send kit), 1 Accounting-Ops approval, 2 proposals.
    assert needs["count"] == 6
    assert {item["app"] for item in needs["items"]} == {"email-ops", "accounting-ops", "project-ops"}
    assert len(needs["items"]) == 5

    today = module_by_id(document, "today")
    assert today["date"] == "2026-11-09"
    assert today["counts"] == {"tasks_due_today": 3, "tasks_overdue": 1, "follow_ups_due": 2}
    titles = [item["title"] for item in today["items"]]
    assert titles[0] == "Roaster maintenance window"  # all-day first
    assert "Call the roaster technician" in titles  # 22:00 local, still today in New York
    assert "Follow up with Dockside Hotel" in titles and "Follow up with Harbor Market" in titles
    assert "Order green coffee samples" not in titles and "Cancelled cupping session" not in titles

    since = module_by_id(document, "since_last_visit")
    assert since["cursor"] == "2026-11-06T23:12:00Z"
    assert since["counts"] == {"meetings_summarized": 2, "tasks_closed": 1, "monitor_updates": 2}

    meetings = module_by_id(document, "recent_meetings")
    assert [m["title"] for m in meetings["items"]][:2] == ["Wholesale pricing review", "Weekly roast plan"]
    assert meetings["items"][0]["open_action_items"] == 2
    assert meetings["items"][0]["duration_seconds"] == 2520

    topics = module_by_id(document, "watched_topics")
    assert [t["monitor_id"] for t in topics["items"]] == ["brf-arabica", "brf-events", "brf-wholesale"]
    assert topics["items"][0]["changed"] is True
    assert topics["items"][0]["drift_line"]["origin"] == "third_party"
    assert topics["changed_count"] == 1

    money = module_by_id(document, "money")
    assert money["cash"]["net_total"] == "18420.00"
    assert money["runway_months"] == "7.2"
    assert money["invoiced_not_due"] == {"amount": "2,900.00", "currency": "USD", "count": 2, "complete": True}

    usage = module_by_id(document, "usage")
    assert usage["credits"] == {
        "last_24_hours": 14, "last_30_days": 312, "pool": {"total": 1000, "used": 312, "available": 688},
    }
    assert document["status_line"]["text"] == "Six things need you, and five are due today."

    # Meeting-Ops was asked for the mapped org by slug, Project-Ops for the org id.
    mo_calls = [r for r in suite.calls if r.url.path == "/api/analytics/sessions"]
    assert mo_calls and mo_calls[0].headers["x-meetingops-org"] == "rivergreen-coffee"
    po_calls = [r for r in suite.calls if r.url.path == "/api/v1/tasks/my-tasks"]
    assert po_calls and po_calls[0].headers["x-workspace-id"] == ORG_ID


@pytest.mark.asyncio
async def test_every_upstream_call_carries_the_persons_own_token():
    ctx = make_ctx()
    document, suite = await build(ctx=ctx)
    assert suite.calls
    for request in suite.calls:
        assert request.headers["authorization"] == f"Bearer {ctx.access_token}"
        assert request.method == "GET"
    # The token never appears in the document.
    assert ctx.access_token not in json.dumps(document)


@pytest.mark.asyncio
async def test_upstream_401_gives_unavailable_reauth_never_an_exception():
    routes = suite_routes()
    routes["/api/v1/auth/profile"] = (401, {"detail": "Token is not authorized for project-ops"})
    routes["/api/auth/orgs"] = (401, {"detail": "expired"})
    document, _ = await build(suite=FakeSuite(routes))
    assert_contract(document)

    today = module_by_id(document, "today")
    po = source_for(today, "project-ops")
    assert po["status"] == "unavailable" and po["reason"] == "reauth"
    assert today["status"] == "ok" and today["partial"] is True  # Customer-Ops still answered
    meetings = module_by_id(document, "recent_meetings")
    assert meetings["status"] == "unavailable" and meetings["reason"] == "reauth"
    assert "Sign in again to refresh Project-Ops." in document["status_line"]["text"]
    # The upstream error text is never copied into the document.
    assert "not authorized for project-ops" not in json.dumps(document)


@pytest.mark.asyncio
async def test_expired_session_token_marks_apps_reauth_without_calling_them():
    document, suite = await build(ctx=make_ctx(token=EXPIRED_TOKEN))
    assert suite.calls == []
    for module_id in ("needs_you", "today", "recent_meetings", "watched_topics", "money"):
        module = module_by_id(document, module_id)
        assert module["status"] == "unavailable" and module["reason"] == "reauth", module_id
    # In-process modules still answer.
    assert module_by_id(document, "apps")["status"] == "ok"
    assert module_by_id(document, "usage")["status"] == "ok"
    assert document["status_line"]["text"] == "Sign in again to refresh your apps."


@pytest.mark.asyncio
async def test_a_slow_app_times_out_while_every_other_module_returns(monkeypatch):
    monkeypatch.setenv("HOME_APP_TIMEOUT_SECONDS", "0.3")
    monkeypatch.setenv("HOME_TOTAL_BUDGET_SECONDS", "3.0")
    routes = suite_routes()

    async def slow(request):
        await asyncio.sleep(2.0)
        return load("mo_sessions")

    routes["/api/analytics/sessions"] = slow
    loop = asyncio.get_running_loop()
    started = loop.time()
    document, _ = await build(suite=FakeSuite(routes))
    elapsed = loop.time() - started
    assert elapsed < 1.5, elapsed
    assert_contract(document)

    meetings = module_by_id(document, "recent_meetings")
    assert meetings["status"] == "unavailable" and meetings["reason"] == "timeout"
    since = module_by_id(document, "since_last_visit")
    assert source_for(since, "meeting-ops")["reason"] == "timeout"
    assert since["status"] == "ok" and since["partial"] is True
    assert since["counts"]["meetings_summarized"] is None
    assert since["counts"]["tasks_closed"] == 1
    for module_id in ("needs_you", "today", "apps", "watched_topics", "money", "usage"):
        assert module_by_id(document, module_id)["status"] == "ok", module_id


@pytest.mark.asyncio
async def test_the_total_budget_cuts_off_whatever_is_still_running(monkeypatch):
    monkeypatch.setenv("HOME_APP_TIMEOUT_SECONDS", "5.0")
    monkeypatch.setenv("HOME_TOTAL_BUDGET_SECONDS", "0.5")
    routes = suite_routes()

    async def hang(request):
        await asyncio.sleep(3.0)
        return load("cdr_briefs")

    routes["/api/briefs"] = hang
    routes["/api/notifications"] = hang
    loop = asyncio.get_running_loop()
    started = loop.time()
    document, _ = await build(suite=FakeSuite(routes))
    assert loop.time() - started < 1.5
    topics = module_by_id(document, "watched_topics")
    assert topics["status"] == "unavailable" and topics["reason"] == "timeout"
    assert module_by_id(document, "today")["status"] == "ok"


@pytest.mark.asyncio
async def test_an_upstream_500_is_unavailable_error():
    routes = suite_routes()
    routes["/api/briefs"] = (500, {"detail": "boom"})
    routes["/api/notifications"] = (502, {"detail": "bad gateway"})
    document, _ = await build(suite=FakeSuite(routes))
    topics = module_by_id(document, "watched_topics")
    assert topics["status"] == "unavailable" and topics["reason"] == "error"


@pytest.mark.asyncio
async def test_money_and_usage_are_absent_for_a_member():
    recorder = Recorder()
    document, suite = await build(ctx=make_ctx(role="member"), recorder=recorder)
    ids = [m["id"] for m in document["modules"]]
    assert ids == EXPECTED_MEMBER_MODULES
    assert "money" not in ids and "usage" not in ids
    # Nothing money-related was even fetched.
    assert not any(path.endswith("/cfo-brief") or path.endswith("/invoices") for path in suite.paths())
    assert not any(name in ("usage", "pool") for name, _ in recorder.calls)
    assert document["person"]["role"] == "member"


@pytest.mark.asyncio
async def test_money_is_present_for_an_owner_and_an_org_admin():
    for role, public in (("owner", "owner"), ("admin", "org_admin")):
        document, suite = await build(ctx=make_ctx(role=role))
        money = module_by_id(document, "money")
        assert money is not None and money["status"] == "ok", role
        assert any(path.endswith("/cfo-brief") for path in suite.paths())
        assert document["person"]["role"] == public


@pytest.mark.asyncio
async def test_billing_admin_and_unknown_role_get_the_member_view():
    for role in ("billing_admin", None):
        document, _ = await build(ctx=make_ctx(role=role))
        assert module_by_id(document, "money") is None, role


@pytest.mark.asyncio
async def test_an_app_the_org_does_not_have_is_not_entitled_and_never_called():
    cards = [card for card in load("oc_apps") if card["slug"] != "customer-ops"]
    document, suite = await build(cards=cards)
    today = module_by_id(document, "today")
    co = source_for(today, "customer-ops")
    assert co["status"] == "not_entitled"
    assert co["url"] == "https://home.example.com/marketplace"
    assert not any("customers" in host for host in suite.hosts())
    assert today["counts"]["follow_ups_due"] is None


@pytest.mark.asyncio
async def test_unlinked_workspace_is_not_set_up_and_shows_no_other_orgs_data():
    routes = suite_routes()
    routes["/api/v1/auth/me/workspaces"] = {"workspaces": [
        {"workspace_id": "a1b2c3d4-0000-4000-8000-00000000beef", "slug": "someone-else",
         "display_name": "Another workspace", "role": "owner", "is_default": True}
    ]}
    document, suite = await build(suite=FakeSuite(routes))
    needs = module_by_id(document, "needs_you")
    eo = source_for(needs, "email-ops")
    assert eo["status"] == "not_set_up"
    assert "No Email-Ops workspace is linked" in eo["note"]
    assert not any(path.endswith("/agent-inbox") for path in suite.paths())
    assert not any(item["app"] == "email-ops" for item in needs["items"])


@pytest.mark.asyncio
async def test_meeting_ops_without_a_link_is_not_set_up():
    document, suite = await build(rows={})
    meetings = module_by_id(document, "recent_meetings")
    assert meetings["status"] == "not_set_up"
    assert "/api/analytics/sessions" not in suite.paths()


@pytest.mark.asyncio
async def test_catalog_failure_keeps_calling_apps_and_marks_only_apps_unavailable():
    document, suite = await build(apps_error=RuntimeError("catalog down"))
    apps = module_by_id(document, "apps")
    assert apps["status"] == "unavailable" and apps["reason"] == "error"
    assert module_by_id(document, "today")["status"] == "ok"
    assert "/api/v1/tasks/my-tasks" in suite.paths()


@pytest.mark.asyncio
async def test_first_visit_has_no_cursor_and_says_so():
    document, _ = await build(cursor=None)
    since = module_by_id(document, "since_last_visit")
    assert since["status"] == "empty" and since["cursor"] is None
    assert since["note"].startswith("This is your first visit")


@pytest.mark.asyncio
async def test_nothing_needs_you_is_a_complete_state():
    routes = suite_routes()
    routes[f"/api/v1/workspaces/{ORG_ID}/agent-inbox"] = {"items": [], "count": 0}
    routes[f"/api/workspaces/{ORG_ID}/approvals"] = {"approvals": [], "total": 0}
    routes["/api/v1/triage/proposals"] = []
    routes["/api/v1/tasks/my-tasks"] = []
    routes[f"/api/v1/workspaces/{ORG_ID}/customers"] = {"items": [], "count": 0}
    document, _ = await build(suite=FakeSuite(routes))
    assert module_by_id(document, "needs_you")["status"] == "empty"
    assert module_by_id(document, "today")["status"] == "empty"
    assert document["status_line"]["text"] == "Nothing needs you."
    assert document["status_line"]["needs_you_count"] == 0


@pytest.mark.asyncio
async def test_an_org_with_nothing_linked_says_so_plainly():
    routes = suite_routes()
    routes["/api/v1/auth/profile"] = dict(load("po_profile"), workspaces=[])
    routes["/api/v1/auth/me/workspaces"] = {"workspaces": []}
    routes[f"/api/workspaces/{ORG_ID}"] = (403, {"detail": "No active membership for this workspace"})
    document, _ = await build(suite=FakeSuite(routes))
    assert module_by_id(document, "needs_you")["status"] == "not_set_up"
    assert module_by_id(document, "today")["status"] == "not_set_up"
    assert document["status_line"]["text"] == "Your apps are not linked to this home yet."
    assert document["status_line"]["needs_you_count"] is None


# --------------------------------------------------------------------------- #
# Address rules
# --------------------------------------------------------------------------- #

PRIVATE_PATTERNS = [
    re.compile(r"\.internal\b", re.I),
    re.compile(r"\.ts\.net\b", re.I),
    re.compile(r"\blocalhost\b", re.I),
]


def private_ipv4_in(text):
    found = []
    for match in re.finditer(r"(?<![\d.])(\d{1,3}(?:\.\d{1,3}){3})(?![\d.])", text):
        try:
            address = ipaddress.ip_address(match.group(1))
        except ValueError:
            continue
        if address.is_private or address in ipaddress.ip_network("100.64.0.0/10"):
            found.append(match.group(1))
    return found


def assert_no_private_address(document):
    text = json.dumps(document)
    for pattern in PRIVATE_PATTERNS:
        assert not pattern.search(text), pattern.pattern
    assert private_ipv4_in(text) == []


def hostile_suite():
    """Upstream text that mentions internal addresses, as third-party data might."""

    routes = suite_routes()
    inbox = load("eo_agent_inbox")
    inbox["items"][0]["body_preview"] = (
        "Ping me at http://10.4.0.12:8080/status or db.internal or tower.example-tail.ts.net "
        "or 100.70.1.2 or https://ops.magicunicorn.dev/admin"
    )
    routes[f"/api/v1/workspaces/{ORG_ID}/agent-inbox"] = inbox
    return FakeSuite(routes)


@pytest.mark.asyncio
async def test_customer_ring_never_names_the_internal_ring_or_a_private_address(monkeypatch):
    # The real committed customer-ring config: no web overrides, so links come
    # from the catalog and backend/config/mcps-index.unicorncommander.json.
    for name in [
        "HOME_PROJECT_OPS_WEB_URL", "HOME_MEETING_OPS_WEB_URL", "HOME_EMAIL_OPS_WEB_URL",
        "HOME_ACCOUNTING_OPS_WEB_URL", "HOME_CUSTOMER_OPS_WEB_URL", "HOME_CENTER_DEEP_WEB_URL",
    ]:
        monkeypatch.delenv(name, raising=False)
    # A server-side API address may be internal; it must never reach the document.
    monkeypatch.setenv("HOME_PROJECT_OPS_API_URL", "http://10.20.30.40:3001")
    monkeypatch.setenv("HOME_ACCOUNTING_OPS_API_URL", "http://accounting-app:8000")
    cards = load("oc_apps")
    for card in cards:
        card["launch_url"] = card["launch_url"].replace("example.com", "unicorncommander.ai")
    # A mis-seeded catalog row pointing at the internal ring.
    cards[1]["launch_url"] = "https://meetingops.magicunicorn.dev"
    cards[1]["companion"]["mcp_url"] = "https://meetingops.magicunicorn.dev/mcp"
    cards[1]["companion"]["claude_code_command"] = (
        "claude mcp add --transport http meeting-ops https://meetingops.magicunicorn.dev/mcp"
    )
    cards[1]["companion"]["client_config"] = {
        "mcpServers": {"meeting-ops": {"url": "https://meetingops.magicunicorn.dev/mcp"}}
    }

    ctx = make_ctx(ring="customer", ops_center_web="https://unicorncommander.ai")
    document, suite = await build(ctx=ctx, suite=hostile_suite(), cards=cards)
    text = json.dumps(document)
    assert "magicunicorn.dev" not in text
    assert_no_private_address(document)
    assert "accounting-app" not in text and "10.20.30.40" not in text
    # The private API address was still used server side.
    assert "10.20.30.40" in suite.hosts()
    apps = module_by_id(document, "apps")
    meeting_tile = next(tile for tile in apps["items"] if tile["slug"] == "meeting-ops")
    assert meeting_tile["open"] is None and meeting_tile["connect_ai"] is None
    project_tile = next(tile for tile in apps["items"] if tile["slug"] == "project-ops")
    assert project_tile["open"] == "https://projectops.unicorncommander.ai"
    # Meeting-Ops links fall back to the customer index host, never the bad row.
    meetings = module_by_id(document, "recent_meetings")
    assert meetings["items"][0]["href"].startswith("https://meeting-ops.unicorncommander.ai/#/sessions/")


@pytest.mark.asyncio
async def test_internal_ring_has_no_private_address_either(monkeypatch):
    monkeypatch.setenv("HOME_MEETING_OPS_WEB_URL", "http://192.168.1.220:8480")
    monkeypatch.setenv("HOME_CENTER_DEEP_WEB_URL", "https://research.tail1234.ts.net")
    ctx = make_ctx(ring="internal", ops_center_web="https://magicunicorn.dev")
    document, _ = await build(ctx=ctx, suite=hostile_suite())
    assert_no_private_address(document)
    # The internal ring may link to itself.
    preview = module_by_id(document, "needs_you")["items"]
    assert any("magicunicorn.dev" in json.dumps(item) for item in preview)
