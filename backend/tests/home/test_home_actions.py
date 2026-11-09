"""POST /api/v1/home/actions/{source}/{item_id}/{action}: forward, receipt, idempotency.

The router is mounted on a bare FastAPI app (server.py is never imported). The
apps are the fictional ``FakeSuite`` hosts under example.com, and the receipt
table is ``ReceiptsDB``: an in-memory stand-in behind the exact three
statements ``PgReceiptStore`` sends, which records every parameter it is
given. Rivergreen Coffee Co., Harbor Market and every id here are fictional.
"""

from __future__ import annotations

import ast
import asyncio
import json
import re
import sys
from dataclasses import replace
from datetime import timedelta
from types import ModuleType
from typing import Any, Dict, List, Optional, Tuple

import httpx
import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

import home_api
from home import actions
from home.adapters.base import AdapterEnv
from home.context import HomeContext
from homekit import (
    API_HOSTS,
    BACKEND,
    EXPIRED_TOKEN,
    NOW,
    ORG_ID,
    PERSON_SUB,
    VALID_TOKEN,
    FakeSuite,
    load,
    make_ctx,
)

EO_ITEM = "3f6c2a1e-8b4d-4c2a-9e1f-5a7b8c9d0e11"
AO_ITEM = "7d1e9f20-3c4b-4a5d-8e6f-1a2b3c4d5e66"
PO_PROPOSAL = "b2c3d4e5-f6a7-4b8c-9d0e-1f2a3b4c5d77"
PO_TASK = "c3d4e5f6-a7b8-4c9d-8e0f-2a3b4c5d6e88"
OTHER_ORG = "9a8b7c6d-5e4f-4a3b-8c2d-1e0f9a8b7c6d"
KEY = "rivergreen-action-0001"

EO_APPROVE = f"/api/v1/workspaces/{ORG_ID}/agent-inbox/{EO_ITEM}/approve"
EO_REJECT = f"/api/v1/workspaces/{ORG_ID}/agent-inbox/{EO_ITEM}/reject"
AO_DECIDE = f"/api/workspaces/{ORG_ID}/approvals/{AO_ITEM}/decide"
PO_ACCEPT = f"/api/v1/triage/proposals/{PO_PROPOSAL}/approve"
PO_REJECT = f"/api/v1/triage/proposals/{PO_PROPOSAL}/reject"
PO_STATUS = f"/api/v1/tasks/{PO_TASK}/status"

PREVIEW = "Hi Dana, thanks for the note. The January sheet is attached."
SUBJECT = "Re: Wholesale pricing for January"


@pytest.fixture(autouse=True)
def actions_env(monkeypatch):
    monkeypatch.setenv("HOME_ACTIONS_ENABLED", "true")
    monkeypatch.delenv("HOME_ACTION_TIMEOUT_SECONDS", raising=False)
    yield


# --------------------------------------------------------------------------- #
# Fakes
# --------------------------------------------------------------------------- #


class ReceiptsDB:
    """home_action_receipts behind RESERVE_SQL, FIND_SQL and COMPLETE_SQL."""

    COLUMNS = {
        "id", "org_id", "person_subject", "source", "item_id", "action", "idempotency_key",
        "upstream_status", "outcome", "message", "created_at",
    }

    def __init__(self):
        self.rows: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
        self.params: List[Tuple[Any, ...]] = []
        self.fail: Optional[BaseException] = None
        self.connections = 0
        self.now = NOW

    async def connect(self):
        if self.fail is not None:
            raise self.fail
        self.connections += 1
        return FakeReceiptConn(self)

    def seed(self, *, created_at, outcome=None, source="accounting-ops",
             item_id=f"ao:approval:{AO_ITEM}", action="approve", key=KEY):
        self.rows[(ORG_ID, PERSON_SUB, key)] = {
            "id": "5e5e5e5e-0000-4000-8000-000000000001", "org_id": ORG_ID,
            "person_subject": PERSON_SUB, "source": source, "item_id": item_id, "action": action,
            "idempotency_key": key, "upstream_status": None, "outcome": outcome, "message": None,
            "created_at": created_at,
        }

    def only_row(self) -> Dict[str, Any]:
        assert len(self.rows) == 1, self.rows
        return next(iter(self.rows.values()))


class FakeReceiptConn:
    def __init__(self, db: ReceiptsDB):
        self.db = db

    async def fetchrow(self, query, *params):
        self.db.params.append(params)
        if query == actions.RESERVE_SQL:
            row_id, org, person, source, item_id, action, key = params
            assert 1 <= len(key) <= 200  # the key length CHECK
            if (str(org), person, key) in self.db.rows:
                return None
            self.db.rows[(str(org), person, key)] = {
                "id": row_id, "org_id": str(org), "person_subject": person, "source": source,
                "item_id": item_id, "action": action, "idempotency_key": key,
                "upstream_status": None, "outcome": None, "message": None, "created_at": self.db.now,
            }
            return {"created_at": self.db.now}
        if query == actions.FIND_SQL:
            org, person, key, stale_after = params
            row = self.db.rows.get((str(org), person, key))
            if row is None:
                return None
            stale = row["outcome"] is None and row["created_at"] < self.db.now - timedelta(seconds=stale_after)
            return {**row, "stale": stale}
        raise AssertionError(f"unexpected statement: {query}")

    async def execute(self, query, *params):
        self.db.params.append(params)
        assert query == actions.COMPLETE_SQL
        row_id, status, outcome, message = params
        assert outcome in actions.OUTCOMES  # the outcome CHECK
        assert message is None or len(message) <= 400  # the message CHECK
        for row in self.db.rows.values():
            if row["id"] == row_id and row["outcome"] is None:
                row.update(upstream_status=status, outcome=outcome, message=message)
                return "UPDATE 1"
        return "UPDATE 0"

    async def close(self):
        return None


