"""Project-Ops adapter.

Read from Project-Ops ``origin/main`` (ffc5bd5). All routes sit under the global
``/api/v1`` prefix and take only ``Authorization: Bearer``
(``backend/src/auth/strategies/jwt.strategy.ts``); a Keycloak token must carry
an ``azp``/``aud`` in ``KEYCLOAK_EXPECTED_AUDIENCES`` (same file, :400-428).

* ``GET /api/v1/auth/profile`` (``backend/src/auth/auth.controller.ts:37-46``):
  the caller's Project-Ops user (``id``, ``role`` ADMIN|MANAGER|STAFF|CLIENT)
  and ``workspaces: [{workspaceId, slug, displayName, role, isDefault}]``
  (``auth.service.ts`` getProfile; ``common/workspace/membership.service.ts:99-124``).
  Used to confirm the mapped workspace. It is empty while
  ``PROJECT_OPS_TENANCY_ENABLED`` is off (``auth.service.ts:98-107``).
* ``GET /api/v1/tasks/my-tasks`` (``backend/src/tasks/tasks.controller.ts:90-95``,
  ``tasks.service.ts:1352-1400``): the caller's own tasks, every status, not
  paged. Rows carry ``id, title, status, priority, dueDate, completedAt``
  (``prisma/schema.prisma:693-723``) and ``project{id, projectNumber, title,
  status}``. ``dueDate`` uses the UTC-midnight date-only convention
  (``tasks.service.ts:462-470``). ``GET /tasks?assignedToId=`` needs the
  Project-Ops user id, so the caller's own list is used instead.
* ``GET /api/v1/triage/proposals?status=PENDING&limit=N``
  (``backend/src/triage/triage.controller.ts:83-92``, ``triage.service.ts:674-689``,
  ``dto/triage-proposals.dto.ts:155-178``): an array (no total) of pending
  proposals with ``id, proposedTitle, proposedPriority, rawText, owner,
  sourceType, reasoning, createdAt, proposedProject{projectNumber, title}``
  (``schema.prisma:1063-1107``). Ruling needs ADMIN, MANAGER or STAFF
  (``triage.controller.ts:94-121``), so it is fetched for those roles only.

The workspace is selected with ``X-Workspace-Id``
(``common/workspace/workspace-membership.guard.ts``). Screens (``frontend/app``):
``/dashboard/my-tasks``, ``/dashboard/tasks/{id}``, ``/dashboard/triage``.
"""

from __future__ import annotations

import asyncio
from datetime import time, timezone
from typing import Any, Dict

from ..mapping import choose_workspace
from .base import (
    EMPTY,
    NOT_ENTITLED,
    OK,
    AdapterEnv,
    AppSnapshot,
    Part,
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
    raise_if_reauth,
    short,
    snapshot,
)

PROFILE_ROUTE = "/api/v1/auth/profile"
MY_TASKS_ROUTE = "/api/v1/tasks/my-tasks"
TRIAGE_ROUTE = "/api/v1/triage/proposals"
TRIAGE_LIMIT = 50
RULING_ROLES = frozenset({"ADMIN", "MANAGER", "STAFF"})
DONE_STATUSES = frozenset({"COMPLETED", "CANCELLED"})


def normalize_task(row: Dict[str, Any], env: AdapterEnv) -> Dict[str, Any]:
    due = parse_iso(row.get("dueDate"))
    all_day = bool(due) and due.astimezone(timezone.utc).time() == time(0, 0)
    task_id = str(row.get("id") or "")
    project = row.get("project") if isinstance(row.get("project"), dict) else {}
    return {
        "id": task_id,
        "title": short(row.get("title")) or "Untitled task",
        "status": str(row.get("status") or "").upper(),
        "priority": row.get("priority"),
        "due": due,
        "all_day": all_day,
        "completed_at": parse_iso(row.get("completedAt")),
        "project": short(project.get("title")),
        "href": env.screen(f"/dashboard/tasks/{path_segment(task_id)}") if task_id else None,
    }


