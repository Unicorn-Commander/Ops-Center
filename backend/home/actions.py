"""Act on a home item: ``POST /api/v1/home/actions/{source}/{item_id}/{action}``.

The person approves, rejects, accepts or marks done an item the home showed
them. Ops-Center forwards that one action, server side, to the EXISTING route of
the app that owns the item, with the person's own access token (the same token,
hosts and workspace rule as the read-only home state), and keeps a receipt.

``item_id`` is the id the home-state document gave the item:

* email-ops ``eo:draft:<uuid>``: approve, reject (POST agent-inbox/{id}/approve or /reject)
* accounting-ops ``ao:approval:<uuid>``: approve, reject (POST approvals/{id}/decide)
* project-ops ``po:triage:<uuid>``: accept, reject (POST triage/proposals/{id}/approve or /reject)
* project-ops ``po:task:<uuid>``: done (PATCH tasks/{id}/status with COMPLETED)

Rules:

* The workspace is never taken from the caller. It is chosen exactly as the
  home state chooses it (``mapping.workspace_candidates``: the org id, then
  ``org_app_workspaces``) and confirmed with the app's own membership read
  before anything is written. Item ids must be UUIDs (every app's ids are).
* The token goes only to the configured app base (``settings.api_base_url``),
  as ``Authorization: Bearer``. No cookie is ever sent and redirects are never
  followed. Nothing here logs a token, an item title or a body.
* Idempotency: an ``Idempotency-Key`` header is required. The receipt row is
  reserved before the app is called, so the same key for the same person in
  the same org reaches the app at most once; a repeat returns the stored
  receipt. Reusing a key for another action is 422; a repeat while the first
  is still running is 409; a reservation that never finished is closed as
  failed after ``STALE_RESERVATION_SECONDS`` and never retried.
* Outcomes: 2xx is ``done``; 401 is ``reauth``; 403 and 404 are ``refused``;
  409 and 422 are ``refused`` with the app's own short reason when it is safe
  text; anything else, or no answer, is ``failed``. The person always gets a
  receipt or a problem document, never a 500.
* One exception to "2xx is done", for honesty: Email-Ops answers 200 without
  acting when the draft was already decided or already has a send time
  (``email.service.ts:3859-3870,3950-3958``). The answer's ``inbox.state`` is
  read (and nothing else kept) and such a receipt says ``refused``.
* A receipt stores no token, no request or response body and no email address.

The state document offers these actions on its items when
``HOME_ACTIONS_ENABLED`` is on (``offered_actions``, called by ``modules``):
each item carries the SPECS entries for its source and kind, after its Open
action, less any the owning app is known to refuse for that row
(``withheld_actions``).
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Awaitable, Callable, Dict, FrozenSet, List, Mapping, Optional, Tuple

import httpx

from . import settings
from .adapters import accounting_ops, email_ops, project_ops
from .adapters.base import (
    TIMEOUT,
    AdapterEnv,
    Forbidden,
    Reauth,
    UpstreamError,
    get_json,
    iso,
    link_note,
    member_ids,
    parse_iso,
    path_segment,
)
from .context import ClientFactory, HomeContext, WorkspaceRowsProvider, default_client_factory, token_expired
from .mapping import choose_workspace, workspace_candidates
from .safety import guard_document

logger = logging.getLogger("home.actions")

RECEIPT_SCHEMA = "uc.home.action_receipt/1"

OUTCOME_DONE = "done"
OUTCOME_REFUSED = "refused"
OUTCOME_REAUTH = "reauth"
OUTCOME_FAILED = "failed"
OUTCOMES = (OUTCOME_DONE, OUTCOME_REFUSED, OUTCOME_REAUTH, OUTCOME_FAILED)

REAUTH_MESSAGE = "Sign in again to finish this."

# A reservation still open after this long belongs to a request that died
# between calling the app and writing its receipt (the slowest action is one
# membership read plus one write, well under a minute).
STALE_RESERVATION_SECONDS = 120

IDEMPOTENCY_KEY_MIN = 8
IDEMPOTENCY_KEY_MAX = 200
_KEY_CHARS = re.compile(r"^[\x21\x23-\x7e]+$")  # visible ASCII, no double quote

# An app's own reason is shown only when it is short, plain text.
REASON_MAX = 160
_REASON_CHARS = re.compile(r"^[A-Za-z0-9 .,;:'()/%&+#_?-]+$")


# --------------------------------------------------------------------------- #
# The upstream calls
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class UpstreamCall:
    method: str
    path: str
    body: Dict[str, Any]
    headers: Dict[str, str] = field(default_factory=dict)


DoneReader = Callable[[Any, datetime], Tuple[str, str]]


@dataclass(frozen=True)
class ActionSpec:
    source: str
    code: str
    kind: str
    action: str
    request: Callable[[str, str], UpstreamCall]  # (workspace_id, item uuid) -> call
    done: DoneReader  # (2xx body or None, now) -> (outcome, message)
    # Upstream answers that mean "already handled" for this action, not a failure.
    already_handled: Tuple[int, ...] = ()
    # How the home offers it on an item (``offered_actions``): the button label
    # and, where the person should know something before the tap, a short note.
    label: str = ""
    note: Optional[str] = None


def _constant(message: str) -> DoneReader:
    return lambda body, now: (OUTCOME_DONE, message)


# Email-Ops 2810e17. Global prefix api/v1 (backend/src/main.ts:64-65). The
# controller is workspaces/:workspaceId/agent-inbox under the JWT and workspace
# membership guards (backend/src/agent-inbox/agent-inbox.controller.ts:181-182);
# approve is :423-490 and reject :492-518, each taking ReviewBodyDto (:66-79:
# only note and trustRecipients, unknown keys are refused). Email-Ops' own page
# sends {} when there is no note (frontend/lib/api.ts:543-559,580-592). The
# home never sends trustRecipients, so an approve never trusts the recipients
# (backend/src/email/email.service.ts:4282). An approve SENDS at once: the
# draft goes to the mail engine inside the request (email.service.ts:4273-4275)
# and the item becomes approved only if the engine accepted it (:4295-4310).
def _email_ops_call(verb: str) -> Callable[[str, str], UpstreamCall]:
    def build(workspace_id: str, item: str) -> UpstreamCall:
        path = f"/api/v1/workspaces/{path_segment(workspace_id)}/agent-inbox/{item}/{verb}"
        return UpstreamCall("POST", path, {})

    return build


def _email_ops_done(action: str) -> DoneReader:
    """Read only ``inbox.state``, ``inbox.sends_at`` and whether a mail message
    came back. Email-Ops answers 200 and changes nothing when the draft was
    already decided (email.service.ts:3859-3870, :4380) or already has a send
    time (:3950-3958); those receipts say refused."""

    expected = "approved" if action == "approve" else "rejected"

    def read(body: Any, now: datetime) -> Tuple[str, str]:
        inbox = body.get("inbox") if isinstance(body, dict) else None
        inbox = inbox if isinstance(inbox, dict) else {}
        state = str(inbox.get("state") or "").strip().lower()
        is_mail = isinstance(body, dict) and isinstance(body.get("message"), dict)
        if state and state != expected:
            if state in ("approved", "rejected"):
                return OUTCOME_REFUSED, f"This draft was already {state} in Email-Ops, so nothing changed."
            if action == "approve" and state == "pending":
                return OUTCOME_REFUSED, "Email-Ops already has a send time for this draft, so nothing changed."
            return OUTCOME_REFUSED, "Email-Ops did not change this draft."
        if action == "reject":
            return OUTCOME_DONE, "Rejected. Email-Ops will not send it." if is_mail else "Rejected in Email-Ops."
        sends_at = parse_iso(inbox.get("sends_at"))
        if is_mail and sends_at is not None and sends_at > now:
            return OUTCOME_DONE, "Approved. Email-Ops will send it at its scheduled time."
        if is_mail:
            return OUTCOME_DONE, "Approved. Email-Ops handed it to the mail server."
        return OUTCOME_DONE, "Approved in Email-Ops."

    return read


# Accounting-Ops ebd7796. POST /api/workspaces/{ws}/approvals/{id}/decide
# (app/api/approvals.py:181-213; DecideRequest :161-167 is decision, note and
# category_override). Floor is accountant (:206). An approve applies the held
# action in one transaction; a decided approval answers 409 "Approval already
# <status>" (:241-245). Its own page sends {"decision": ...} only
# (web/components/approval-actions.tsx:40-46).
def _accounting_ops_call(decision: str) -> Callable[[str, str], UpstreamCall]:
    def build(workspace_id: str, item: str) -> UpstreamCall:
        path = f"/api/workspaces/{path_segment(workspace_id)}/approvals/{item}/decide"
        return UpstreamCall("POST", path, {"decision": decision})

    return build


# Project-Ops ffc5bd5. Global prefix api/v1 (backend/src/main.ts:55-56); the
# workspace is the X-Workspace-Id header, honoured only after the membership
# guard checks it (common/workspace/workspace-membership.guard.ts:21,
# current-workspace.decorator.ts). Ruling a proposal: POST
# triage/proposals/:id/approve (backend/src/triage/triage.controller.ts:106-117,
# ApproveTriageProposalDto dto/triage-proposals.dto.ts:126-131, all optional)
# and POST triage/proposals/:id/reject (:119-130, RejectTriageProposalDto
# :133-153, all optional); roles ADMIN, MANAGER, STAFF. Its own page sends {}
# (frontend/lib/triage-api.ts:104-121).
def _project_ops_triage_call(verb: str) -> Callable[[str, str], UpstreamCall]:
    def build(workspace_id: str, item: str) -> UpstreamCall:
        return UpstreamCall(
            "POST", f"/api/v1/triage/proposals/{item}/{verb}", {}, {"X-Workspace-Id": workspace_id}
        )

    return build


# Project-Ops ffc5bd5. PATCH tasks/:id/status (backend/src/tasks/tasks.controller.ts:154-173,
# UpdateTaskStatusDto dto/update-task-status.dto.ts:5-28). force is never sent, so
# open dependency blockers answer 409 (tasks.service.ts:157-171). Its own page sends
# {status} only (frontend/lib/tasks-api.ts:268-272).
def _project_ops_task_done(workspace_id: str, item: str) -> UpstreamCall:
    return UpstreamCall(
        "PATCH", f"/api/v1/tasks/{item}/status", {"status": "COMPLETED"}, {"X-Workspace-Id": workspace_id}
    )


ACTIONS: Tuple[ActionSpec, ...] = (
    ActionSpec(
        "email-ops", "eo", "draft", "approve", _email_ops_call("approve"), _email_ops_done("approve"),
        # A single approve sends inside the request: there is no hold window
        # (email.service.ts:4273-4310).
        label="Approve", note="Sends the email now",
    ),
    ActionSpec(
        "email-ops", "eo", "draft", "reject", _email_ops_call("reject"), _email_ops_done("reject"),
        label="Reject",
    ),
    ActionSpec(
        "accounting-ops", "ao", "approval", "approve", _accounting_ops_call("approve"),
        _constant("Approved. Accounting-Ops applied it."), label="Approve",
    ),
    ActionSpec(
        "accounting-ops", "ao", "approval", "reject", _accounting_ops_call("reject"),
        _constant("Rejected. Accounting-Ops left the books as they were."), label="Reject",
    ),
    ActionSpec(
        "project-ops", "po", "triage", "accept", _project_ops_triage_call("approve"),
        _constant("Accepted. Project-Ops created the task."),
        # Project-Ops answers 400 when the proposal was already ruled or has no
        # project (ffc5bd5 backend/src/triage/triage.service.ts:739-743).
        already_handled=(400,), label="Accept",
    ),
    ActionSpec(
        "project-ops", "po", "triage", "reject", _project_ops_triage_call("reject"),
        _constant("Rejected. Project-Ops did not create a task."),
        # Project-Ops answers 400 when the proposal was already ruled or has no
        # project (ffc5bd5 backend/src/triage/triage.service.ts:739-743).
        already_handled=(400,), label="Reject",
    ),
    ActionSpec(
        "project-ops", "po", "task", "done", _project_ops_task_done,
        _constant("Marked done in Project-Ops."), label="Mark done",
    ),
)

SPECS: Dict[Tuple[str, str, str], ActionSpec] = {(s.source, s.kind, s.action): s for s in ACTIONS}
SOURCE_CODES = {s.source: s.code for s in ACTIONS}
ITEM_NAMES = {
    ("email-ops", "draft"): "An Email-Ops draft",
    ("accounting-ops", "approval"): "An Accounting-Ops approval",
    ("project-ops", "triage"): "A Project-Ops triage proposal",
    ("project-ops", "task"): "A Project-Ops task",
}


def allowed_actions() -> List[Dict[str, Any]]:
    """The whole table, for problem documents and agents."""

    rows: List[Dict[str, Any]] = []
    for spec in ACTIONS:
        item = f"{spec.code}:{spec.kind}:<uuid>"
        row = next((r for r in rows if r["source"] == spec.source and r["item_id"] == item), None)
        if row is None:
            row = {"source": spec.source, "item_id": item, "actions": []}
            rows.append(row)
        row["actions"].append(spec.action)
    return rows


# --------------------------------------------------------------------------- #
# Workspace: the same candidates as the home state, confirmed by the app
# --------------------------------------------------------------------------- #


async def _email_ops_workspace(env: AdapterEnv) -> Optional[str]:
    """The caller's Email-Ops workspaces (``adapters/email_ops.py``)."""

    listing = await get_json(env, email_ops.WORKSPACES_ROUTE)
    rows = listing.get("workspaces") if isinstance(listing, dict) else None
    chosen = choose_workspace(env.candidates, member_ids(rows or [], "workspace_id"))
    return chosen.workspace_id if chosen else None


