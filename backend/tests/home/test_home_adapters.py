"""Per-adapter behaviour against fixtures in each app's real response shape."""

from __future__ import annotations

from datetime import datetime, timezone

import httpx
import pytest

from home.adapters import accounting_ops, center_deep, customer_ops, email_ops, meeting_ops, project_ops
from home.adapters.base import (
    AdapterEnv,
    Forbidden,
    NotFound,
    Reauth,
    Rejected,
    UpstreamError,
    get_json,
    parse_iso,
)
from home.context import token_expired
from home.mapping import workspace_candidates
from homekit import (
    EXPIRED_TOKEN,
    NOW,
    ORG_ID,
    PERSON_SUB,
    VALID_TOKEN,
    FakeSuite,
    load,
    make_ctx,
    suite_routes,
)


def env_for(app, suite, *, api, web, rows=None, role="owner", want_money=None, timeout=1.0):
    ctx = make_ctx(role=role)
    client = suite.factory(timeout)
    return AdapterEnv(
        ctx=ctx, client=client, app=app, label=app, api_base=api, web_base=web,
        candidates=workspace_candidates(ORG_ID, app, rows or {}), timeout=timeout,
        want_money=ctx.is_manager if want_money is None else want_money,
    )


# --------------------------------------------------------------------------- #
# base
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status, expected",
    [(401, Reauth), (403, Forbidden), (404, NotFound), (400, Rejected), (422, Rejected),
     (500, UpstreamError), (302, UpstreamError), (503, UpstreamError)],
)
async def test_get_json_maps_status_codes(status, expected):
    def handler(request):
        return httpx.Response(status, json={"detail": "fictional upstream detail"},
                              headers={"location": "https://login.example.com/"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=False)
    env = AdapterEnv(ctx=make_ctx(), client=client, app="x", label="X", api_base="https://x.example.com",
                     web_base=None, candidates=[], timeout=1.0)
    with pytest.raises(expected) as caught:
        await get_json(env, "/api/thing")
    assert "fictional upstream detail" not in str(caught.value)
    await client.aclose()


@pytest.mark.asyncio
async def test_get_json_timeout_and_bad_body():
    def slow(request):
        raise httpx.ReadTimeout("slow", request=request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(slow))
    env = AdapterEnv(ctx=make_ctx(), client=client, app="x", label="X", api_base="https://x.example.com",
                     web_base=None, candidates=[], timeout=1.0)
    with pytest.raises(UpstreamError) as caught:
        await get_json(env, "/api/thing")
    assert caught.value.reason == "timeout"
    await client.aclose()

    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, text="<html>")))
    env.client = client
    with pytest.raises(UpstreamError) as caught:
        await get_json(env, "/api/thing")
    assert caught.value.reason == "error"
    await client.aclose()


def test_parse_iso_handles_the_forms_the_apps_send():
    assert parse_iso("2026-11-09T00:00:00.000Z") == datetime(2026, 11, 9, tzinfo=timezone.utc)
    assert parse_iso("2026-11-07T13:30:00") == datetime(2026, 11, 7, 13, 30, tzinfo=timezone.utc)
    assert parse_iso("2026-11-08T21:10:00+00:00").tzinfo is not None
    assert parse_iso("2026-11-08T21:10:00.1234567Z").microsecond == 123456
    assert parse_iso("2026-11-14") == datetime(2026, 11, 14, tzinfo=timezone.utc)
    assert parse_iso("not a date") is None and parse_iso(None) is None


def test_token_expiry_precheck():
    assert token_expired(VALID_TOKEN, NOW) is False
    assert token_expired(EXPIRED_TOKEN, NOW) is True
    assert token_expired(None, NOW) is True
    assert token_expired("opaque-token-without-dots", NOW) is False