def eo_answer(state: str, *, mail: bool = True, sends_at: Optional[str] = None):
    """Email-Ops' {inbox, message} answer, with a recipient and a preview that
    must never reach a receipt."""

    return {
        "inbox": {
            "id": EO_ITEM, "state": state, "kind": "email", "to_address": "dana@harbormarket.example",
            "subject": SUBJECT, "body_preview": PREVIEW, "sends_at": sends_at,
        },
        "message": {"id": "c0ffee00-0000-4000-8000-000000000002", "status": "SENT",
                    "to_address": "dana@harbormarket.example", "subject": SUBJECT} if mail else None,
    }


def ao_answer(request: httpx.Request):
    decision = json.loads(request.content)["decision"]
    return {"ok": True, "approval_id": AO_ITEM,
            "decision": "approved" if decision == "approve" else "rejected",
            "subject_type": "bank_transaction_import", "applied": decision == "approve"}


def action_routes() -> Dict[str, Any]:
    return {
        # Membership reads (the same routes the home-state adapters use)
        "/api/v1/auth/me/workspaces": load("eo_workspaces"),
        "/api/v1/auth/profile": load("po_profile"),
        f"/api/workspaces/{ORG_ID}": load("ao_workspace"),
        # Writes
        EO_APPROVE: eo_answer("approved"),
        EO_REJECT: eo_answer("rejected"),
        AO_DECIDE: ao_answer,
        PO_ACCEPT: {"id": PO_PROPOSAL, "status": "APPLIED", "createdTaskId": PO_TASK},
        PO_REJECT: {"id": PO_PROPOSAL, "status": "REJECTED"},
        PO_STATUS: {"id": PO_TASK, "status": "COMPLETED", "title": "Roaster maintenance window"},
    }


def make_providers(suite: FakeSuite, db: ReceiptsDB, rows: Optional[Dict[str, str]] = None):
    async def workspace_rows():
        return rows or {}

    return actions.ActionProviders(
        store=actions.PgReceiptStore(db.connect), workspace_rows=workspace_rows, client_factory=suite.factory
    )


def action_app(routes=None, *, ctx: Optional[HomeContext] = None, db: Optional[ReceiptsDB] = None):
    suite = FakeSuite(action_routes() if routes is None else routes)
    db = db or ReceiptsDB()
    app = FastAPI()
    app.include_router(home_api.router)
    app.dependency_overrides[home_api.get_home_context] = lambda: ctx or make_ctx()
    app.dependency_overrides[home_api.get_action_providers] = lambda: make_providers(suite, db)
    return app, suite, db


def action_client(routes=None, **kwargs):
    app, suite, db = action_app(routes, **kwargs)
    return TestClient(app), suite, db


def post(client, source, item_id, action, key: Optional[str] = KEY, **headers):
    if key is not None:
        headers["Idempotency-Key"] = key
    return client.post(f"/api/v1/home/actions/{source}/{item_id}/{action}", headers=headers)


def writes(suite: FakeSuite) -> List[httpx.Request]:
    return [request for request in suite.calls if request.method != "GET"]


def assert_plain(text: str):
    """House copy rules for anything a person reads."""

    assert text and text.endswith((".", "?")), text
    assert "—" not in text and "–" not in text and "!" not in text, text
    assert len(text) <= 400


def assert_problem(response, status: int, code: str):
    assert response.status_code == status, response.text
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert body["status"] == status and body["code"] == code and body["type"] == "about:blank"
    assert_plain(body["detail"])
    assert_plain(body["fix"])
    return body


# --------------------------------------------------------------------------- #
# Flag
# --------------------------------------------------------------------------- #


def test_flag_off_returns_404_before_any_session_store_or_app_call(monkeypatch):
    monkeypatch.delenv("HOME_ACTIONS_ENABLED", raising=False)
    # No overrides: if the flag check did not run first, the real context
    # builder would try to read a session and fail differently.
    app = FastAPI()
    app.include_router(home_api.router)
    response = post(TestClient(app), "email-ops", f"eo:draft:{EO_ITEM}", "approve")
    assert response.status_code == 404
    assert response.json() == {"detail": "Not Found"}

    monkeypatch.setenv("HOME_ACTIONS_ENABLED", "false")
    client, suite, db = action_client()
    assert post(client, "email-ops", f"eo:draft:{EO_ITEM}", "approve").status_code == 404
    assert suite.calls == [] and db.connections == 0


def test_actions_flag_is_independent_of_the_home_state_flag(monkeypatch):
    monkeypatch.setenv("HOME_STATE_ENABLED", "true")
    monkeypatch.delenv("HOME_ACTIONS_ENABLED", raising=False)
    client, suite, _ = action_client()
    assert post(client, "email-ops", f"eo:draft:{EO_ITEM}", "approve").status_code == 404
    assert suite.calls == []

    monkeypatch.delenv("HOME_STATE_ENABLED", raising=False)
    monkeypatch.setenv("HOME_ACTIONS_ENABLED", "1")
    client, suite, _ = action_client()
    assert client.get("/api/v1/home/state").status_code == 404
    response = post(client, "email-ops", f"eo:draft:{EO_ITEM}", "approve")
    assert response.status_code == 200 and response.json()["outcome"] == "done"


# --------------------------------------------------------------------------- #
# Request checks
# --------------------------------------------------------------------------- #


