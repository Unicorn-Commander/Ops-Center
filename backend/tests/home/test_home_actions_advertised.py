"""Home actions offered on the items of the state document (lane H1d).

With ``HOME_ACTIONS_ENABLED`` off the state document must stay exactly what it
was before the home offered actions: ``fixtures/golden_state_actions_off.json``
and ``fixtures/golden_state_actions_off.md`` were generated from Ops-Center
main 8186405f by ``state_document`` below, with the build times frozen, and
are compared byte for byte. Regenerate them only on purpose.

The suite is H1's fixtures with UUID item ids (every app's ids are UUIDs, and
the action route accepts nothing else), plus rows an app is known to refuse an
action on. Rivergreen Coffee Co., Harbor Market and every id, host and address
here are fictional.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import home_api
from home import actions
from home.aggregator import build_home_state
from home.markdown import render_markdown
from homekit import (
    FIXTURES,
    NOW,
    ORG_ID,
    FakeSuite,
    load,
    make_ctx,
    make_providers,
    module_by_id,
    suite_routes,
)
from test_home_actions import AO_ITEM, EO_ITEM, PO_PROPOSAL, PO_TASK, ReceiptsDB, action_routes, writes
from test_home_actions import make_providers as action_providers

GOLDEN_JSON = FIXTURES / "golden_state_actions_off.json"
GOLDEN_MD = FIXTURES / "golden_state_actions_off.md"

# Rows an app is known to refuse an action on, or where the action would not
# do what its label says.
EO_SCHEDULED = "6a1d2e3f-4b5c-4d6e-8f70-1a2b3c4d5e01"  # a draft with a send time tomorrow
EO_CLEANUP = "6a1d2e3f-4b5c-4d6e-8f70-1a2b3c4d5e02"  # a cleanup request, not a draft
AO_JOURNAL = "6a1d2e3f-4b5c-4d6e-8f70-1a2b3c4d5e03"  # a journal proposal
PO_NO_PROJECT = "6a1d2e3f-4b5c-4d6e-8f70-1a2b3c4d5e04"  # a proposal with no project
PO_BLOCKED = "6a1d2e3f-4b5c-4d6e-8f70-1a2b3c4d5e05"  # a task due today with an open blocker

TASK_IDS = {
    "task-roaster-maint": PO_TASK,
    "task-price-sheet": PO_BLOCKED,
    "task-late-call": "6a1d2e3f-4b5c-4d6e-8f70-1a2b3c4d5e11",
    "task-overdue-labels": "6a1d2e3f-4b5c-4d6e-8f70-1a2b3c4d5e12",
    "task-tomorrow": "6a1d2e3f-4b5c-4d6e-8f70-1a2b3c4d5e13",
    "task-done": "6a1d2e3f-4b5c-4d6e-8f70-1a2b3c4d5e14",
    "task-done-old": "6a1d2e3f-4b5c-4d6e-8f70-1a2b3c4d5e15",
    "task-cancelled-today": "6a1d2e3f-4b5c-4d6e-8f70-1a2b3c4d5e16",
    "task-no-due": "6a1d2e3f-4b5c-4d6e-8f70-1a2b3c4d5e17",
}

ISO = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})$")
FROZEN = "2026-11-09T15:00:00Z"
BUILD_TIME_KEYS = ("as_of", "generated_at")


def actionable_routes() -> Dict[str, Any]:
    """H1's suite with UUID item ids and one row of each refused kind."""

    routes = suite_routes()

    inbox = load("eo_agent_inbox")
    inbox["items"][0].update(id=EO_ITEM, kind="EMAIL")
    inbox["items"][1].update(id=EO_SCHEDULED, kind="EMAIL", sends_at="2026-11-10T14:00:00.000Z")
    inbox["items"].append({
        "id": EO_CLEANUP, "message_id": None, "kind": "CLEANUP", "approval_tier": "mailbox_owner",
        "approval_reason": None, "state": "pending", "drafted_by": "Email-Ops cleaner",
        "summary": "Move 14 promotional threads to Trash.", "to_address": None, "to_addresses": [],
        "cc": [], "bcc": [], "from_address": None, "subject": "Clean up 14 promotional threads",
        "body_preview": "14 threads from a coffee supplier's mailing list.", "body_sha256": None,
        "thread_id": None, "kit_id": None, "attachments": [], "sends_at": None,
        "reviewed_by_uc_uid": None, "reviewed_at": None, "review_note": None,
        "created_at": "2026-11-08T20:00:00.000Z", "payload": {"action": "TRASH"},
    })
    inbox["count"] = 4
    routes[f"/api/v1/workspaces/{ORG_ID}/agent-inbox"] = inbox

    approvals = load("ao_approvals")
    approvals["approvals"][0]["id"] = AO_ITEM
    approvals["approvals"].append({
        "id": AO_JOURNAL, "entity_id": "ent-1", "entity_display_name": "Rivergreen Coffee Co.",
        "entity_slug": "rivergreen", "subject_type": "journal_entry_post", "subject_id": AO_JOURNAL,
        "amount": 412.0, "currency_code": "USD", "status": "pending",
        "reasoning": "Deposit from Harbor Market matches invoice INV-0042.",
        "requested_by_identity": "agent:bookkeeper", "decided_by_uc_uid": None, "decided_at": None,
        "created_at": "2026-11-08T19:30:00+00:00", "payload": {"source": "bank_feed"},
    })
    approvals["total"] = 2
    routes[f"/api/workspaces/{ORG_ID}/approvals"] = approvals

    triage = load("po_triage")
    triage[0]["id"] = PO_PROPOSAL
    triage[1]["id"] = PO_NO_PROJECT
    assert triage[1]["proposedProjectId"] is None and triage[1]["proposedProject"] is None
    routes["/api/v1/triage/proposals"] = triage

    tasks = load("po_my_tasks")
    for task in tasks:
        task["id"] = TASK_IDS[task["id"]]
        task["isBlocked"] = task["id"] == PO_BLOCKED
    routes["/api/v1/tasks/my-tasks"] = tasks
    return routes