async def _accounting_ops_workspace(env: AdapterEnv) -> Optional[str]:
    """Accounting-Ops' per-candidate membership probe (``adapters/accounting_ops.py``)."""

    found = await accounting_ops._find_workspace(env)  # noqa: SLF001 - the adapter's own probe
    return found[0].workspace_id if found else None


async def _project_ops_workspace(env: AdapterEnv) -> Optional[str]:
    """The workspaces on the caller's Project-Ops profile (``adapters/project_ops.py``)."""

    profile = await project_ops.get_profile(env)
    workspaces = profile.get("workspaces") if isinstance(profile.get("workspaces"), list) else []
    chosen = choose_workspace(env.candidates, member_ids(workspaces, "workspaceId"))
    return chosen.workspace_id if chosen else None


WORKSPACE_FINDERS: Dict[str, Callable[[AdapterEnv], Awaitable[Optional[str]]]] = {
    "email-ops": _email_ops_workspace,
    "accounting-ops": _accounting_ops_workspace,
    "project-ops": _project_ops_workspace,
}


# --------------------------------------------------------------------------- #
# Receipts
# --------------------------------------------------------------------------- #


@dataclass
class Receipt:
    id: str
    source: str
    item_id: str
    action: str
    idempotency_key: str
    outcome: Optional[str] = None
    message: Optional[str] = None
    upstream_status: Optional[int] = None
    created_at: Optional[datetime] = None

    def document(self, *, replayed: bool) -> Dict[str, Any]:
        return {
            "schema": RECEIPT_SCHEMA,
            "id": self.id,
            "source": self.source,
            "item_id": self.item_id,
            "action": self.action,
            "outcome": self.outcome,
            "message": self.message,
            "upstream_status": self.upstream_status,
            "idempotency_key": self.idempotency_key,
            "created_at": iso(self.created_at) if self.created_at else None,
            "replayed": replayed,
        }