def test_missing_idempotency_key_is_a_400_problem_and_nothing_is_called():
    client, suite, db = action_client()
    response = post(client, "accounting-ops", f"ao:approval:{AO_ITEM}", "approve", key=None)
    assert_problem(response, 400, "idempotency_key_missing")
    assert suite.calls == [] and db.connections == 0

    for bad in ("short", "has a space in it", "x" * 201, "quote\"inside1"):
        response = post(client, "accounting-ops", f"ao:approval:{AO_ITEM}", "approve", key=bad)
        assert_problem(response, 400, "idempotency_key_invalid")
    assert suite.calls == [] and db.connections == 0


def test_structured_field_quotes_around_the_key_are_accepted():
    client, _, db = action_client()
    response = post(client, "accounting-ops", f"ao:approval:{AO_ITEM}", "approve", key=f'"{KEY}"')
    assert response.status_code == 200
    assert response.json()["idempotency_key"] == KEY
    assert db.only_row()["idempotency_key"] == KEY


@pytest.mark.parametrize(
    "source, item_id, action, detail",
    [
        ("project-ops", f"po:task:{PO_TASK}", "approve", "A Project-Ops task allows: done."),
        ("project-ops", f"po:triage:{PO_PROPOSAL}", "done",
         "A Project-Ops triage proposal allows: accept or reject."),
        ("email-ops", f"eo:draft:{EO_ITEM}", "send", "An Email-Ops draft allows: approve or reject."),
        ("accounting-ops", f"ao:approval:{AO_ITEM}", "accept",
         "An Accounting-Ops approval allows: approve or reject."),
        ("meeting-ops", "mo:session:4d3c2b1a-0000-4000-8000-000000000003", "approve",
         "The home can act only on Email-Ops drafts, Accounting-Ops approvals, and Project-Ops "
         "triage proposals and tasks."),
        ("email-ops", f"ao:approval:{AO_ITEM}", "approve",
         "This is not an item id the home gave out for email-ops."),
        ("accounting-ops", "ao:approval:not-a-uuid", "approve",
         "This is not an item id the home gave out for accounting-ops."),
        ("project-ops", f"po:task:{PO_TASK}:extra", "done",
         "This is not an item id the home gave out for project-ops."),
    ],
)
def test_anything_else_is_a_400_problem_naming_the_allowed_actions(source, item_id, action, detail):
    client, suite, db = action_client()
    body = assert_problem(post(client, source, item_id, action), 400, "action_not_allowed")
    assert body["detail"] == detail
    assert body["allowed_actions"] == [
        {"source": "email-ops", "item_id": "eo:draft:<uuid>", "actions": ["approve", "reject"]},
        {"source": "accounting-ops", "item_id": "ao:approval:<uuid>", "actions": ["approve", "reject"]},
        {"source": "project-ops", "item_id": "po:triage:<uuid>", "actions": ["accept", "reject"]},
        {"source": "project-ops", "item_id": "po:task:<uuid>", "actions": ["done"]},
    ]
    assert suite.calls == [] and db.connections == 0


# --------------------------------------------------------------------------- #
# Each mapping, asserted on the request the app received
# --------------------------------------------------------------------------- #

MAPPINGS = [
    # source, item_id, action, host env, membership read, method, path, body, workspace header, message
    ("email-ops", f"eo:draft:{EO_ITEM}", "approve", "HOME_EMAIL_OPS_API_URL", "/api/v1/auth/me/workspaces",
     "POST", EO_APPROVE, {}, False, "Approved. Email-Ops handed it to the mail server."),
    ("email-ops", f"eo:draft:{EO_ITEM}", "reject", "HOME_EMAIL_OPS_API_URL", "/api/v1/auth/me/workspaces",
     "POST", EO_REJECT, {}, False, "Rejected. Email-Ops will not send it."),
    ("accounting-ops", f"ao:approval:{AO_ITEM}", "approve", "HOME_ACCOUNTING_OPS_API_URL",
     f"/api/workspaces/{ORG_ID}", "POST", AO_DECIDE, {"decision": "approve"}, False,
     "Approved. Accounting-Ops applied it."),
    ("accounting-ops", f"ao:approval:{AO_ITEM}", "reject", "HOME_ACCOUNTING_OPS_API_URL",
     f"/api/workspaces/{ORG_ID}", "POST", AO_DECIDE, {"decision": "reject"}, False,
     "Rejected. Accounting-Ops left the books as they were."),
    ("project-ops", f"po:triage:{PO_PROPOSAL}", "accept", "HOME_PROJECT_OPS_API_URL", "/api/v1/auth/profile",
     "POST", PO_ACCEPT, {}, True, "Accepted. Project-Ops created the task."),
    ("project-ops", f"po:triage:{PO_PROPOSAL}", "reject", "HOME_PROJECT_OPS_API_URL", "/api/v1/auth/profile",
     "POST", PO_REJECT, {}, True, "Rejected. Project-Ops did not create a task."),
    ("project-ops", f"po:task:{PO_TASK}", "done", "HOME_PROJECT_OPS_API_URL", "/api/v1/auth/profile",
     "PATCH", PO_STATUS, {"status": "COMPLETED"}, True, "Marked done in Project-Ops."),
]


