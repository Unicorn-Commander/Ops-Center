"""Accounting-Ops adapter.

Read from Accounting-Ops ``origin/main`` (ebd7796). Bearer only: a Keycloak
token with a matching audience, a Brigade token, an ``aops_pat_`` PAT or a
service token (``app/auth.py``).

Reachability: the public host sends ``/api/*`` to the Next.js web tier, whose
proxies accept only a browser session (``docker-compose.yml:147-158,207-210``;
``web/app/api/workspaces/[workspaceId]/cfo-brief/route.ts``), so
``HOME_ACCOUNTING_OPS_API_URL`` must point at the FastAPI service itself.

Workspace: each candidate is probed with ``GET /api/workspaces/{id}``
(``app/api/workspaces.py:127-151``), which answers 404 for an unknown
workspace, 403 without an active membership (``app/tenancy.py``
``_resolve_membership``) and otherwise returns the caller's Accounting-Ops
role. The list route ``/api/me/workspaces`` is deliberately not used: it can
provision a workspace on first call (``app/api/workspaces.py:57-66``,
``app/api/onboarding.py`` ``ensure_entitled_workspace``). Workspace ids are
UUIDs (``app/api/onboarding.py:126-131`` uses the Ops-Center org UUID).
Role ladder (``app/tenancy.py:70-80``): viewer 0, client_user 1, bookkeeper 2,
accountant 3 (cpa 3), admin 4, owner 5 (client_owner 5).

* ``GET /api/workspaces/{id}/approvals?status_filter=pending&limit=N``
  (``app/api/approvals.py:88-157``): ``{approvals: [{id, entity_id,
  entity_display_name, entity_slug, subject_type, subject_id, amount,
  currency_code, status, reasoning, requested_by_identity, decided_by_uc_uid,
  decided_at, created_at, payload}], total}``. Read floor accountant; only
  admin decides, so it is fetched for Accounting-Ops admins and owners only.
* ``GET /api/workspaces/{id}/cfo-brief`` (``app/api/cfo_brief.py:482-...``,
  model ``:92-145``): ``as_of, priorities[{id, kind, severity, headline,
  detail, action_href, action_label, score}], action_required_total,
  cash{configured, headline, detail, assets_total, liabilities_total,
  net_total, months_runway, monthly_burn, tone}, summary_line, onboarding,
  ask_cfo_href, sources_ok``. Floor viewer.
* ``GET /api/workspaces/{id}/invoices?limit=500`` (``app/api/invoices.py:160-243``):
  ``{invoices: [{id, status, currency, issue_date, due_date, total,
  balance_due, aging, customer_name, ...}], total}``; statuses
  draft|sent|viewed|partial|paid|overdue|void
  (``migrations/tenant/versions/0019_ar_invoicing.py:269-272``). Floor viewer.

The two money routes are called only for Ops-Center org owners and admins.
Screens (``web/app``): ``/approvals``, ``/dashboard``, ``/invoices``.
"""

from __future__ import annotations

import asyncio
import uuid
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional

from .base import (
    EMPTY,
    NOT_ENTITLED,
    OK,
    AdapterEnv,
    AppSnapshot,
    Forbidden,
    NotFound,
    Part,
    Rejected,
    UpstreamError,
    failed_snapshot,
    get_json,
    iso,
    link_note,
    not_set_up_snapshot,
    parse_iso,
    part_from_error,
    path_segment,
    raise_if_reauth,
    short,
    snapshot,
)

ROLE_RANK = {
    "viewer": 0,
    "client_user": 1,
    "bookkeeper": 2,
    "accountant": 3,
    "cpa": 3,
    "admin": 4,
    "owner": 5,
    "client_owner": 5,
    "platform_admin": 100,
}
DECIDER_RANK = ROLE_RANK["admin"]
APPROVALS_LIMIT = 20
INVOICES_LIMIT = 500
OPEN_INVOICE_STATUSES = frozenset({"sent", "viewed", "partial"})


def _is_uuid(value: str) -> bool:
    try:
        uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        return False
    return True


def _decimal(value: Any) -> Optional[Decimal]:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def money_text(value: Any) -> Optional[str]:
    amount = _decimal(value)
    if amount is None:
        return None
    return f"{amount.quantize(Decimal('0.01')):,.2f}"


def normalize_approval(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": str(row.get("id") or ""),
        "subject_type": str(row.get("subject_type") or ""),
        "amount": money_text(row.get("amount")),
        "currency": row.get("currency_code"),
        "entity": short(row.get("entity_display_name"), 80),
        "reasoning": row.get("reasoning"),
        "requested_by": short(row.get("requested_by_identity"), 80),
        "created_at": parse_iso(row.get("created_at")),
    }