RESERVE_SQL = """
    INSERT INTO home_action_receipts
        (id, org_id, person_subject, source, item_id, action, idempotency_key)
    VALUES ($1::uuid, $2::uuid, $3, $4, $5, $6, $7)
    ON CONFLICT (org_id, person_subject, idempotency_key) DO NOTHING
    RETURNING created_at
"""

FIND_SQL = """
    SELECT id::text AS id, source, item_id, action, idempotency_key,
           upstream_status, outcome, message, created_at,
           (outcome IS NULL AND created_at < now() - ($4::int * interval '1 second')) AS stale
    FROM home_action_receipts
    WHERE org_id = $1::uuid AND person_subject = $2 AND idempotency_key = $3
"""

COMPLETE_SQL = """
    UPDATE home_action_receipts
    SET upstream_status = $2, outcome = $3, message = $4
    WHERE id = $1::uuid AND outcome IS NULL
"""


class PgReceiptStore:
    """``home_action_receipts`` through a short-lived asyncpg connection per
    statement (``my_apps_api.get_db_connection``, the same as the home state)."""

    def __init__(self, connect: Callable[[], Awaitable[Any]]):
        self._connect = connect

    async def _run(self, method: str, query: str, *params: Any) -> Any:
        conn = await self._connect()
        try:
            return await getattr(conn, method)(query, *params)
        finally:
            await conn.close()

    async def reserve(self, org_id: str, person: str, receipt: Receipt) -> bool:
        """Insert the reservation. False when this key is already taken."""

        row = await self._run(
            "fetchrow", RESERVE_SQL, receipt.id, org_id, person, receipt.source,
            receipt.item_id, receipt.action, receipt.idempotency_key,
        )
        if row is None:
            return False
        receipt.created_at = row["created_at"]
        return True

    async def find(self, org_id: str, person: str, key: str) -> Optional[Tuple[Receipt, bool]]:
        row = await self._run("fetchrow", FIND_SQL, org_id, person, key, STALE_RESERVATION_SECONDS)
        if row is None:
            return None
        receipt = Receipt(
            id=str(row["id"]), source=row["source"], item_id=row["item_id"], action=row["action"],
            idempotency_key=row["idempotency_key"], outcome=row["outcome"], message=row["message"],
            upstream_status=row["upstream_status"], created_at=row["created_at"],
        )
        return receipt, bool(row["stale"])

    async def complete(self, receipt: Receipt) -> bool:
        """Write the outcome once; False when the row was already completed."""

        status = await self._run(
            "execute", COMPLETE_SQL, receipt.id, receipt.upstream_status, receipt.outcome, receipt.message
        )
        return str(status or "").strip().endswith(" 1")