@pytest.mark.parametrize(
    "source, item_id, action, host_env, probe, method, path, body, ws_header, message", MAPPINGS
)
def test_each_action_reaches_the_owning_apps_existing_route(
    source, item_id, action, host_env, probe, method, path, body, ws_header, message
):
    client, suite, db = action_client()
    response = post(client, source, item_id, action)
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("application/json")
    receipt = response.json()
    assert receipt["outcome"] == "done" and receipt["message"] == message
    assert receipt["upstream_status"] == 200 and receipt["replayed"] is False
    assert receipt["source"] == source and receipt["item_id"] == item_id and receipt["action"] == action
    assert receipt["schema"] == "uc.home.action_receipt/1"

    # One membership read, then exactly one write, both on the app's own host.
    assert [r.url.path for r in suite.calls] == [probe, path]
    write = writes(suite)
    assert len(write) == 1
    request = write[0]
    assert request.method == method
    assert f"https://{request.url.host}" == API_HOSTS[host_env]
    assert request.url.path == path and not request.url.query
    assert json.loads(request.content) == body
    assert request.headers["authorization"] == f"Bearer {VALID_TOKEN}"
    assert request.headers["content-type"] == "application/json"
    assert "cookie" not in request.headers
    if ws_header:
        assert request.headers["x-workspace-id"] == ORG_ID
    else:
        assert "x-workspace-id" not in request.headers

    row = db.only_row()
    assert row["outcome"] == "done" and row["upstream_status"] == 200 and row["message"] == message


@pytest.mark.asyncio
async def test_the_workspace_comes_from_the_org_link_when_the_org_id_is_not_a_workspace():
    linked = "1b2c3d4e-5f60-4718-9a0b-c1d2e3f4a5b6"
    routes = action_routes()
    routes["/api/v1/auth/me/workspaces"] = {"workspaces": [{"workspace_id": linked, "role": "member"}]}
    routes[f"/api/v1/workspaces/{linked}/agent-inbox/{EO_ITEM}/approve"] = eo_answer("approved")
    suite = FakeSuite(routes)
    db = ReceiptsDB()
    reply = await actions.run_action(
        make_ctx(), make_providers(suite, db, rows={"email-ops": linked}),
        "email-ops", f"eo:draft:{EO_ITEM}", "approve", KEY,
    )
    assert reply.body["outcome"] == "done"
    assert writes(suite)[0].url.path == f"/api/v1/workspaces/{linked}/agent-inbox/{EO_ITEM}/approve"


# --------------------------------------------------------------------------- #
# Idempotency
# --------------------------------------------------------------------------- #


def test_the_same_key_twice_calls_the_app_once_and_returns_the_same_receipt():
    client, suite, db = action_client()
    first = post(client, "accounting-ops", f"ao:approval:{AO_ITEM}", "approve")
    calls_after_first = len(suite.calls)
    second = post(client, "accounting-ops", f"ao:approval:{AO_ITEM}", "approve")

    assert first.status_code == second.status_code == 200
    assert len(writes(suite)) == 1
    assert len(suite.calls) == calls_after_first  # the repeat made no upstream call at all
    assert second.headers["idempotent-replayed"] == "true"
    assert "idempotent-replayed" not in first.headers
    one, two = first.json(), second.json()
    assert one.pop("replayed") is False and two.pop("replayed") is True
    assert one == two
    assert len(db.rows) == 1


@pytest.mark.asyncio
async def test_keys_are_scoped_per_person_and_per_org():
    routes = action_routes()
    routes[f"/api/workspaces/{OTHER_ORG}"] = {"id": OTHER_ORG, "role": "owner"}
    routes[f"/api/workspaces/{OTHER_ORG}/approvals/{AO_ITEM}/decide"] = ao_answer
    suite = FakeSuite(routes)
    db = ReceiptsDB()
    providers = make_providers(suite, db)
    item = f"ao:approval:{AO_ITEM}"

    mara = make_ctx()
    colleague = replace(mara, person_id="2e3f4a5b-6c7d-4e8f-9a0b-1c2d3e4f5a6b", display_name="Theo Lindqvist")
    other_org = replace(mara, org_id=OTHER_ORG, org_name="Harbor Market")
    replies = [
        await actions.run_action(ctx, providers, "accounting-ops", item, "approve", KEY)
        for ctx in (mara, colleague, other_org, mara)
    ]

    assert [r.body["replayed"] for r in replies] == [False, False, False, True]
    assert len({r.body["id"] for r in replies[:3]}) == 3
    assert replies[3].body["id"] == replies[0].body["id"]
    assert len(writes(suite)) == 3
    assert {(org, person) for org, person, _ in db.rows} == {
        (ORG_ID, PERSON_SUB), (ORG_ID, colleague.person_id), (OTHER_ORG, PERSON_SUB),
    }


def test_the_same_key_for_a_different_action_is_a_422_problem():
    client, suite, _ = action_client()
    assert post(client, "accounting-ops", f"ao:approval:{AO_ITEM}", "approve").status_code == 200
    response = post(client, "accounting-ops", f"ao:approval:{AO_ITEM}", "reject")
    assert_problem(response, 422, "idempotency_key_reused")
    assert len(writes(suite)) == 1


@pytest.mark.asyncio
async def test_two_requests_with_the_same_key_at_once_reach_the_app_once():
    release = asyncio.Event()

    async def slow_decide(request):
        await release.wait()
        return ao_answer(request)

    routes = action_routes()
    routes[AO_DECIDE] = slow_decide
    suite = FakeSuite(routes)
    providers = make_providers(suite, ReceiptsDB())
    item = f"ao:approval:{AO_ITEM}"

    first = asyncio.ensure_future(actions.run_action(make_ctx(), providers, "accounting-ops", item, "approve", KEY))
    for _ in range(300):
        if writes(suite):
            break
        await asyncio.sleep(0.01)
    assert len(writes(suite)) == 1

    try:  # a regression that forwards twice would wait on `release`; fail instead of hanging
        second = await asyncio.wait_for(
            actions.run_action(make_ctx(), providers, "accounting-ops", item, "approve", KEY), timeout=5
        )
    finally:
        release.set()
    assert second.status_code == 409 and second.body["code"] == "action_in_progress"
    assert second.headers["Retry-After"] == "2"
    done = await asyncio.wait_for(first, timeout=5)
    assert done.body["outcome"] == "done"
    assert len(writes(suite)) == 1


