"""Meeting-Ops adapter.

Read from UC-Meeting-Ops ``origin/main`` (97ac807). Auth accepts a Keycloak
Bearer whose ``azp``/``aud`` is in the accepted list (``backend/auth/dependencies.py``).

* ``GET /api/auth/orgs`` (``backend/auth/routes.py:681-689``, model ``:124-135``):
  the caller's orgs ``[{id, name, slug, role, is_active, plan}]``. Used to
  confirm the mapped org first, because the ``X-MeetingOps-Org`` selector takes
  a SLUG and silently falls back to the person's default org when it does not
  match (``backend/auth/organization.py:17,222-300``).
* ``GET /api/analytics/sessions?limit=N`` (``backend/api/analytics_simple.py:157-210``):
  ``[{id, name, created_at, duration, speakers, status, has_ai_summary}]``,
  completed or processing sessions of the active org, newest first. ``id`` is
  the session key; ``duration`` is seconds (``api/simple_recording_db.py:1621``).
* ``GET /api/action-items?status=todo&limit=N`` (``backend/api/action_items.py:229-273``,
  model ``:78-100``, statuses ``:39``): open items with ``session_key,
  session_title, text, owner, due_date, created_at``.

Never calls ``/api/digests``: a plain GET there can queue an LLM job
(``backend/api/digests.py:206-222``). Screens are hash routes
(``frontend/src/AppRouterSimplified.tsx:592-608``): ``#/sessions``,
``#/sessions/{id}``, ``#/action-items``. On the customer ring ``/api`` goes
straight to the backend (``deploy/unicorncommander/docker-compose.unicorncommander.yml:335``);
on the internal ring it sits behind oauth2-proxy (``deploy/bigboy/docker-compose.bigboy.yml:755-790``).
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, Optional, Tuple

from .base import (
    EMPTY,
    OK,
    AdapterEnv,
    AppSnapshot,
    Part,
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

ORGS_ROUTE = "/api/auth/orgs"
SESSIONS_ROUTE = "/api/analytics/sessions"
ACTION_ITEMS_ROUTE = "/api/action-items"
SESSIONS_LIMIT = 20
ACTION_ITEMS_LIMIT = 200
ORG_HEADER = "X-MeetingOps-Org"


def _choose_org(env: AdapterEnv, orgs: Any) -> Optional[Tuple[Any, Dict[str, Any]]]:
    by_key: Dict[str, Dict[str, Any]] = {}
    for org in orgs if isinstance(orgs, list) else []:
        if not isinstance(org, dict) or not org.get("slug"):
            continue
        by_key[str(org["slug"]).strip().lower()] = org
        if org.get("id") is not None:
            by_key[str(org["id"]).strip().lower()] = org
    for candidate in env.candidates:
        org = by_key.get(candidate.workspace_id.strip().lower())
        if org is not None:
            return candidate, org
    return None


def normalize_session(row: Dict[str, Any], env: AdapterEnv) -> Dict[str, Any]:
    key = str(row.get("id") or "")
    try:
        duration = int(round(float(row.get("duration") or 0)))
    except (TypeError, ValueError):
        duration = 0
    try:
        speakers = int(row.get("speakers") or 0)
    except (TypeError, ValueError):
        speakers = 0
    return {
        "id": key,
        "title": short(row.get("name")) or "Untitled meeting",
        "created_at": parse_iso(row.get("created_at")),
        "duration_seconds": duration,
        "speakers": speakers,
        "status": row.get("status"),
        "has_summary": bool(row.get("has_ai_summary")),
        "href": env.screen(f"/#/sessions/{path_segment(key)}") if key else None,
    }


def normalize_action_item(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": str(row.get("id") or ""),
        "session_key": str(row.get("session_key") or ""),
        "session_title": short(row.get("session_title")),
        "text": row.get("text"),
        "owner": short(row.get("owner"), 80),
        "due_date": row.get("due_date"),
        "created_at": parse_iso(row.get("created_at")),
    }


async def _fetch(env: AdapterEnv) -> AppSnapshot:
    orgs = await get_json(env, ORGS_ROUTE)
    chosen = _choose_org(env, orgs)
    if chosen is None:
        return not_set_up_snapshot(env, link_note("Meeting-Ops"))
    candidate, org = chosen
    slug = str(org["slug"])
    headers = {ORG_HEADER: slug}

    results = await asyncio.gather(
        get_json(env, SESSIONS_ROUTE, params={"limit": SESSIONS_LIMIT}, headers=headers),
        get_json(
            env, ACTION_ITEMS_ROUTE, params={"status": "todo", "limit": ACTION_ITEMS_LIMIT}, headers=headers
        ),
        return_exceptions=True,
    )
    raise_if_reauth(results)

    parts: Dict[str, Part] = {}
    sessions_route = f"{SESSIONS_ROUTE}?limit={SESSIONS_LIMIT}"
    sessions_screen = env.screen("/#/sessions")
    if isinstance(results[0], BaseException):
        parts["sessions"] = part_from_error("sessions", results[0], sessions_route, sessions_screen)
    else:
        rows = results[0] if isinstance(results[0], list) else []
        sessions = [normalize_session(row, env) for row in rows if isinstance(row, dict)]
        parts["sessions"] = Part(
            "sessions", OK if sessions else EMPTY, route=sessions_route, screen=sessions_screen,
            data={"items": sessions, "limit": SESSIONS_LIMIT}, as_of=iso(),
        )

    items_route = f"{ACTION_ITEMS_ROUTE}?status=todo&limit={ACTION_ITEMS_LIMIT}"
    items_screen = env.screen("/#/action-items")
    if isinstance(results[1], BaseException):
        parts["action_items"] = part_from_error("action_items", results[1], items_route, items_screen)
    else:
        rows = results[1] if isinstance(results[1], list) else []
        items = [normalize_action_item(row) for row in rows if isinstance(row, dict)]
        parts["action_items"] = Part(
            "action_items", OK if items else EMPTY, route=items_route, screen=items_screen,
            data={
                "items": items,
                "count": len(items),
                "count_is_lower_bound": len(items) >= ACTION_ITEMS_LIMIT,
            },
            as_of=iso(),
        )

    return snapshot(
        env, OK, workspace=slug, workspace_origin=candidate.origin, role=org.get("role"), parts=parts
    )


async def fetch(env: AdapterEnv) -> AppSnapshot:
    try:
        return await _fetch(env)
    except UpstreamError as exc:
        return failed_snapshot(env, exc)