@dataclass
class ActionProviders:
    """The receipt table, the org's explicit workspace links and the HTTP
    client factory (``context.default_client_factory``: no redirects)."""

    store: Any  # PgReceiptStore or a stand-in with the same three methods
    workspace_rows: WorkspaceRowsProvider
    client_factory: ClientFactory = default_client_factory


def storage_subject(subject: str) -> str:
    """The person's session subject as stored. A subject that looks like an
    email address is stored as its SHA-256, so a receipt never holds one."""

    value = (subject or "").strip()
    if "@" in value:
        return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()
    return value


# --------------------------------------------------------------------------- #
# Replies
# --------------------------------------------------------------------------- #


@dataclass
class ActionReply:
    status_code: int
    body: Dict[str, Any]
    problem: bool = False
    headers: Dict[str, str] = field(default_factory=dict)


_TITLES = {400: "Bad Request", 409: "Conflict", 422: "Unprocessable Content", 503: "Service Unavailable"}


def problem(status: int, code: str, detail: str, fix: str, headers: Optional[Dict[str, str]] = None,
            **extra: Any) -> ActionReply:
    """An RFC 9457 problem document with a plain-words ``fix`` (DESIGN section g)."""

    body: Dict[str, Any] = {
        "type": "about:blank",
        "title": _TITLES.get(status, "Error"),
        "status": status,
        "detail": detail,
        "fix": fix,
        "code": code,
    }
    body.update(extra)
    return ActionReply(status, body, problem=True, headers=dict(headers or {}))


