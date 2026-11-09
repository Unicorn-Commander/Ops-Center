"""Email-Ops adapter.

Read from Email-Ops ``origin/main`` (2810e17). Auth reads the ``access_token``
cookie, then the Bearer header (``backend/src/auth/strategies/jwt.strategy.ts``).

* ``GET /api/v1/auth/me/workspaces`` (``backend/src/auth/auth.controller.ts:170-177``,
  ``common/workspace/list-my-workspaces.ts:15-44``):
  ``{workspaces: [{workspace_id, slug, display_name, role, is_default}]}``.
  Used to confirm the mapped workspace.
* ``GET /api/v1/workspaces/{ws}/agent-inbox``
  (``backend/src/agent-inbox/agent-inbox.controller.ts:181-182,311-335``):
  ``{items, count}``. The state defaults to pending; ``count`` is pending
  drafts plus proposed send kits (``backend/src/email/email.service.ts:2712-2735``);
  ``items`` are ``AgentInboxView`` rows (``email.types.ts:243-277``: id, kind,
  approval_tier, state, drafted_by, summary, to_address, from_address, subject,
  body_preview, thread_id, kit_id, sends_at, created_at), newest first, capped
  at 200, already narrowed to the mailboxes this person may see
  (``email.service.ts:2664-2683``). This read route also backfills old draft
  subjects on read (``email.service.ts:2696-2704``), as it does when the person
  opens the inbox in Email-Ops.

Screen: ``/agent-inbox`` (``frontend/app/agent-inbox/page.tsx``). It takes no
item id in the URL, so every row opens the queue. The public host routes
``/api`` to the backend (``infrastructure/docker-compose.bigboy.prod.yml:68``).
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


def inbox_route(workspace_id: str) -> str:
    return f"/api/v1/workspaces/{path_segment(workspace_id)}/agent-inbox"


def normalize_item(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": str(row.get("id") or ""),
        "kind": row.get("kind"),
        "subject": short(row.get("subject")),
        "summary": row.get("summary"),
        "preview": row.get("body_preview"),
        "drafted_by": short(row.get("drafted_by"), 80),
        "to": short(row.get("to_address"), 120),
        "sends_at": parse_iso(row.get("sends_at")),
        "created_at": parse_iso(row.get("created_at")),
        "approval_tier": row.get("approval_tier"),
    }


async def _fetch(env: AdapterEnv) -> AppSnapshot:
    listing = await get_json(env, WORKSPACES_ROUTE)
    rows = listing.get("workspaces") if isinstance(listing, dict) else None
    chosen = choose_workspace(env.candidates, member_ids(rows or [], "workspace_id"))
    if chosen is None:
        return not_set_up_snapshot(env, link_note("Email-Ops"))

    route = inbox_route(chosen.workspace_id)
    screen = env.screen("/agent-inbox")
    try:
        payload = await get_json(env, route)
    except Reauth:
        raise
    except UpstreamError as exc:
        part = part_from_error("agent_inbox", exc, route, screen)
    else:
        payload = payload if isinstance(payload, dict) else {}
        items = [normalize_item(row) for row in payload.get("items") or [] if isinstance(row, dict)]
        try:
            count = int(payload.get("count"))
        except (TypeError, ValueError):
            count = len(items)
        part = Part(
            "agent_inbox", OK if count or items else EMPTY, route=route, screen=screen,
            data={"items": items, "count": max(count, len(items))}, as_of=iso(),
        )

    return snapshot(
        env, OK, workspace=chosen.workspace_id, workspace_origin=chosen.origin,
        parts={"agent_inbox": part},
    )


async def fetch(env: AdapterEnv) -> AppSnapshot:
    try:
        return await _fetch(env)
    except UpstreamError as exc:
        return failed_snapshot(env, exc)