async def state_document(**ctx_kwargs: Any) -> Dict[str, Any]:
    suite = FakeSuite(actionable_routes())
    return await build_home_state(make_ctx(**ctx_kwargs), make_providers(suite))


def frozen(node: Any) -> Any:
    """The document with every build time set to FROZEN (each one checked to be
    a build time first), so two builds can be compared byte for byte."""

    if isinstance(node, dict):
        out = {}
        for key, value in node.items():
            if key in BUILD_TIME_KEYS:
                assert isinstance(value, str) and ISO.match(value), (key, value)
                out[key] = FROZEN
            else:
                out[key] = frozen(value)
        return out
    if isinstance(node, list):
        return [frozen(value) for value in node]
    return node


def as_text(document: Dict[str, Any]) -> str:
    """The JSON text, keys in the order the route sends them."""

    return json.dumps(document, indent=2, ensure_ascii=False) + "\n"


def items_by_key(document: Dict[str, Any]) -> Dict[Tuple[str, str], Dict[str, Any]]:
    return {
        (module["id"], item["id"]): item
        for module in document["modules"] for item in module.get("items") or [] if "id" in item
    }


def offers_in(document: Dict[str, Any]) -> List[Tuple[str, Dict[str, Any], Dict[str, Any]]]:
    """(module id, item, action) for every offered action (the ones with a method)."""

    return [
        (module["id"], item, action)
        for module in document["modules"] for item in module.get("items") or []
        for action in item.get("actions") or [] if "method" in action
    ]


def without_offers(node: Any) -> Any:
    """The document with every offered action taken out of every actions list."""

    if isinstance(node, dict):
        return {
            key: [without_offers(a) for a in value if not (isinstance(a, dict) and "method" in a)]
            if key == "actions" and isinstance(value, list) else without_offers(value)
            for key, value in node.items()
        }
    if isinstance(node, list):
        return [without_offers(value) for value in node]
    return node


# --------------------------------------------------------------------------- #
# The flag off: nothing changes
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
@pytest.mark.parametrize("flag", [None, "false", "0", "off", ""])
async def test_with_actions_off_the_state_document_is_byte_for_byte_what_it_was(monkeypatch, flag):
    if flag is None:
        monkeypatch.delenv("HOME_ACTIONS_ENABLED", raising=False)
    else:
        monkeypatch.setenv("HOME_ACTIONS_ENABLED", flag)
    document = frozen(await state_document())
    assert as_text(document) == GOLDEN_JSON.read_text(encoding="utf-8")
    assert render_markdown(document) == GOLDEN_MD.read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# The flag on: what is offered, and how
# --------------------------------------------------------------------------- #

ITEM_UUID = "0f1e2d3c-4b5a-4968-8776-655443322110"

# The brief's labels, per (source, kind of the item id), in table order.
LABELS = {
    ("email-ops", "draft"): [("approve", "Approve", "Sends the email now"), ("reject", "Reject", None)],
    ("accounting-ops", "approval"): [("approve", "Approve", None), ("reject", "Reject", None)],
    ("project-ops", "triage"): [("accept", "Accept", None), ("reject", "Reject", None)],
    ("project-ops", "task"): [("done", "Mark done", None)],
}