def receipts_unavailable() -> ActionReply:
    return problem(
        503, "receipts_unavailable",
        "The home cannot keep receipts right now, so nothing was sent to the app.",
        "Try again in a few minutes, or act on the item in its own app.",
    )


def unexpected_problem() -> ActionReply:
    return problem(
        503, "action_unavailable",
        "The home could not finish this request.",
        "Check the item in its own app before trying again.",
    )


# --------------------------------------------------------------------------- #
# Request checks
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Target:
    spec: ActionSpec
    item: str  # the app's own id, a lowercase UUID

    @property
    def item_id(self) -> str:
        return f"{self.spec.code}:{self.spec.kind}:{self.item}"


def _not_allowed(detail: str) -> ActionReply:
    return problem(
        400, "action_not_allowed", detail,
        "Use an item id from the home and one of the actions allowed for it.",
        allowed_actions=allowed_actions(),
    )


def resolve_target(source: str, item_id: str, action: str) -> Tuple[Optional[Target], Optional[ActionReply]]:
    source = (source or "").strip().lower()
    action = (action or "").strip().lower()
    code = SOURCE_CODES.get(source)
    if code is None:
        return None, _not_allowed(
            "The home can act only on Email-Ops drafts, Accounting-Ops approvals, "
            "and Project-Ops triage proposals and tasks."
        )
    parts = (item_id or "").strip().split(":")
    kind = parts[1].lower() if len(parts) == 3 and parts[0].lower() == code else None
    name = ITEM_NAMES.get((source, kind)) if kind else None
    if name is None:
        return None, _not_allowed(f"This is not an item id the home gave out for {source}.")
    spec = SPECS.get((source, kind, action))
    if spec is None:
        allowed = [s.action for s in ACTIONS if s.source == source and s.kind == kind]
        return None, _not_allowed(f"{name} allows: {' or '.join(allowed)}.")
    try:
        item = str(uuid.UUID(parts[2]))
    except (ValueError, AttributeError, TypeError):
        return None, _not_allowed(f"This is not an item id the home gave out for {source}.")
    return Target(spec, item), None


def check_idempotency_key(raw: Optional[str]) -> Tuple[Optional[str], Optional[ActionReply]]:
    fix = (
        "Send an Idempotency-Key header with a new random value, such as a UUID, for each "
        "action. Send the same value again to read the receipt of that action."
    )
    if raw is None or not raw.strip():
        return None, problem(400, "idempotency_key_missing", "This request needs an Idempotency-Key header.", fix)
    key = raw.strip()
    if len(key) >= 2 and key[0] == key[-1] == '"':  # the structured-field string form
        key = key[1:-1]
    if not (IDEMPOTENCY_KEY_MIN <= len(key) <= IDEMPOTENCY_KEY_MAX) or not _KEY_CHARS.match(key):
        return None, problem(
            400, "idempotency_key_invalid",
            f"The Idempotency-Key must be {IDEMPOTENCY_KEY_MIN} to {IDEMPOTENCY_KEY_MAX} visible ASCII characters.",
            fix,
        )
    return key, None


# --------------------------------------------------------------------------- #
# Offering actions on the items of the state document
# --------------------------------------------------------------------------- #

ACTION_ROUTE = "/api/v1/home/actions"