def test_an_unfinished_reservation_is_closed_as_failed_and_never_retried():
    db = ReceiptsDB()
    db.seed(created_at=NOW - timedelta(minutes=10))
    client, suite, _ = action_client(db=db)
    response = post(client, "accounting-ops", f"ao:approval:{AO_ITEM}", "approve")
    assert response.status_code == 200
    receipt = response.json()
    assert receipt["outcome"] == "failed" and receipt["replayed"] is True
    assert receipt["message"] == "This action did not finish. Check the item in Accounting-Ops before trying again."
    assert suite.calls == []
    assert db.only_row()["outcome"] == "failed"

    fresh = ReceiptsDB()
    fresh.seed(created_at=NOW - timedelta(seconds=5))
    client, suite, _ = action_client(db=fresh)
    assert_problem(post(client, "accounting-ops", f"ao:approval:{AO_ITEM}", "approve"), 409, "action_in_progress")
    assert suite.calls == []


# --------------------------------------------------------------------------- #
# Upstream outcomes
# --------------------------------------------------------------------------- #


def _raise(exc: Exception):
    def handler(request):
        raise exc

    return handler


@pytest.mark.parametrize(
    "answer, outcome, status, message",
    [
        ((401, {"detail": "invalid token"}), "reauth", 401, "Sign in again to finish this."),
        ((403, {"detail": "Journal proposal requires a human session"}), "refused", 403,
         "Accounting-Ops did not allow this. Open it in Accounting-Ops to finish it."),
        ((404, {"detail": "Approval not found"}), "refused", 404,
         "Accounting-Ops could not find this item. It may have been handled already."),
        ((409, {"detail": "Approval already approved"}), "refused", 409,
         "Accounting-Ops did not do this. It said: Approval already approved."),
        ((422, {"detail": "Cannot apply unknown subject_type 'mystery_import'"}), "refused", 422,
         "Accounting-Ops did not do this. It said: Cannot apply unknown subject_type 'mystery_import'."),
        ((409, {"message": "proposal is APPLIED", "statusCode": 409}), "refused", 409,
         "Accounting-Ops did not do this. It said: Proposal is APPLIED."),
        ((409, {"detail": "Ask dana@harbormarket.example to resend it"}), "refused", 409,
         "Accounting-Ops did not do this right now. Open it in Accounting-Ops to see why."),
        ((409, {"detail": "See https://ledger.example.com/approvals for details"}), "refused", 409,
         "Accounting-Ops did not do this right now. Open it in Accounting-Ops to see why."),
        ((409, {"detail": "ledger worker 10.20.0.7 refused the posting"}), "refused", 409,
         "Accounting-Ops did not do this right now. Open it in Accounting-Ops to see why."),
        ((409, {"detail": "key fictional0fictional0fictional0fictional0fictional rejected"}), "refused", 409,
         "Accounting-Ops did not do this right now. Open it in Accounting-Ops to see why."),
        ((422, {"detail": [{"loc": ["body", "decision"], "msg": "field required"}]}), "refused", 422,
         "Accounting-Ops did not do this right now. Open it in Accounting-Ops to see why."),
        ((409, {"detail": "Already decided — nothing to do"}), "refused", 409,
         "Accounting-Ops did not do this right now. Open it in Accounting-Ops to see why."),
        ((400, {"detail": "decision must be 'approve' or 'reject'"}), "failed", 400,
         "Accounting-Ops could not finish this. Check the item in Accounting-Ops before trying again."),
        ((500, {"detail": "Internal Server Error"}), "failed", 500,
         "Accounting-Ops could not finish this. Check the item in Accounting-Ops before trying again."),
        ((503, {"detail": "maintenance"}), "failed", 503,
         "Accounting-Ops could not finish this. Check the item in Accounting-Ops before trying again."),
        (httpx.Response(302, headers={"location": "https://sso.example.com/login"}), "failed", 302,
         "Accounting-Ops could not finish this. Check the item in Accounting-Ops before trying again."),
        (_raise(httpx.ReadTimeout("slow")), "failed", None,
         "Accounting-Ops did not answer in time. Check the item in Accounting-Ops before trying again."),
        (_raise(httpx.ConnectError("refused")), "failed", None,
         "Accounting-Ops could not be reached, so nothing was changed. Try again in a moment."),
        (_raise(httpx.RemoteProtocolError("reset")), "failed", None,
         "Accounting-Ops could not finish this. Check the item in Accounting-Ops before trying again."),
    ],
)
def test_upstream_answers_map_to_receipts_never_a_500(answer, outcome, status, message):
    routes = action_routes()
    routes[AO_DECIDE] = answer
    client, suite, db = action_client(routes)
    response = post(client, "accounting-ops", f"ao:approval:{AO_ITEM}", "approve")
    assert response.status_code == 200, response.text
    receipt = response.json()
    assert (receipt["outcome"], receipt["upstream_status"], receipt["message"]) == (outcome, status, message)
    assert_plain(receipt["message"])
    assert len(writes(suite)) == 1
    row = db.only_row()
    assert (row["outcome"], row["upstream_status"], row["message"]) == (outcome, status, message)


