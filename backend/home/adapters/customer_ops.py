"""Customer-Ops adapter.

Read from Customer-Ops ``origin/main`` (bb0b768). Bearer only
(``backend/src/auth/strategies/jwt.strategy.ts``).

* ``GET /api/v1/auth/me/workspaces`` (``backend/src/auth/auth.controller.ts:173-181``,
  ``common/workspace/list-my-workspaces.ts``):
  ``{workspaces: [{workspace_id, slug, display_name, role, is_default}]}``.
  Used to confirm the mapped workspace.
* ``GET /api/v1/workspaces/{ws}/customers?ownerUserKey={sub}&limit=200``
  (``backend/src/customers/customers.controller.ts:51-65``,
  ``dto/customer.dto.ts:140-179``, ``customers.service.ts:2378-2390``):
  ``{items, count}``; rows carry ``id, stage, priority, ownerUserKey`` (the
  uchub ``sub`` of the rep, ``prisma/schema.prisma:402-404``), ``nextActionAt``
  (``:410-412``), ``expectedValue, isLost`` and a federated ``contact
  {displayName, primaryEmail, currentOrgName}`` that is null when Contact-Ops
  cannot answer. The list has no ``nextActionAt`` filter, so due follow-ups
  are picked out by the home.

Screens (``frontend/app``): ``/dashboard/customers``,
``/dashboard/customers/{id}``. On the customer ring the API has its own host
(``deploy/docker-compose.prod.yml:206``), which is the index entry.
"""

from __future__ import annotations

from typing import Any, Dict

from ..mapping import choose_workspace
from .base import (
    EMPTY,
    OK,
    AdapterEnv,
    AppSnapshot,
    Part,
    Reauth,
    UpstreamError,
    failed_snapshot,
    get_json,
    iso,
    link_note,
    member_ids,
    not_set_up_snapshot,
    parse_iso,
    part_from_error,
    path_segment,
    short,
    snapshot,
)

WORKSPACES_ROUTE = "/api/v1/auth/me/workspaces"
CUSTOMERS_LIMIT = 200


def normalize_customer(row: Dict[str, Any], env: AdapterEnv) -> Dict[str, Any]:
    contact = row.get("contact") if isinstance(row.get("contact"), dict) else {}
    customer_id = str(row.get("id") or "")
    return {
        "id": customer_id,
        "name": short(contact.get("displayName"), 80) or short(contact.get("currentOrgName"), 80),
        "stage": row.get("stage"),
        "priority": row.get("priority"),
        "next_action_at": parse_iso(row.get("nextActionAt")),
        "is_lost": bool(row.get("isLost")),
        "href": env.screen(f"/dashboard/customers/{path_segment(customer_id)}") if customer_id else None,
    }


async def _fetch(env: AdapterEnv) -> AppSnapshot:
    listing = await get_json(env, WORKSPACES_ROUTE)
    rows = listing.get("workspaces") if isinstance(listing, dict) else None
    chosen = choose_workspace(env.candidates, member_ids(rows or [], "workspace_id"))
    if chosen is None:
        return not_set_up_snapshot(env, link_note("Customer-Ops"))

    path = f"/api/v1/workspaces/{path_segment(chosen.workspace_id)}/customers"
    route = f"{path}?ownerUserKey={path_segment(env.ctx.person_id)}&limit={CUSTOMERS_LIMIT}"
    screen = env.screen("/dashboard/customers")
    try:
        payload = await get_json(
            env, path, params={"ownerUserKey": env.ctx.person_id, "limit": CUSTOMERS_LIMIT}
        )
    except Reauth:
        raise
    except UpstreamError as exc:
        part = part_from_error("followups", exc, route, screen)
    else:
        payload = payload if isinstance(payload, dict) else {}
        customers = [
            normalize_customer(row, env) for row in payload.get("items") or [] if isinstance(row, dict)
        ]
        part = Part(
            "followups", OK if customers else EMPTY, route=route, screen=screen,
            data={"items": customers, "count_is_lower_bound": len(customers) >= CUSTOMERS_LIMIT},
            as_of=iso(),
        )

    return snapshot(
        env, OK, workspace=chosen.workspace_id, workspace_origin=chosen.origin,
        parts={"followups": part},
    )


async def fetch(env: AdapterEnv) -> AppSnapshot:
    try:
        return await _fetch(env)
    except UpstreamError as exc:
        return failed_snapshot(env, exc)