# Accounting-Ops ebd7796 decides a journal proposal (subject_type
# journal_entry_post, app/journal/pending_post.py:15) only for a human session
# whose token was issued to Accounting-Ops' own Keycloak client: before it reads
# the decision, decide_approval answers 403 "Journal proposal requires a human
# session" to approve and reject alike when the token's azp is not its
# keycloak_client_id, or the token is an agent, PAT, service or machine token
# (app/api/approvals.py:254-264). The home forwards the person's Ops-Center
# token, so it never offers a decision on one; Open still leads there.
ACCOUNTING_OPS_OWN_CLIENT_SUBJECTS = frozenset({"journal_entry_post"})

# Email-Ops 2810e17 agent-inbox rows are EMAIL, CLEANUP or NOTICE
# (prisma/schema.prisma:196-200; the list says EMAIL when unset,
# email.service.ts:6371). Only EMAIL is a draft. Approving a CLEANUP row trashes,
# archives or unsubscribes (:4032-4096) and approving a NOTICE adds a calendar
# event or acknowledges it (:3886-3913), so neither is offered a draft's Approve
# ("Sends the email now") or Reject. Review still opens it in Email-Ops.
EMAIL_OPS_DRAFT_KIND = "EMAIL"


def withheld_actions(source: str, kind: str, row: Mapping[str, Any], now: datetime) -> FrozenSet[str]:
    """Actions SPECS has for this source and kind that the home does not offer
    on this row: the owning app is known to refuse them for it, or would not do
    what the label says. ``row`` is the adapter's normalized row
    (``adapters/*.normalize_*``)."""

    if (source, kind) == ("email-ops", "draft"):
        if str(row.get("kind") or EMAIL_OPS_DRAFT_KIND).upper() != EMAIL_OPS_DRAFT_KIND:
            return frozenset({"approve", "reject"})
        # Approve leaves a draft whose send time is still ahead exactly as it
        # is (email.service.ts:3950-3958), so only Reject is offered on it.
        sends_at = parse_iso(row.get("sends_at"))
        if sends_at is not None and sends_at > now:
            return frozenset({"approve"})
    elif (source, kind) == ("accounting-ops", "approval"):
        if row.get("subject_type") in ACCOUNTING_OPS_OWN_CLIENT_SUBJECTS:
            return frozenset({"approve", "reject"})
    elif (source, kind) == ("project-ops", "triage"):
        # Accept sends no project, and Project-Ops ffc5bd5 answers 400 "no
        # project resolved" for a proposal without one (triage.service.ts:740-744).
        if not row.get("project_id"):
            return frozenset({"accept"})
    elif (source, kind) == ("project-ops", "task"):
        # Marked done without force, a task with an open blocker is refused
        # with 409 (tasks.service.ts:157-171); isBlocked is that same test
        # (:120-142, :1389-1395).
        if row.get("blocked"):
            return frozenset({"done"})
    return frozenset()


def offered_actions(item_id: Any, row: Mapping[str, Any], now: datetime) -> List[Dict[str, Any]]:
    """The actions the home offers on one item, for its ``actions`` list.

    Every SPECS entry for the item's source and kind, in table order, less the
    ``withheld_actions`` for its row, each as ``{id, label, method, href}`` plus
    ``note`` where the entry has one. Source and kind come from the item id, the
    middle part of ``eo:draft:<uuid>`` (not the item's own ``kind`` field), and
    each href is checked with ``resolve_target``, the route's own parser, so
    every offered href is one the route accepts. An id it would refuse (another
    source or kind, or no UUID) is offered nothing.
    """

    raw = str(item_id or "")
    parts = raw.split(":")
    if len(parts) != 3:
        return []
    specs = [spec for spec in ACTIONS if (spec.code, spec.kind) == (parts[0].lower(), parts[1].lower())]
    if not specs:
        return []
    withheld = withheld_actions(specs[0].source, specs[0].kind, row, now)
    offered: List[Dict[str, Any]] = []
    for spec in specs:
        target, _ = resolve_target(spec.source, raw, spec.action)
        if target is None or target.spec is not spec or spec.action in withheld:
            continue
        entry: Dict[str, Any] = {
            "id": spec.action,
            "label": spec.label,
            "method": "POST",
            "href": f"{ACTION_ROUTE}/{spec.source}/{target.item_id}/{spec.action}",
        }
        if spec.note:
            entry["note"] = spec.note
        offered.append(entry)
    return offered


# --------------------------------------------------------------------------- #
# Outcomes
# --------------------------------------------------------------------------- #