# --------------------------------------------------------------------------- #
# Project-Ops
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_project_ops_normalizes_tasks_and_proposals():
    suite = FakeSuite(suite_routes())
    env = env_for("project-ops", suite, api="https://api.po.example.com", web="https://po.example.com")
    snap = await project_ops.fetch(env)
    assert snap.status == "ok" and snap.workspace == ORG_ID and snap.role == "MANAGER"
    tasks = {t["id"]: t for t in snap.parts["my_tasks"].data}
    assert tasks["task-roaster-maint"]["all_day"] is True
    assert tasks["task-price-sheet"]["all_day"] is False
    assert tasks["task-roaster-maint"]["href"] == "https://po.example.com/dashboard/tasks/task-roaster-maint"
    assert tasks["task-roaster-maint"]["blocked"] is False
    triage = snap.parts["triage"].data
    assert triage["count"] == 2 and triage["count_is_lower_bound"] is False
    assert triage["items"][0]["title"] == "Send Harbor Market the January price sheet"
    assert [item["project_id"] for item in triage["items"]] == ["proj-sales", None]
    calls = [(r.url.path, dict(r.url.params)) for r in suite.calls]
    assert ("/api/v1/triage/proposals", {"status": "PENDING", "limit": "50"}) in calls
    await env.client.aclose()


@pytest.mark.asyncio
async def test_project_ops_client_role_never_asks_for_triage():
    routes = suite_routes()
    profile = load("po_profile")
    profile["role"] = "CLIENT"
    routes["/api/v1/auth/profile"] = profile
    suite = FakeSuite(routes)
    env = env_for("project-ops", suite, api="https://api.po.example.com", web="https://po.example.com")
    snap = await project_ops.fetch(env)
    assert snap.parts["triage"].status == "not_entitled"
    assert "/api/v1/triage/proposals" not in suite.paths()
    assert snap.parts["my_tasks"].status == "ok"
    await env.client.aclose()


@pytest.mark.asyncio
async def test_project_ops_one_failing_route_does_not_hide_the_other():
    routes = suite_routes()
    routes["/api/v1/triage/proposals"] = (403, {"message": "Forbidden"})
    routes["/api/v1/tasks/my-tasks"] = (500, {"message": "boom"})
    suite = FakeSuite(routes)
    env = env_for("project-ops", suite, api="https://api.po.example.com", web="https://po.example.com")
    snap = await project_ops.fetch(env)
    assert snap.status == "ok"
    assert snap.parts["triage"].status == "not_entitled"
    assert snap.parts["my_tasks"].status == "unavailable" and snap.parts["my_tasks"].reason == "error"
    await env.client.aclose()


# --------------------------------------------------------------------------- #
# Meeting-Ops
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_meeting_ops_maps_a_numeric_org_id_to_its_slug_header():
    suite = FakeSuite(suite_routes())
    env = env_for("meeting-ops", suite, api="https://mo.example.com", web="https://mo.example.com",
                  rows={"meeting-ops": "41"})
    snap = await meeting_ops.fetch(env)
    assert snap.status == "ok" and snap.workspace == "rivergreen-coffee"
    for request in suite.calls[1:]:
        assert request.headers["x-meetingops-org"] == "rivergreen-coffee"
    sessions = snap.parts["sessions"].data["items"]
    assert sessions[0]["href"] == "https://mo.example.com/#/sessions/sess-pricing"
    assert sessions[1]["duration_seconds"] == 1500
    assert snap.parts["action_items"].data["count"] == 3
    await env.client.aclose()


@pytest.mark.asyncio
async def test_meeting_ops_never_relies_on_the_silent_default_org():
    suite = FakeSuite(suite_routes())
    env = env_for("meeting-ops", suite, api="https://mo.example.com", web="https://mo.example.com",
                  rows={"meeting-ops": "someone-elses-org"})
    snap = await meeting_ops.fetch(env)
    assert snap.status == "not_set_up"
    assert suite.paths() == ["/api/auth/orgs"]
    await env.client.aclose()