# A normalized row of each kind on which nothing is withheld.
PLAIN_ROWS = {
    ("email-ops", "draft"): {"kind": "EMAIL", "sends_at": None},
    ("accounting-ops", "approval"): {"subject_type": "bank_transaction_import"},
    ("project-ops", "triage"): {"project_id": "6a1d2e3f-4b5c-4d6e-8f70-1a2b3c4d5e21"},
    ("project-ops", "task"): {"blocked": False},
}


def offer(source: str, item_id: str, action: str, label: str, note: str = "") -> Dict[str, Any]:
    entry = {"id": action, "label": label, "method": "POST",
             "href": f"/api/v1/home/actions/{source}/{item_id}/{action}"}
    if note:
        entry["note"] = note
    return entry


# What the suite's plain rows carry after Open, keyed by (module, item id).
OFFERED = {
    ("needs_you", f"eo:draft:{EO_ITEM}"): [
        offer("email-ops", f"eo:draft:{EO_ITEM}", "approve", "Approve", "Sends the email now"),
        offer("email-ops", f"eo:draft:{EO_ITEM}", "reject", "Reject"),
    ],
    ("needs_you", f"ao:approval:{AO_ITEM}"): [
        offer("accounting-ops", f"ao:approval:{AO_ITEM}", "approve", "Approve"),
        offer("accounting-ops", f"ao:approval:{AO_ITEM}", "reject", "Reject"),
    ],
    ("needs_you", f"po:triage:{PO_PROPOSAL}"): [
        offer("project-ops", f"po:triage:{PO_PROPOSAL}", "accept", "Accept"),
        offer("project-ops", f"po:triage:{PO_PROPOSAL}", "reject", "Reject"),
    ],
    ("today", f"po:task:{PO_TASK}"): [
        offer("project-ops", f"po:task:{PO_TASK}", "done", "Mark done"),
    ],
}


def test_the_label_table_covers_every_action_the_route_takes():
    assert set(LABELS) == {(spec.source, spec.kind) for spec in actions.ACTIONS}
    for spec in actions.ACTIONS:
        assert spec.label, spec  # no action is offered without a label
        assert "\u2014" not in spec.label + (spec.note or "")


@pytest.mark.parametrize("source, kind", sorted(LABELS))
def test_offered_actions_are_the_specs_in_table_order_with_their_labels(source, kind):
    item_id = f"{actions.SOURCE_CODES[source]}:{kind}:{ITEM_UUID}"
    offered = actions.offered_actions(item_id, PLAIN_ROWS[(source, kind)], NOW)
    # Derived from SPECS: the same actions in the same order, no second copy.
    assert [o["id"] for o in offered] == [
        spec.action for spec in actions.ACTIONS if (spec.source, spec.kind) == (source, kind)
    ]
    assert [(o["id"], o["label"], o.get("note")) for o in offered] == LABELS[(source, kind)]
    for entry in offered:
        assert set(entry) <= {"id", "label", "method", "href", "note"}
        assert entry["method"] == "POST"
        assert entry["href"] == f"/api/v1/home/actions/{source}/{item_id}/{entry['id']}"
        # The route's own parser takes the href back to this very spec.
        prefix, href_source, href_item, href_action = entry["href"].rsplit("/", 3)
        target, refusal = actions.resolve_target(href_source, href_item, href_action)
        assert prefix == "/api/v1/home/actions" and refusal is None
        assert target.spec is actions.SPECS[(source, kind, entry["id"])]


def test_an_offered_href_uses_the_routes_own_form_of_the_id():
    upper = ITEM_UUID.upper()
    offered = actions.offered_actions(f"po:task:{upper}", PLAIN_ROWS[("project-ops", "task")], NOW)
    assert [o["href"] for o in offered] == [f"/api/v1/home/actions/project-ops/po:task:{ITEM_UUID}/done"]


@pytest.mark.parametrize(
    "item_id",
    ["eo:draft:eo-item-1", "eo:draft", f"eo:draft:{ITEM_UUID}:extra", f"mo:session:{ITEM_UUID}",
     f"co:followup:{ITEM_UUID}", f"po:proposal:{ITEM_UUID}", f"ao:priority:{ITEM_UUID}",
     f"cdr:notification:{ITEM_UUID}", "", None],
)
def test_an_id_the_route_would_refuse_is_offered_nothing(item_id):
    assert actions.offered_actions(item_id, {"kind": "EMAIL", "project_id": "p", "blocked": False}, NOW) == []