@pytest.mark.parametrize(
    "answer, outcome, message",
    [
        (eo_answer("rejected"), "refused", "This draft was already rejected in Email-Ops, so nothing changed."),
        (eo_answer("pending", sends_at="2026-11-09T18:00:00.000Z"), "refused",
         "Email-Ops already has a send time for this draft, so nothing changed."),
        (eo_answer("approved", sends_at="2026-11-09T18:00:00.000Z"), "done",
         "Approved. Email-Ops will send it at its scheduled time."),
        (eo_answer("approved", mail=False), "done", "Approved in Email-Ops."),
        ({"unexpected": "shape"}, "done", "Approved in Email-Ops."),
    ],
)
def test_email_ops_200_without_acting_is_not_reported_as_done(answer, outcome, message):
    routes = action_routes()
    routes[EO_APPROVE] = answer
    client, _, _ = action_client(routes)
    receipt = post(client, "email-ops", f"eo:draft:{EO_ITEM}", "approve").json()
    assert (receipt["outcome"], receipt["upstream_status"], receipt["message"]) == (outcome, 200, message)


def test_reject_of_an_already_approved_draft_is_refused():
    routes = action_routes()
    routes[EO_REJECT] = eo_answer("approved")
    client, _, _ = action_client(routes)
    receipt = post(client, "email-ops", f"eo:draft:{EO_ITEM}", "reject").json()
    assert receipt["outcome"] == "refused"
    assert receipt["message"] == "This draft was already approved in Email-Ops, so nothing changed."


@pytest.mark.parametrize(
    "probe_answer, outcome, status, message",
    [
        ((401, {"detail": "expired"}), "reauth", 401, "Sign in again to finish this."),
        ((403, {"detail": "no access"}), "refused", 403,
         "Email-Ops did not allow this. Open it in Email-Ops to finish it."),
        ((500, {"detail": "boom"}), "failed", 500,
         "Email-Ops had a problem, so nothing was changed. Try again in a moment."),
        (_raise(httpx.ReadTimeout("slow")), "failed", None,
         "Email-Ops did not answer in time, so nothing was changed. Try again in a moment."),
        ({"workspaces": []}, "refused", None,
         "No Email-Ops workspace is linked to this organization for you yet."),
    ],
)
def test_membership_read_outcomes_never_write(probe_answer, outcome, status, message):
    routes = action_routes()
    routes["/api/v1/auth/me/workspaces"] = probe_answer
    client, suite, _ = action_client(routes)
    receipt = post(client, "email-ops", f"eo:draft:{EO_ITEM}", "approve").json()
    assert (receipt["outcome"], receipt["upstream_status"], receipt["message"]) == (outcome, status, message)
    assert writes(suite) == []


def test_an_expired_session_token_is_reauth_without_any_call():
    client, suite, db = action_client(ctx=make_ctx(token=EXPIRED_TOKEN))
    receipt = post(client, "project-ops", f"po:task:{PO_TASK}", "done").json()
    assert receipt["outcome"] == "reauth" and receipt["message"] == "Sign in again to finish this."
    assert receipt["upstream_status"] is None
    assert suite.calls == []
    assert db.only_row()["outcome"] == "reauth"


def test_an_app_not_connected_on_this_ring_fails_plainly_without_a_call(monkeypatch):
    monkeypatch.delenv("HOME_ACCOUNTING_OPS_API_URL", raising=False)
    client, suite, _ = action_client()
    receipt = post(client, "accounting-ops", f"ao:approval:{AO_ITEM}", "approve").json()
    assert receipt["outcome"] == "failed"
    assert receipt["message"] == "Accounting-Ops is not connected to the home on this ring yet."
    assert suite.calls == []


def test_receipts_unavailable_is_a_503_problem_and_the_app_is_never_called():
    db = ReceiptsDB()
    db.fail = RuntimeError("relation home_action_receipts does not exist")
    client, suite, _ = action_client(db=db)
    assert_problem(post(client, "email-ops", f"eo:draft:{EO_ITEM}", "approve"), 503, "receipts_unavailable")
    assert suite.calls == []


def test_a_bug_after_the_write_is_a_failed_receipt_and_a_bug_before_is_a_503(monkeypatch):
    def broken(*args, **kwargs):
        raise KeyError("bug")

    monkeypatch.setattr(actions, "classify", broken)
    client, suite, _ = action_client()
    response = post(client, "accounting-ops", f"ao:approval:{AO_ITEM}", "approve")
    assert response.status_code == 200
    assert response.json()["outcome"] == "failed"
    assert response.json()["message"] == (
        "Accounting-Ops could not finish this. Check the item in Accounting-Ops before trying again."
    )

    async def exploding(*args, **kwargs):
        raise RuntimeError("bug")

    monkeypatch.setattr(actions, "run_action", exploding)
    assert_problem(post(client, "accounting-ops", f"ao:approval:{AO_ITEM}", "approve"), 503,
                   "action_unavailable")


@pytest.mark.asyncio
async def test_a_cookie_an_app_set_earlier_never_rides_along_on_the_write():
    seen: List[Optional[str]] = []

    async def handler(request: httpx.Request):
        seen.append(request.headers.get("cookie"))
        return httpx.Response(200, json=eo_answer("approved"))

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), cookies={"access_token": "fictional-app-cookie"}
    ) as client:
        env = AdapterEnv(
            ctx=make_ctx(), client=client, app="email-ops", label="Email-Ops",
            api_base=API_HOSTS["HOME_EMAIL_OPS_API_URL"], web_base=None, candidates=[], timeout=1.0,
        )
        call = actions.UpstreamCall("POST", EO_APPROVE, {})
        status, body, failure = await actions._write(env, call, 1.0)
    assert (status, failure) == (200, None) and body["inbox"]["state"] == "approved"
    assert seen == [None]