# --------------------------------------------------------------------------- #
# Email-Ops
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_email_ops_count_includes_send_kits_beyond_the_items():
    suite = FakeSuite(suite_routes())
    env = env_for("email-ops", suite, api="https://eo.example.com", web="https://eo.example.com")
    snap = await email_ops.fetch(env)
    part = snap.parts["agent_inbox"]
    assert part.data["count"] == 3 and len(part.data["items"]) == 2
    assert part.screen == "https://eo.example.com/agent-inbox"
    assert part.route == f"/api/v1/workspaces/{ORG_ID}/agent-inbox"
    await env.client.aclose()


@pytest.mark.asyncio
async def test_email_ops_inbox_failure_is_a_part_state():
    routes = suite_routes()
    routes[f"/api/v1/workspaces/{ORG_ID}/agent-inbox"] = (503, {"message": "down"})
    suite = FakeSuite(routes)
    env = env_for("email-ops", suite, api="https://eo.example.com", web="https://eo.example.com")
    snap = await email_ops.fetch(env)
    assert snap.status == "ok"
    assert snap.parts["agent_inbox"].status == "unavailable"
    await env.client.aclose()


# --------------------------------------------------------------------------- #
# Accounting-Ops
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_accounting_ops_probe_skips_non_uuid_and_forbidden_candidates():
    mapped = "c0ffee00-1111-4222-8333-444455556666"
    routes = suite_routes()
    routes[f"/api/workspaces/{ORG_ID}"] = (403, {"detail": "No active membership for this workspace"})
    routes[f"/api/workspaces/{mapped}"] = dict(load("ao_workspace"), id=mapped)
    routes[f"/api/workspaces/{mapped}/approvals"] = load("ao_approvals")
    routes[f"/api/workspaces/{mapped}/cfo-brief"] = load("ao_cfo_brief")
    routes[f"/api/workspaces/{mapped}/invoices"] = load("ao_invoices")
    suite = FakeSuite(routes)
    env = env_for("accounting-ops", suite, api="https://ao.example.com", web="https://ledger.example.com",
                  rows={"accounting-ops": mapped})
    snap = await accounting_ops.fetch(env)
    assert snap.status == "ok" and snap.workspace == mapped and snap.workspace_origin == "org_app_workspaces"
    assert snap.parts["approvals"].data["count"] == 1
    assert snap.parts["invoices"].data["amount"] == "2,900.00"
    await env.client.aclose()

    suite = FakeSuite(suite_routes())
    env = env_for("accounting-ops", suite, api="https://ao.example.com", web="https://ledger.example.com",
                  rows={"accounting-ops": "not-a-uuid"})
    env.candidates = env.candidates[1:]  # only the non-UUID row
    snap = await accounting_ops.fetch(env)
    assert snap.status == "not_set_up" and suite.calls == []
    await env.client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("ao_role", ["viewer", "client_user", "bookkeeper", "", "auditor"])
async def test_accounting_ops_below_accountant_gets_no_approvals_and_member_no_money(ao_role):
    # Accounting-Ops lists and decides approvals from accountant up
    # (ebd7796 app/api/approvals.py:107, :206); an unknown role ranks below all.
    routes = suite_routes()
    routes[f"/api/workspaces/{ORG_ID}"] = dict(load("ao_workspace"), role=ao_role)
    suite = FakeSuite(routes)
    env = env_for("accounting-ops", suite, api="https://ao.example.com", web="https://ledger.example.com",
                  role="member")
    snap = await accounting_ops.fetch(env)
    assert snap.parts["approvals"].status == "not_entitled"
    assert snap.parts["approvals"].note == (
        "Deciding approvals needs the accountant role or higher in Accounting-Ops."
    )
    assert "cfo_brief" not in snap.parts and "invoices" not in snap.parts
    assert suite.paths() == [f"/api/workspaces/{ORG_ID}"]
    await env.client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("ao_role", ["accountant", "cpa", "admin", "owner", "client_owner", "ACCOUNTANT"])