def invoiced_not_due(rows: List[Dict[str, Any]], total: int) -> Dict[str, Any]:
    """Balance on open invoices whose due date has not passed (aging 'current')."""

    amount = Decimal("0")
    count = 0
    currencies = set()
    for row in rows:
        if str(row.get("status") or "").lower() not in OPEN_INVOICE_STATUSES:
            continue
        if row.get("aging") != "current":
            continue
        balance = _decimal(row.get("balance_due"))
        if balance is None or balance <= 0:
            continue
        amount += balance
        count += 1
        if row.get("currency"):
            currencies.add(str(row["currency"]).upper())
    return {
        "amount": f"{amount.quantize(Decimal('0.01')):,.2f}",
        "currency": currencies.pop() if len(currencies) == 1 else ("mixed" if currencies else None),
        "count": count,
        "complete": total <= len(rows),
    }


async def _find_workspace(env: AdapterEnv):
    for candidate in env.candidates:
        if not _is_uuid(candidate.workspace_id):
            continue
        try:
            detail = await get_json(env, f"/api/workspaces/{path_segment(candidate.workspace_id)}")
        except (Forbidden, NotFound, Rejected):
            continue
        return candidate, (detail if isinstance(detail, dict) else {})
    return None


async def _fetch(env: AdapterEnv) -> AppSnapshot:
    found = await _find_workspace(env)
    if found is None:
        return not_set_up_snapshot(env, link_note("Accounting-Ops"))
    candidate, detail = found
    ws = candidate.workspace_id
    role = str(detail.get("role") or "").lower()
    rank = ROLE_RANK.get(role, -1)
    base = f"/api/workspaces/{path_segment(ws)}"

    approvals_route = f"{base}/approvals?status_filter=pending&limit={APPROVALS_LIMIT}"
    cfo_route = f"{base}/cfo-brief"
    invoices_route = f"{base}/invoices?limit={INVOICES_LIMIT}"

    names: List[str] = []
    calls = []
    if rank >= DECIDER_RANK:
        names.append("approvals")
        calls.append(
            get_json(env, f"{base}/approvals", params={"status_filter": "pending", "limit": APPROVALS_LIMIT})
        )
    if env.want_money:
        names.extend(["cfo_brief", "invoices"])
        calls.append(get_json(env, cfo_route))
        calls.append(get_json(env, f"{base}/invoices", params={"limit": INVOICES_LIMIT}))
    results = dict(zip(names, await asyncio.gather(*calls, return_exceptions=True)))
    raise_if_reauth(results.values())

    parts: Dict[str, Part] = {}
    approvals_screen = env.screen("/approvals")
    if "approvals" not in results:
        parts["approvals"] = Part(
            "approvals", NOT_ENTITLED, route=approvals_route, screen=approvals_screen, as_of=iso(),
            note="Only Accounting-Ops admins and owners decide approvals.",
        )
    elif isinstance(results["approvals"], BaseException):
        parts["approvals"] = part_from_error(
            "approvals", results["approvals"], approvals_route, approvals_screen
        )
    else:
        payload = results["approvals"] if isinstance(results["approvals"], dict) else {}
        items = [normalize_approval(r) for r in payload.get("approvals") or [] if isinstance(r, dict)]
        try:
            total = int(payload.get("total"))
        except (TypeError, ValueError):
            total = len(items)
        parts["approvals"] = Part(
            "approvals", OK if total or items else EMPTY, route=approvals_route,
            screen=approvals_screen, data={"items": items, "count": max(total, len(items))}, as_of=iso(),
        )

    if env.want_money:
        dashboard = env.screen("/dashboard")
        cfo = results.get("cfo_brief")
        if isinstance(cfo, BaseException):
            parts["cfo_brief"] = part_from_error("cfo_brief", cfo, cfo_route, dashboard)
        else:
            parts["cfo_brief"] = Part(
                "cfo_brief", OK, route=cfo_route, screen=dashboard,
                data=cfo if isinstance(cfo, dict) else {}, as_of=iso(),
            )
        invoices_screen = env.screen("/invoices")
        invoices = results.get("invoices")
        if isinstance(invoices, BaseException):
            parts["invoices"] = part_from_error("invoices", invoices, invoices_route, invoices_screen)
        else:
            payload = invoices if isinstance(invoices, dict) else {}
            rows = [r for r in payload.get("invoices") or [] if isinstance(r, dict)]
            try:
                total = int(payload.get("total"))
            except (TypeError, ValueError):
                total = len(rows)
            parts["invoices"] = Part(
                "invoices", OK if rows else EMPTY, route=invoices_route, screen=invoices_screen,
                data=invoiced_not_due(rows, total), as_of=iso(),
            )

    return snapshot(
        env, OK, workspace=ws, workspace_origin=candidate.origin, role=role or None, parts=parts
    )


async def fetch(env: AdapterEnv) -> AppSnapshot:
    try:
        return await _fetch(env)
    except UpstreamError as exc:
        return failed_snapshot(env, exc)
