"""Center Deep Research adapter (per person).

Read from Center-Deep-Research ``origin/main`` (0a3279e). Briefs and
notifications are scoped to the person, not the organization, because no
token carries an org claim yet (``src/center_deep_research/federation/keycloak.py:62-73``).
So this module needs no workspace mapping.

* ``GET /api/briefs`` (``src/center_deep_research/api/briefs_routes.py:469-477``):
  ``list[ResearchBrief]`` (``schemas.py:536-585``): ``id, title, kind``
  (``standard`` or ``situation``, ``:389-401``) and ``schedule{enabled,
  cadence, next_run_at, last_run_at}`` (``:339-383``). A watched topic is a
  brief with ``kind != "situation"`` and ``schedule.enabled``, sorted by title,
  the same rule as Center Deep's own home (``web/src/lib/briefs.ts:240-246``).
* ``GET /api/notifications?limit=100`` (``api/notifications_routes.py:49-59``):
  ``list[Notification]`` newest first (``briefs/store.py`` list,
  ``order_by(created_at.desc())``), each ``id, created_at, brief_id, run_id,
  title, summary, read, drift{changed, summary}, data_drift{changed, summary}``
  (``schemas.py:658-680,723-740,751-782``).

Auth: a uchub Bearer JWT whose audience is ``center-deep-research`` or
``account`` (``federation/keycloak.py:1-9,205-226``). On the customer ring
``/api/*`` is behind oauth2-proxy with Bearer pass-through
(``deploy/docker-compose.prod.yml:129-170``), which also checks the audience.
Screens are hash routes (``web/src/App.tsx:218-226``): ``#/brief/{id}``,
``#/run/{id}``.
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict

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
    parse_iso,
    part_from_error,
    path_segment,
    raise_if_reauth,
    short,
    snapshot,
)

BRIEFS_ROUTE = "/api/briefs"
NOTIFICATIONS_ROUTE = "/api/notifications"
NOTIFICATIONS_LIMIT = 100


def normalize_brief(row: Dict[str, Any], env: AdapterEnv) -> Dict[str, Any]:
    schedule = row.get("schedule") if isinstance(row.get("schedule"), dict) else {}
    brief_id = str(row.get("id") or "")
    return {
        "id": brief_id,
        "title": short(row.get("title")) or "Untitled topic",
        "kind": str(row.get("kind") or "standard"),
        "enabled": bool(schedule.get("enabled")),
        "cadence": schedule.get("cadence"),
        "last_run_at": parse_iso(schedule.get("last_run_at")),
        "next_run_at": parse_iso(schedule.get("next_run_at")),
        "href": env.screen(f"/#/brief/{path_segment(brief_id)}") if brief_id else None,
    }


def _drift(row: Dict[str, Any], key: str) -> Dict[str, Any]:
    value = row.get(key)
    return value if isinstance(value, dict) else {}


def normalize_notification(row: Dict[str, Any], env: AdapterEnv) -> Dict[str, Any]:
    drift = _drift(row, "drift")
    data_drift = _drift(row, "data_drift")
    run_id = str(row.get("run_id") or "")
    changed = bool(drift.get("changed")) or bool(data_drift.get("changed"))
    line = (
        (drift.get("summary") if drift.get("changed") else None)
        or (data_drift.get("summary") if data_drift.get("changed") else None)
        or row.get("summary")
    )
    return {
        "id": str(row.get("id") or ""),
        "brief_id": str(row.get("brief_id") or ""),
        "title": short(row.get("title")) or "Monitor update",
        "created_at": parse_iso(row.get("created_at")),
        "read": bool(row.get("read")),
        "changed": changed,
        "line": line,
        "run_href": env.screen(f"/#/run/{path_segment(run_id)}") if run_id else None,
    }


async def _fetch(env: AdapterEnv) -> AppSnapshot:
    results = await asyncio.gather(
        get_json(env, BRIEFS_ROUTE),
        get_json(env, NOTIFICATIONS_ROUTE, params={"limit": NOTIFICATIONS_LIMIT}),
        return_exceptions=True,
    )
    raise_if_reauth(results)
    if all(isinstance(result, BaseException) for result in results):
        first = results[0]
        raise first if isinstance(first, UpstreamError) else UpstreamError("error")

    parts: Dict[str, Part] = {}
    home = env.screen("/")
    if isinstance(results[0], BaseException):
        parts["briefs"] = part_from_error("briefs", results[0], BRIEFS_ROUTE, home)
    else:
        rows = results[0] if isinstance(results[0], list) else []
        briefs = [normalize_brief(row, env) for row in rows if isinstance(row, dict)]
        parts["briefs"] = Part(
            "briefs", OK if briefs else EMPTY, route=BRIEFS_ROUTE, screen=home, data=briefs, as_of=iso()
        )

    notifications_route = f"{NOTIFICATIONS_ROUTE}?limit={NOTIFICATIONS_LIMIT}"
    if isinstance(results[1], BaseException):
        parts["notifications"] = part_from_error("notifications", results[1], notifications_route, home)
    else:
        rows = results[1] if isinstance(results[1], list) else []
        notes = [normalize_notification(row, env) for row in rows if isinstance(row, dict)]
        parts["notifications"] = Part(
            "notifications", OK if notes else EMPTY, route=notifications_route, screen=home,
            data={"items": notes, "count_is_lower_bound": len(notes) >= NOTIFICATIONS_LIMIT},
            as_of=iso(),
        )

    return snapshot(env, OK, parts=parts)


async def fetch(env: AdapterEnv) -> AppSnapshot:
    try:
        return await _fetch(env)
    except UpstreamError as exc:
        return failed_snapshot(env, exc)