def normalize_proposal(row: Dict[str, Any]) -> Dict[str, Any]:
    project = row.get("proposedProject") if isinstance(row.get("proposedProject"), dict) else {}
    return {
        "id": str(row.get("id") or ""),
        "title": short(row.get("proposedTitle")) or "Proposed task",
        "priority": row.get("proposedPriority"),
        "source_type": str(row.get("sourceType") or ""),
        "owner": short(row.get("owner"), 80),
        "raw_text": row.get("rawText"),
        "reasoning": row.get("reasoning"),
        "created_at": parse_iso(row.get("createdAt")),
        "project": short(project.get("title")),
    }


async def _fetch(env: AdapterEnv) -> AppSnapshot:
    profile = await get_profile(env)
    workspaces = profile.get("workspaces") if isinstance(profile.get("workspaces"), list) else []
    chosen = choose_workspace(env.candidates, member_ids(workspaces, "workspaceId"))
    if chosen is None:
        return not_set_up_snapshot(env, link_note("Project-Ops"))

    role = str(profile.get("role") or "").upper()
    headers = {"X-Workspace-Id": chosen.workspace_id}
    can_rule = role in RULING_ROLES
    calls = [get_json(env, MY_TASKS_ROUTE, headers=headers)]
    if can_rule:
        calls.append(
            get_json(
                env, TRIAGE_ROUTE, params={"status": "PENDING", "limit": TRIAGE_LIMIT}, headers=headers
            )
        )
    results = await asyncio.gather(*calls, return_exceptions=True)
    raise_if_reauth(results)

    parts: Dict[str, Part] = {}
    tasks_screen = env.screen("/dashboard/my-tasks")
    tasks_result = results[0]
    if isinstance(tasks_result, BaseException):
        parts["my_tasks"] = part_from_error("my_tasks", tasks_result, MY_TASKS_ROUTE, tasks_screen)
    else:
        rows = tasks_result if isinstance(tasks_result, list) else []
        tasks = [normalize_task(row, env) for row in rows if isinstance(row, dict)]
        parts["my_tasks"] = Part(
            "my_tasks", OK if tasks else EMPTY, route=MY_TASKS_ROUTE, screen=tasks_screen,
            data=tasks, as_of=iso(),
        )

    triage_route = f"{TRIAGE_ROUTE}?status=PENDING&limit={TRIAGE_LIMIT}"
    triage_screen = env.screen("/dashboard/triage")
    if not can_rule:
        parts["triage"] = Part(
            "triage", NOT_ENTITLED, route=triage_route, screen=triage_screen, as_of=iso(),
            note="Ruling on proposed tasks needs a staff role in Project-Ops.",
        )
    elif isinstance(results[1], BaseException):
        parts["triage"] = part_from_error("triage", results[1], triage_route, triage_screen)
    else:
        rows = results[1] if isinstance(results[1], list) else []
        proposals = [normalize_proposal(row) for row in rows if isinstance(row, dict)]
        parts["triage"] = Part(
            "triage", OK if proposals else EMPTY, route=triage_route, screen=triage_screen,
            data={
                "items": proposals,
                "count": len(proposals),
                "count_is_lower_bound": len(proposals) >= TRIAGE_LIMIT,
            },
            as_of=iso(),
        )

    return snapshot(
        env, OK, workspace=chosen.workspace_id, workspace_origin=chosen.origin, role=role or None,
        parts=parts,
    )


async def get_profile(env: AdapterEnv) -> Dict[str, Any]:
    profile = await get_json(env, PROFILE_ROUTE)
    if not isinstance(profile, dict):
        raise UpstreamError("error")
    return profile


async def fetch(env: AdapterEnv) -> AppSnapshot:
    try:
        return await _fetch(env)
    except UpstreamError as exc:
        return failed_snapshot(env, exc)