# --------------------------------------------------------------------------- #
# What a receipt may hold
# --------------------------------------------------------------------------- #


def _flatten(values) -> List[str]:
    out: List[str] = []
    for value in values:
        if isinstance(value, (list, tuple)):
            out.extend(_flatten(value))
        elif value is not None:
            out.append(str(value))
    return out


def test_receipt_rows_never_hold_a_token_a_body_or_an_email_address():
    routes = action_routes()
    routes[AO_DECIDE] = (409, {"detail": "Ask dana@harbormarket.example, she has the ledger"})
    mara_by_email = replace(make_ctx(), person_id="mara@rivergreen.example")
    db = ReceiptsDB()
    client, _, _ = action_client(routes, ctx=mara_by_email, db=db)
    responses = [
        post(client, "email-ops", f"eo:draft:{EO_ITEM}", "approve", key="rivergreen-action-0101"),
        post(client, "accounting-ops", f"ao:approval:{AO_ITEM}", "approve", key="rivergreen-action-0102"),
        post(client, "project-ops", f"po:task:{PO_TASK}", "done", key="rivergreen-action-0103"),
    ]
    assert [r.json()["outcome"] for r in responses] == ["done", "refused", "done"]

    written = _flatten(db.params) + _flatten(value for row in db.rows.values() for value in row.values())
    forbidden = (VALID_TOKEN, "Bearer", "@", PREVIEW, SUBJECT, "Roaster maintenance", "harbormarket")
    for value in written:
        for needle in forbidden:
            assert needle not in value, (needle, value)
    for row in db.rows.values():
        assert set(row) == ReceiptsDB.COLUMNS
        assert row["person_subject"].startswith("sha256:")
    for response in responses:
        assert VALID_TOKEN not in response.text and "dana@" not in response.text


def test_a_plain_subject_is_stored_as_is():
    assert actions.storage_subject(PERSON_SUB) == PERSON_SUB
    hashed = actions.storage_subject("mara@rivergreen.example")
    assert hashed.startswith("sha256:") and "@" not in hashed and len(hashed) == 71


# --------------------------------------------------------------------------- #
# CSRF and the session
# --------------------------------------------------------------------------- #

ACTION_PATHS = [
    f"/api/v1/home/actions/email-ops/eo:draft:{EO_ITEM}/approve",
    f"/api/v1/home/actions/accounting-ops/ao:approval:{AO_ITEM}/reject",
    f"/api/v1/home/actions/project-ops/po:triage:{PO_PROPOSAL}/accept",
    f"/api/v1/home/actions/project-ops/po:task:{PO_TASK}/done",
]