@pytest.mark.asyncio
async def test_with_actions_on_each_item_carries_its_actions_after_open(monkeypatch):
    monkeypatch.delenv("HOME_ACTIONS_ENABLED", raising=False)
    off = items_by_key(await state_document())
    monkeypatch.setenv("HOME_ACTIONS_ENABLED", "true")
    on = items_by_key(await state_document())
    for key, expected in OFFERED.items():
        before = off[key]["actions"]
        assert [a["id"] for a in before] == ["open"], key
        assert on[key]["actions"] == before + expected, key


@pytest.mark.asyncio
async def test_with_actions_on_the_document_only_gains_the_offered_actions(monkeypatch):
    monkeypatch.setenv("HOME_ACTIONS_ENABLED", "true")
    document = frozen(await state_document())
    offers = offers_in(document)
    assert len(offers) >= sum(len(expected) for expected in OFFERED.values())
    assert {module_id for module_id, _, _ in offers} == {"needs_you", "today"}
    # Take the offers out again and it is the flag-off document, byte for byte.
    assert as_text(without_offers(document)) == GOLDEN_JSON.read_text(encoding="utf-8")
    for module in document["modules"]:
        for item in module.get("items") or []:
            ids = [a["id"] for a in item.get("actions") or []]
            if "open" in ids:
                assert ids[0] == "open", item["id"]  # Open stays first


@pytest.mark.asyncio
async def test_closed_tasks_since_the_last_visit_are_offered_nothing(monkeypatch):
    monkeypatch.setenv("HOME_ACTIONS_ENABLED", "true")
    since = module_by_id(await state_document(), "since_last_visit")
    closed = [item for item in since["items"] if item["id"].startswith("po:task:")]
    assert closed and all("actions" not in item for item in closed)


# --------------------------------------------------------------------------- #
# Accounting-Ops journal proposals: Open only
# --------------------------------------------------------------------------- #


def test_accounting_ops_journal_proposals_withhold_both_decisions():
    # ebd7796 app/api/approvals.py:254-264 refuses approve and reject on a
    # journal_entry_post unless the token was issued to Accounting-Ops' own client.
    journal = {"subject_type": "journal_entry_post"}
    assert actions.withheld_actions("accounting-ops", "approval", journal, NOW) == {"approve", "reject"}
    assert actions.offered_actions(f"ao:approval:{ITEM_UUID}", journal, NOW) == []
    for subject in ("bank_transaction_import", "journal_recategorization", "compliance_rule", "", None):
        offered = actions.offered_actions(f"ao:approval:{ITEM_UUID}", {"subject_type": subject}, NOW)
        assert [o["id"] for o in offered] == ["approve", "reject"], subject


@pytest.mark.asyncio
async def test_a_journal_proposal_in_needs_you_keeps_open_only(monkeypatch):
    monkeypatch.setenv("HOME_ACTIONS_ENABLED", "true")
    items = items_by_key(await state_document())
    journal = items[("needs_you", f"ao:approval:{AO_JOURNAL}")]
    assert journal["title"] == "Approve journal entry post of 412.00 USD for Rivergreen Coffee Co."
    assert journal["actions"] == [{"id": "open", "label": "Open", "href": "https://ledger.example.com/approvals"}]
    assert [a["id"] for a in items[("needs_you", f"ao:approval:{AO_ITEM}")]["actions"]] == [
        "open", "approve", "reject",
    ]


# --------------------------------------------------------------------------- #
# Rows an app would refuse, or where the label would not be true
# --------------------------------------------------------------------------- #