def safe_reason(body: Any, ring: str) -> Optional[str]:
    """The app's own reason (``detail`` or ``message``) when it is short plain
    text: no address, link, email address, markup, JSON or token-like run."""

    if not isinstance(body, dict):
        return None
    raw = next(
        (body[key] for key in ("detail", "message") if isinstance(body.get(key), str) and body[key].strip()),
        None,
    )
    if raw is None:
        return None
    reason = " ".join(raw.split())
    if len(reason) > REASON_MAX or not _REASON_CHARS.match(reason):
        return None
    if not any(ch.isalpha() for ch in reason) or "://" in reason or "www." in reason.lower():
        return None
    if any(len(word) > 40 for word in reason.split()):
        return None
    if guard_document(reason, ring)[1]:
        return None
    reason = reason[0].upper() + reason[1:]
    return reason if reason.endswith((".", "?")) else reason + "."


def _check_before_retry(label: str) -> str:
    return f"{label} could not finish this. Check the item in {label} before trying again."


def classify(spec: ActionSpec, status: int, body: Any, label: str, ctx: HomeContext) -> Tuple[str, str]:
    """Outcome and message for the app's answer to the write."""

    if 200 <= status < 300:
        return spec.done(body, ctx.now)
    if status == 401:
        return OUTCOME_REAUTH, REAUTH_MESSAGE
    if status == 403:
        return OUTCOME_REFUSED, f"{label} did not allow this. Open it in {label} to finish it."
    if status == 404:
        return OUTCOME_REFUSED, f"{label} could not find this item. It may have been handled already."
    if status in spec.already_handled:
        return OUTCOME_REFUSED, f"{label} says this was already handled, so nothing changed."
    if status in (409, 422):
        reason = safe_reason(body, ctx.ring)
        if reason:
            return OUTCOME_REFUSED, f"{label} did not do this. It said: {reason}"
        return OUTCOME_REFUSED, f"{label} did not do this right now. Open it in {label} to see why."
    return OUTCOME_FAILED, _check_before_retry(label)


# --------------------------------------------------------------------------- #
# Forwarding
# --------------------------------------------------------------------------- #

Result = Tuple[str, Optional[int], str]  # outcome, upstream status, message


async def _workspace_rows(providers: ActionProviders, timeout: float) -> Dict[str, str]:
    try:
        rows = await asyncio.wait_for(providers.workspace_rows(), timeout)
    except Exception as exc:  # noqa: BLE001 - the org id candidate still applies
        logger.warning("home action: workspace rows unavailable (%s)", type(exc).__name__)
        return {}
    return dict(rows or {})


async def _write(env: AdapterEnv, call: UpstreamCall, timeout: float) -> Tuple[Optional[int], Any, Optional[str]]:
    """The one write, with the person's Bearer token and nothing else. Returns
    (status, body for 2xx/409/422 or None, transport failure or None)."""

    headers = {
        "Authorization": f"Bearer {env.ctx.access_token or ''}",
        "Accept": "application/json",
        **call.headers,
    }
    env.client.cookies.clear()  # a cookie an app set on the membership read never rides along
    try:
        response = await env.client.request(
            call.method, env.api_base.rstrip("/") + call.path, json=call.body, headers=headers, timeout=timeout
        )
    except (httpx.ConnectError, httpx.ConnectTimeout):
        return None, None, "unreached"
    except httpx.TimeoutException:
        return None, None, TIMEOUT
    except httpx.HTTPError:
        return None, None, "error"
    status = response.status_code
    body = None
    if 200 <= status < 300 or status in (409, 422):
        try:
            body = response.json()
        except ValueError:
            body = None
    return status, body, None


async def forward(ctx: HomeContext, providers: ActionProviders, target: Target) -> Result:
    spec = target.spec
    label = settings.APPS[spec.source].label
    api_base = settings.api_base_url(spec.source, ctx.ring)
    if not api_base:
        return OUTCOME_FAILED, None, f"{label} is not connected to the home on this ring yet."
    if token_expired(ctx.access_token, ctx.now):
        return OUTCOME_REAUTH, None, REAUTH_MESSAGE

    read_timeout = settings.app_timeout_seconds()
    write_timeout = settings.action_timeout_seconds()
    rows = await _workspace_rows(providers, read_timeout)
    client = providers.client_factory(max(read_timeout, write_timeout))
    try:
        env = AdapterEnv(
            ctx=ctx, client=client, app=spec.source, label=label, api_base=api_base, web_base=None,
            candidates=workspace_candidates(ctx.org_id, spec.source, rows), timeout=read_timeout,
        )
        try:
            workspace = await WORKSPACE_FINDERS[spec.source](env)
        except Reauth as exc:
            return OUTCOME_REAUTH, exc.status_code, REAUTH_MESSAGE
        except Forbidden as exc:
            return OUTCOME_REFUSED, exc.status_code, f"{label} did not allow this. Open it in {label} to finish it."
        except UpstreamError as exc:
            if exc.reason == TIMEOUT:
                return OUTCOME_FAILED, None, f"{label} did not answer in time, so nothing was changed. Try again in a moment."
            return OUTCOME_FAILED, exc.status_code, f"{label} had a problem, so nothing was changed. Try again in a moment."
        if workspace is None:
            return OUTCOME_REFUSED, None, link_note(label)

        status, body, failure = await _write(env, spec.request(workspace, target.item), write_timeout)
        if failure == "unreached":
            return OUTCOME_FAILED, None, f"{label} could not be reached, so nothing was changed. Try again in a moment."
        if failure == TIMEOUT:
            return OUTCOME_FAILED, None, f"{label} did not answer in time. Check the item in {label} before trying again."
        if failure or status is None:
            return OUTCOME_FAILED, None, _check_before_retry(label)
        outcome, message = classify(spec, status, body, label, ctx)
        return outcome, status, message
    finally:
        await client.aclose()