def configured_csrf_exemptions() -> set:
    """The exempt_urls set server.py passes to create_csrf_protection, read
    from the source (server.py itself is never imported in these tests)."""

    tree = ast.parse((BACKEND / "server.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "create_csrf_protection":
            for keyword in node.keywords:
                if keyword.arg == "exempt_urls":
                    return set(ast.literal_eval(keyword.value))
    raise AssertionError("create_csrf_protection(exempt_urls=...) not found in server.py")


def public_api_paths() -> set:
    """Every path in auth_middleware's public allowlist: PUBLIC_EXACT and the
    prefixes build_public_prefixes returns, read from the source."""

    tree = ast.parse((BACKEND / "auth_middleware.py").read_text(encoding="utf-8"))
    roots = [
        node for node in tree.body
        if (isinstance(node, ast.Assign) and any(getattr(t, "id", None) == "PUBLIC_EXACT" for t in node.targets))
        or (isinstance(node, ast.FunctionDef) and node.name == "build_public_prefixes")
    ]
    assert len(roots) == 2
    return {
        node.value for root in roots for node in ast.walk(root)
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value.startswith("/")
    }


def test_the_action_route_is_on_no_csrf_exemption_list_and_is_not_public():
    from csrf_protection import CSRFMiddleware, CSRFProtection

    exempt = configured_csrf_exemptions()
    assert "/api/v1/auth/login" in exempt and len(exempt) > 30  # the real list was found
    configured = CSRFMiddleware(app=None, csrf_protect=CSRFProtection(), exempt_urls=exempt)
    default = CSRFMiddleware(app=None, csrf_protect=CSRFProtection())
    for path in ACTION_PATHS:
        assert not configured.is_exempt(path), path
        assert not default.is_exempt(path), path
    assert not any(entry.startswith("/api/v1/home") for entry in exempt | default.exempt_urls)

    public = public_api_paths()
    assert "/api/v1/auth/csrf-token" in public and "/api/v1/public/" in public  # the real list was found
    for path in ACTION_PATHS:
        assert not any(path.startswith(entry) for entry in public), path


def test_the_csrf_middleware_refuses_a_cookie_post_without_its_token():
    from csrf_protection import create_csrf_protection

    sessions = {"sess-rivergreen-1": {"csrf_token": "csrf-fictional-1"}}
    _, factory = create_csrf_protection(
        enabled=True, secret_key="test-only-not-a-secret", exempt_urls=configured_csrf_exemptions(),
        sessions_store=sessions,
    )
    app, suite, db = action_app()
    app.add_middleware(factory)
    client = TestClient(app, cookies={"session_token": "sess-rivergreen-1"})

    refused = post(client, "email-ops", f"eo:draft:{EO_ITEM}", "approve")
    assert refused.status_code == 403
    assert "CSRF" in refused.json()["detail"]
    assert suite.calls == [] and db.connections == 0

    allowed = post(client, "email-ops", f"eo:draft:{EO_ITEM}", "approve", **{"X-CSRF-Token": "csrf-fictional-1"})
    assert allowed.status_code == 200 and allowed.json()["outcome"] == "done"
    assert len(writes(suite)) == 1


class OpsCenterConn:
    """Ops-Center's database for the real request binding: the role query, the
    org links and the receipt table."""

    def __init__(self, db: ReceiptsDB, role: str = "owner"):
        self.receipts = FakeReceiptConn(db)
        self.role = role
        self.queries: List[Tuple[str, Tuple[Any, ...]]] = []

    async def fetchrow(self, query, *params):
        if "organization_members" in query:
            self.queries.append(("role", params))
            return {"role": self.role}
        return await self.receipts.fetchrow(query, *params)

    async def fetch(self, query, *params):
        assert "org_app_workspaces" in query
        self.queries.append(("links", params))
        return []

    async def execute(self, query, *params):
        return await self.receipts.execute(query, *params)

    async def close(self):
        return None


def test_real_binding_uses_the_cookie_session_token_and_bearer_alone_cannot_act(monkeypatch):
    db = ReceiptsDB()
    conn = OpsCenterConn(db)
    session = {
        "user": {"sub": PERSON_SUB, "name": "Mara Okonkwo", "email": "mara@rivergreen.example"},
        "access_token": VALID_TOKEN,
        "org_id": ORG_ID,
    }
    my_apps = ModuleType("my_apps_api")
    my_apps._session_data_from_request = (  # the real one reads only the session_token cookie
        lambda request: session if request.cookies.get("session_token") == "sess-rivergreen-1" else None
    )
    my_apps._session_subject = lambda data: (data.get("user") or {}).get("sub")

    async def get_user_org_from_session(request):
        request.state.current_org_name = "Rivergreen Coffee Co."
        return ORG_ID

    async def get_db_connection():
        return conn

    my_apps.get_user_org_from_session = get_user_org_from_session
    my_apps.get_db_connection = get_db_connection
    monkeypatch.setitem(sys.modules, "my_apps_api", my_apps)

    suite = FakeSuite(action_routes())
    app = FastAPI()
    app.include_router(home_api.router)

    async def providers_with_fake_http(ctx: HomeContext = Depends(home_api.get_home_context)):
        providers = await home_api.get_action_providers(ctx)
        providers.client_factory = suite.factory
        return providers

    app.dependency_overrides[home_api.get_action_providers] = providers_with_fake_http

    bearer_only = post(TestClient(app), "project-ops", f"po:task:{PO_TASK}", "done",
                       Authorization=f"Bearer {VALID_TOKEN}")
    assert bearer_only.status_code == 401
    assert suite.calls == [] and db.rows == {}

    client = TestClient(app, cookies={"session_token": "sess-rivergreen-1"})
    response = post(client, "project-ops", f"po:task:{PO_TASK}", "done")
    assert response.status_code == 200, response.text
    assert response.json()["outcome"] == "done"
    assert all(r.headers["authorization"] == f"Bearer {VALID_TOKEN}" for r in suite.calls)
    assert all("cookie" not in r.headers for r in suite.calls)
    row = db.only_row()
    assert (row["org_id"], row["person_subject"]) == (ORG_ID, PERSON_SUB)
    assert ("links", (ORG_ID,)) in conn.queries


# --------------------------------------------------------------------------- #
# Migration
# --------------------------------------------------------------------------- #


def test_the_migration_is_idempotent_and_matches_what_the_store_writes():
    sql = (BACKEND / "migrations" / "home_action_receipts_20261109.sql").read_text(encoding="utf-8")
    code = "\n".join(line for line in sql.splitlines() if not line.strip().startswith("--"))
    creates = re.findall(r"CREATE\s+(?:UNIQUE\s+)?(?:TABLE|INDEX)\b[^;]*", code, flags=re.IGNORECASE)
    assert len(creates) == 2
    assert all("IF NOT EXISTS" in statement.upper() for statement in creates)
    assert not re.search(r"\b(DROP|DELETE|TRUNCATE|ALTER)\b", code, flags=re.IGNORECASE)

    table = re.search(r"CREATE TABLE IF NOT EXISTS home_action_receipts \((.*?)\n\);", code, flags=re.S).group(1)
    columns = {
        line.split()[0] for line in table.splitlines()
        if line.strip() and not line.strip().upper().startswith(("CONSTRAINT", "CHECK"))
    }
    assert columns == ReceiptsDB.COLUMNS
    assert not any(word in column for column in columns for word in ("token", "body", "email"))
    assert "CHECK (outcome IS NULL OR outcome IN ('done', 'refused', 'reauth', 'failed'))" in code
    assert re.search(r"ON home_action_receipts \(org_id, person_subject, idempotency_key\)", code)
    for statement in (actions.RESERVE_SQL, actions.FIND_SQL, actions.COMPLETE_SQL):
        assert "home_action_receipts" in statement
        named = set(re.findall(r"\b([a-z_]+)\b", statement)) & (ReceiptsDB.COLUMNS | {"token", "body", "email"})
        assert named <= ReceiptsDB.COLUMNS, named
    assert "ON CONFLICT (org_id, person_subject, idempotency_key)" in actions.RESERVE_SQL