LATER = datetime(2026, 11, 10, 14, 0, tzinfo=timezone.utc)  # NOW is 2026-11-09 15:00 UTC
EARLIER = datetime(2026, 11, 9, 14, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    "source, kind, row, offered",
    [
        # Email-Ops 2810e17: only EMAIL rows are drafts (unset means EMAIL there).
        ("email-ops", "draft", {"kind": "EMAIL"}, ["approve", "reject"]),
        ("email-ops", "draft", {"kind": None}, ["approve", "reject"]),
        ("email-ops", "draft", {"kind": "email"}, ["approve", "reject"]),
        ("email-ops", "draft", {"kind": "CLEANUP"}, []),  # approve would trash or archive mail
        ("email-ops", "draft", {"kind": "NOTICE"}, []),  # approve would add a calendar event
        # Approve leaves a draft with a send time still ahead as it is.
        ("email-ops", "draft", {"kind": "EMAIL", "sends_at": LATER}, ["reject"]),
        ("email-ops", "draft", {"kind": "EMAIL", "sends_at": EARLIER}, ["approve", "reject"]),
        ("email-ops", "draft", {"kind": "EMAIL", "sends_at": "2026-11-10T14:00:00Z"}, ["reject"]),
        ("email-ops", "draft", {"kind": "EMAIL", "sends_at": "not a time"}, ["approve", "reject"]),
        # Accounting-Ops ebd7796: journal proposals need its own client's token.
        ("accounting-ops", "approval", {"subject_type": "journal_entry_post"}, []),
        ("accounting-ops", "approval", {"subject_type": "bank_transaction_import"}, ["approve", "reject"]),
        # Project-Ops ffc5bd5: accept needs a project; done is refused with a blocker open.
        ("project-ops", "triage", {"project_id": "6a1d2e3f-4b5c-4d6e-8f70-1a2b3c4d5e21"}, ["accept", "reject"]),
        ("project-ops", "triage", {"project_id": None}, ["reject"]),
        ("project-ops", "triage", {}, ["reject"]),
        ("project-ops", "task", {"blocked": False}, ["done"]),
        ("project-ops", "task", {"blocked": True}, []),
    ],
)
def test_an_action_the_app_would_refuse_for_the_row_is_not_offered(source, kind, row, offered):
    item_id = f"{actions.SOURCE_CODES[source]}:{kind}:{ITEM_UUID}"
    assert [o["id"] for o in actions.offered_actions(item_id, row, NOW)] == offered


@pytest.mark.asyncio
async def test_in_the_document_such_rows_keep_what_works(monkeypatch):
    monkeypatch.setenv("HOME_ACTIONS_ENABLED", "true")
    document = await state_document()
    items = items_by_key(document)

    def ids(module_id: str, item_id: str) -> List[str]:
        return [action["id"] for action in items[(module_id, item_id)]["actions"]]

    assert ids("needs_you", f"eo:draft:{EO_CLEANUP}") == ["open"]
    assert ids("needs_you", f"eo:draft:{EO_SCHEDULED}") == ["open", "reject"]
    assert ids("needs_you", f"ao:approval:{AO_JOURNAL}") == ["open"]
    assert ids("needs_you", f"po:triage:{PO_NO_PROJECT}") == ["open", "reject"]
    assert ids("today", f"po:task:{PO_BLOCKED}") == ["open"]
    # "Sends the email now" is only on a draft that approve would send now.
    assert [item["id"] for _, item, action in offers_in(document) if action.get("note")] == [
        f"eo:draft:{EO_ITEM}"
    ]


# --------------------------------------------------------------------------- #
# Round trip: an href from the state document, POSTed through the real route
# --------------------------------------------------------------------------- #


def round_trip_client(suite: FakeSuite, db: ReceiptsDB) -> TestClient:
    """Both real routes on a bare app, reading and writing the same fake apps."""

    app = FastAPI()
    app.include_router(home_api.router)
    app.dependency_overrides[home_api.get_home_context] = lambda: make_ctx()
    app.dependency_overrides[home_api.get_home_providers] = lambda: make_providers(suite)
    app.dependency_overrides[home_api.get_action_providers] = lambda: action_providers(suite, db)
    return TestClient(app)


def test_every_offered_href_round_trips_through_the_real_action_route(monkeypatch):
    monkeypatch.setenv("HOME_STATE_ENABLED", "true")
    monkeypatch.setenv("HOME_ACTIONS_ENABLED", "true")
    # The state reads, plus H1b's membership reads and write answers for the
    # same four item ids.
    suite = FakeSuite({**action_routes(), **actionable_routes()})
    db = ReceiptsDB()
    client = round_trip_client(suite, db)

    state = client.get("/api/v1/home/state")
    assert state.status_code == 200, state.text
    offers = offers_in(state.json())
    assert {(item["id"], action["id"]) for _, item, action in offers} >= {
        (item_id, entry["id"]) for (_, item_id), expected in OFFERED.items() for entry in expected
    }

    for number, (_, item, action) in enumerate(offers):
        written = len(writes(suite))
        response = client.request(
            action["method"], action["href"], headers={"Idempotency-Key": f"round-trip-{number:04d}"}
        )
        assert response.status_code == 200, (action["href"], response.text)
        receipt = response.json()
        assert receipt["schema"] == "uc.home.action_receipt/1" and receipt["replayed"] is False
        assert (receipt["source"], receipt["item_id"], receipt["action"]) == (item["app"], item["id"], action["id"])
        assert receipt["outcome"] in actions.OUTCOMES
        if (item["id"], action["id"]) in {(i, e["id"]) for (_, i), x in OFFERED.items() for e in x}:
            assert receipt["outcome"] == "done", receipt
            assert len(writes(suite)) == written + 1
    assert len(db.rows) == len(offers)