async def _forward_safely(ctx: HomeContext, providers: ActionProviders, target: Target) -> Result:
    try:
        return await forward(ctx, providers, target)
    except Exception as exc:  # noqa: BLE001 - a bug is a failed receipt, never a 500
        logger.warning(
            "home action: %s %s failed unexpectedly (%s)", target.spec.source, target.spec.action, type(exc).__name__
        )
        return OUTCOME_FAILED, None, _check_before_retry(settings.APPS[target.spec.source].label)


# --------------------------------------------------------------------------- #
# The action
# --------------------------------------------------------------------------- #


async def _replay(ctx: HomeContext, providers: ActionProviders, person: str, fresh: Receipt) -> ActionReply:
    """The key is taken: return its receipt, or say why not."""

    try:
        found = await providers.store.find(ctx.org_id, person, fresh.idempotency_key)
    except Exception as exc:  # noqa: BLE001
        logger.warning("home action: receipt lookup failed (%s)", type(exc).__name__)
        return receipts_unavailable()
    if found is None:
        return receipts_unavailable()
    stored, stale = found
    if (stored.source, stored.item_id, stored.action) != (fresh.source, fresh.item_id, fresh.action):
        return problem(
            422, "idempotency_key_reused",
            "This Idempotency-Key was already used for a different action.",
            "Send a new Idempotency-Key for each new action.",
        )
    if stored.outcome is None and not stale:
        return problem(
            409, "action_in_progress", "This action is still being sent to the app.",
            "Wait a moment, then send the same request with the same Idempotency-Key to read its receipt.",
            headers={"Retry-After": "2"},
        )
    if stored.outcome is None:
        app = settings.APPS.get(stored.source)
        label = app.label if app else "the app"
        stored.outcome = OUTCOME_FAILED
        stored.message = f"This action did not finish. Check the item in {label} before trying again."
        try:
            if not await providers.store.complete(stored):
                reread = await providers.store.find(ctx.org_id, person, fresh.idempotency_key)
                stored = reread[0] if reread else stored
        except Exception as exc:  # noqa: BLE001
            logger.warning("home action: closing an unfinished receipt failed (%s)", type(exc).__name__)
    return ActionReply(200, stored.document(replayed=True), headers={"Idempotent-Replayed": "true"})


async def run_action(
    ctx: HomeContext,
    providers: ActionProviders,
    source: str,
    item_id: str,
    action: str,
    idempotency_key: Optional[str],
) -> ActionReply:
    """Check the request, reserve the receipt, forward once, complete the receipt."""

    target, refusal = resolve_target(source, item_id, action)
    if refusal is not None:
        return refusal
    key, refusal = check_idempotency_key(idempotency_key)
    if refusal is not None:
        return refusal

    person = storage_subject(ctx.person_id)
    receipt = Receipt(
        id=str(uuid.uuid4()), source=target.spec.source, item_id=target.item_id,
        action=target.spec.action, idempotency_key=key,
    )
    try:
        reserved = await providers.store.reserve(ctx.org_id, person, receipt)
    except Exception as exc:  # noqa: BLE001 - no receipt, no call
        logger.warning("home action: receipt reservation failed (%s)", type(exc).__name__)
        return receipts_unavailable()
    if not reserved:
        return await _replay(ctx, providers, person, receipt)

    started = time.monotonic()
    receipt.outcome, receipt.upstream_status, receipt.message = await _forward_safely(ctx, providers, target)
    logger.info(
        "home action: %s %s %s -> %s (%s) in %d ms",
        target.spec.source, target.spec.kind, target.spec.action, receipt.outcome,
        receipt.upstream_status if receipt.upstream_status is not None else "no status",
        int((time.monotonic() - started) * 1000),
    )
    try:
        await providers.store.complete(receipt)
    except Exception as exc:  # noqa: BLE001 - the person still gets the receipt
        logger.warning("home action: receipt completion failed (%s)", type(exc).__name__)
    return ActionReply(200, receipt.document(replayed=False))
