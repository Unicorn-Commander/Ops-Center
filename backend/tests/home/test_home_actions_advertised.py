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
from typing import Any, Dict

import pytest

from home.aggregator import build_home_state
from home.markdown import render_markdown
from homekit import FIXTURES, ORG_ID, FakeSuite, load, make_ctx, make_providers, suite_routes
from test_home_actions import AO_ITEM, EO_ITEM, PO_PROPOSAL, PO_TASK

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