async def test_accounting_ops_accountant_and_up_see_the_approvals(ao_role):
    # decide_approval's floor is accountant (ebd7796 app/api/approvals.py:189-206),
    # so an accountant gets the approvals the home can act on. The two money
    # routes stay for Ops-Center owners and admins only: this person is a member.
    routes = suite_routes()
    routes[f"/api/workspaces/{ORG_ID}"] = dict(load("ao_workspace"), role=ao_role)
    suite = FakeSuite(routes)
    env = env_for("accounting-ops", suite, api="https://ao.example.com", web="https://ledger.example.com",
                  role="member")
    snap = await accounting_ops.fetch(env)
    approvals = snap.parts["approvals"]
    assert approvals.status == "ok" and approvals.note is None
    assert approvals.data["count"] == 1 and approvals.data["items"][0]["id"] == "ap-1"
    assert suite.paths() == [f"/api/workspaces/{ORG_ID}", f"/api/workspaces/{ORG_ID}/approvals"]
    assert "cfo_brief" not in snap.parts and "invoices" not in snap.parts
    await env.client.aclose()


def test_invoiced_not_due_counts_only_open_invoices_not_yet_due():
    rows = load("ao_invoices")["invoices"]
    assert accounting_ops.invoiced_not_due(rows, 5) == {
        "amount": "2,900.00", "currency": "USD", "count": 2, "complete": True,
    }
    assert accounting_ops.invoiced_not_due(rows, 900)["complete"] is False
    assert accounting_ops.money_text(1284.5) == "1,284.50"


# --------------------------------------------------------------------------- #
# Customer-Ops
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_customer_ops_asks_for_the_persons_own_relationships():
    suite = FakeSuite(suite_routes())
    env = env_for("customer-ops", suite, api="https://api.customers.example.com",
                  web="https://customers.example.com")
    snap = await customer_ops.fetch(env)
    request = next(r for r in suite.calls if r.url.path.endswith("/customers"))
    assert request.url.params["ownerUserKey"] == PERSON_SUB
    assert request.url.params["limit"] == "200"
    rows = {row["id"]: row for row in snap.parts["followups"].data["items"]}
    assert rows["cust-harbor"]["name"] == "Harbor Market"
    assert rows["cust-unscheduled"]["name"] is None and rows["cust-unscheduled"]["next_action_at"] is None
    await env.client.aclose()


# --------------------------------------------------------------------------- #
# Center Deep Research
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_center_deep_reads_briefs_and_notifications_per_person():
    suite = FakeSuite(suite_routes())
    env = env_for("center-deep", suite, api="https://research.example.com", web="https://research.example.com")
    snap = await center_deep.fetch(env)
    assert snap.status == "ok" and snap.workspace is None
    briefs = {b["id"]: b for b in snap.parts["briefs"].data}
    assert briefs["brf-situation"]["kind"] == "situation"
    assert briefs["brf-oneoff"]["enabled"] is False
    notes = snap.parts["notifications"].data["items"]
    assert notes[0]["changed"] is True
    assert notes[0]["line"].startswith("Freight quotes rose")
    assert notes[0]["run_href"] == "https://research.example.com/#/run/run-903"
    assert dict(next(r for r in suite.calls if r.url.path == "/api/notifications").url.params) == {"limit": "100"}
    await env.client.aclose()


@pytest.mark.asyncio
async def test_center_deep_401_is_reauth():
    routes = suite_routes()
    routes["/api/briefs"] = (401, {"detail": "invalid token"})
    suite = FakeSuite(routes)
    env = env_for("center-deep", suite, api="https://research.example.com", web="https://research.example.com")
    snap = await center_deep.fetch(env)
    assert snap.status == "unavailable" and snap.reason == "reauth"
    await env.client.aclose()
