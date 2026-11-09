"""Module builders: app snapshots in, section-g modules out.

Every module carries ``id``, ``title``, ``status`` (ok, empty, not_set_up,
not_entitled, unavailable), ``reason`` when unavailable (reauth, timeout,
error), ``as_of`` and ``source``: one entry per route that fed it, each with
the app, its own status, the public URL of the exact screen that shows the
number, the API route (a path, never a host) and the workspace used.

A module is ``ok`` or ``empty`` as soon as one of its sources answered; it is
marked ``partial`` when another source did not. Counts that could not be read
are ``null``, never zero.
"""

from __future__ import annotations

from collections import Counter
from datetime import date, datetime, time, timezone, tzinfo
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .adapters.base import (
    EMPTY,
    ERROR,
    NOT_ENTITLED,
    NOT_SET_UP,
    OK,
    REAUTH,
    TIMEOUT,
    UNAVAILABLE,
    AppSnapshot,
    Part,
    iso,
    parse_iso,
    short,
    text,
)
from .context import HomeContext
from .safety import join_url, public_url

MAX_ITEMS_PER_SOURCE = 10
MAX_TODAY_ITEMS_PER_SOURCE = 20
RECENT_MEETINGS = 5
MAX_SINCE_ITEMS = 10
MAX_MONEY_PRIORITIES = 3

TITLES = {
    "needs_you": "Needs you",
    "today": "Today",
    "since_last_visit": "Since you were last here",
    "apps": "Your apps",
    "recent_meetings": "Recent meetings",
    "watched_topics": "Watched topics",
    "money": "Money",
    "usage": "AI usage and credits",
}

DONE_TASK_STATUSES = frozenset({"COMPLETED", "CANCELLED"})
ANSWERED = (OK, EMPTY)

# my-apps catalog slug -> app key used by the adapters.
SLUG_TO_APP = {
    "project-ops": "project-ops",
    "meeting-ops": "meeting-ops",
    "email-ops": "email-ops",
    "accounting-ops": "accounting-ops",
    "customer-ops": "customer-ops",
    "center-deep-research": "center-deep",
}


# --------------------------------------------------------------------------- #
# Shared helpers
# --------------------------------------------------------------------------- #


def _iso_or_none(value: Any) -> Optional[str]:
    parsed = value if isinstance(value, datetime) else parse_iso(value)
    return iso(parsed) if parsed else None


def _compact(item: Dict[str, Any], keep: Iterable[str] = ()) -> Dict[str, Any]:
    keep = set(keep)
    return {key: value for key, value in item.items() if value is not None or key in keep}


def _open_action(label: str, href: Optional[str]) -> List[Dict[str, str]]:
    return [{"id": "open", "label": label, "href": href}] if href else []


def source_entry(snap: AppSnapshot, part: Part, ctx: HomeContext) -> Dict[str, Any]:
    """One ``source`` row for a module: which route of which app fed it."""

    status = part.status
    if status == NOT_ENTITLED and snap.status == NOT_ENTITLED:
        url = f"{ctx.ops_center_web}/marketplace"
    else:
        url = part.screen or snap.web_base
    entry: Dict[str, Any] = {
        "app": snap.app,
        "label": snap.label,
        "status": status,
        "as_of": part.as_of or snap.as_of,
        "url": url,
        "route": part.route,
        "workspace": snap.workspace,
    }
    if status == UNAVAILABLE:
        entry["reason"] = part.reason or ERROR
    if part.note:
        entry["note"] = part.note
    return entry


def ops_center_source(part: Part, ctx: HomeContext) -> Dict[str, Any]:
    entry: Dict[str, Any] = {
        "app": "ops-center",
        "label": "Ops-Center",
        "status": part.status,
        "as_of": part.as_of or iso(),
        "url": part.screen,
        "route": part.route,
        "workspace": ctx.org_id,
    }
    if part.status == UNAVAILABLE:
        entry["reason"] = part.reason or ERROR
    if part.note:
        entry["note"] = part.note
    return entry


def combine(sources: List[Dict[str, Any]], has_items: bool) -> Tuple[str, Optional[str], bool]:
    """Module status from its sources: (status, reason, partial)."""

    statuses = [source["status"] for source in sources]
    unavailable = [source for source in sources if source["status"] == UNAVAILABLE]
    if any(status in ANSWERED for status in statuses):
        return (OK if has_items else EMPTY), None, bool(unavailable)
    if unavailable:
        reasons = {source.get("reason") for source in unavailable}
        reason = REAUTH if REAUTH in reasons else TIMEOUT if TIMEOUT in reasons else ERROR
        return UNAVAILABLE, reason, False
    if statuses and all(status == NOT_ENTITLED for status in statuses):
        return NOT_ENTITLED, None, False
    return NOT_SET_UP, None, False


def module(
    module_id: str,
    sources: List[Dict[str, Any]],
    has_items: bool,
    *,
    override: Optional[Tuple[str, Optional[str]]] = None,
    **body: Any,
) -> Dict[str, Any]:
    status, reason, partial = combine(sources, has_items)
    if override is not None:
        status, reason = override
        partial = False
    result: Dict[str, Any] = {
        "id": module_id,
        "title": TITLES[module_id],
        "status": status,
        "as_of": max((source["as_of"] for source in sources if source.get("as_of")), default=iso()),
        "source": sources,
    }
    if status == UNAVAILABLE:
        result["reason"] = reason or ERROR
    if partial:
        result["partial"] = True
    result.update(body)
    return result


def _local_date(moment: datetime, tz: tzinfo) -> date:
    return moment.astimezone(tz).date()


def _task_local_date(task: Dict[str, Any], tz: tzinfo) -> Optional[date]:
    due = task.get("due")
    if not isinstance(due, datetime):
        return None
    # Date-only due dates are stored at UTC midnight (Project-Ops convention).
    if task.get("all_day"):
        return due.astimezone(timezone.utc).date()
    return _local_date(due, tz)


def project_task_counts(part: Part, ctx: HomeContext) -> Tuple[List[Dict[str, Any]], int]:
    """(open tasks due today, number of open overdue tasks) for the person."""

    today = _local_date(ctx.now, ctx.tz)
    due_today: List[Dict[str, Any]] = []
    overdue = 0
    for task in part.data or []:
        if task.get("status") in DONE_TASK_STATUSES:
            continue
        due_date = _task_local_date(task, ctx.tz)
        if due_date is None:
            continue
        if due_date == today:
            due_today.append(task)
        elif due_date < today:
            overdue += 1
    return due_today, overdue


def followups_due(part: Part, ctx: HomeContext) -> List[Dict[str, Any]]:
    today = _local_date(ctx.now, ctx.tz)
    data = part.data if isinstance(part.data, dict) else {}
    due = []
    for row in data.get("items") or []:
        moment = row.get("next_action_at")
        if row.get("is_lost") or not isinstance(moment, datetime):
            continue
        if _local_date(moment, ctx.tz) <= today:
            due.append(row)
    return due


def _humanize(value: str) -> str:
    return " ".join(value.replace("_", " ").replace("-", " ").split()).lower()


# --------------------------------------------------------------------------- #
# Needs you
# --------------------------------------------------------------------------- #


def _email_item(row: Dict[str, Any], part: Part) -> Dict[str, Any]:
    href = part.screen
    title = row.get("subject") or short(row.get("summary")) or "Email draft waiting for approval"
    return _compact(
        {
            "id": f"eo:draft:{row.get('id')}",
            "app": "email-ops",
            "kind": "approval",
            "scope": "mine",
            "title": title,
            "origin": "third_party",
            "proposed_by": {"kind": "agent", "name": row.get("drafted_by") or "Email-Ops agent"},
            "created_at": _iso_or_none(row.get("created_at")),
            "summary": text(row.get("summary"), "system"),
            "preview": text(row.get("preview"), "third_party"),
            "to": row.get("to"),
            "sends_at": _iso_or_none(row.get("sends_at")),
            "href": href,
            "actions": _open_action("Review", href),
        },
        keep=("href",),
    )


def _approval_item(row: Dict[str, Any], part: Part) -> Dict[str, Any]:
    href = part.screen
    subject = _humanize(row.get("subject_type") or "") or "item"
    title = f"Approve {subject}"
    if row.get("amount"):
        title += f" of {row['amount']}" + (f" {row['currency']}" if row.get("currency") else "")
    if row.get("entity"):
        title += f" for {row['entity']}"
    return _compact(
        {
            "id": f"ao:approval:{row.get('id')}",
            "app": "accounting-ops",
            "kind": "approval",
            "scope": "mine",
            "title": title,
            "origin": "system",
            "proposed_by": {"kind": "agent", "name": row.get("requested_by") or "Accounting-Ops"},
            "created_at": _iso_or_none(row.get("created_at")),
            "summary": text(row.get("reasoning"), "third_party"),
            "amount": row.get("amount"),
            "currency": row.get("currency"),
            "entity": row.get("entity"),
            "href": href,
            "actions": _open_action("Open", href),
        },
        keep=("href",),
    )


def _proposal_item(row: Dict[str, Any], part: Part) -> Dict[str, Any]:
    href = part.screen
    proposer = "Meeting-Ops action item" if row.get("source_type") == "MEETING_OPS" else "Project-Ops triage"
    return _compact(
        {
            "id": f"po:triage:{row.get('id')}",
            "app": "project-ops",
            "kind": "proposal",
            "scope": "workspace",
            "title": row.get("title") or "Proposed task",
            "origin": "third_party",
            "proposed_by": {"kind": "agent", "name": proposer},
            "created_at": _iso_or_none(row.get("created_at")),
            "summary": text(row.get("reasoning"), "system"),
            "preview": text(row.get("raw_text"), "third_party"),
            "project": row.get("project"),
            "priority": row.get("priority"),
            "href": href,
            "actions": _open_action("Review", href),
        },
        keep=("href",),
    )


def build_needs_you(ctx: HomeContext, snaps: Dict[str, AppSnapshot]) -> Dict[str, Any]:
    email, accounting, project = snaps["email-ops"], snaps["accounting-ops"], snaps["project-ops"]
    inbox, approvals, triage = email.part("agent_inbox"), accounting.part("approvals"), project.part("triage")

    items: List[Dict[str, Any]] = []
    count = 0
    lower_bound = False
    for part, make in ((inbox, _email_item), (approvals, _approval_item), (triage, _proposal_item)):
        if part.status not in ANSWERED or not isinstance(part.data, dict):
            continue
        rows = part.data.get("items") or []
        count += int(part.data.get("count") or len(rows))
        lower_bound = lower_bound or bool(part.data.get("count_is_lower_bound"))
        items.extend(make(row, part) for row in rows[:MAX_ITEMS_PER_SOURCE])
    items.sort(key=lambda item: item.get("created_at") or "", reverse=True)

    sources = [
        source_entry(email, inbox, ctx),
        source_entry(accounting, approvals, ctx),
        source_entry(project, triage, ctx),
    ]
    return module(
        "needs_you", sources, count > 0 or bool(items),
        count=count, count_is_lower_bound=lower_bound, items=items,
    )


# --------------------------------------------------------------------------- #
# Today
# --------------------------------------------------------------------------- #


def _task_item(task: Dict[str, Any], tz: tzinfo) -> Dict[str, Any]:
    due = task.get("due")
    all_day = bool(task.get("all_day"))
    due_date = _task_local_date(task, tz)
    return _compact(
        {
            "id": f"po:task:{task.get('id')}",
            "app": "project-ops",
            "kind": "task",
            "title": task.get("title"),
            "origin": "system",
            "due_date": due_date.isoformat() if due_date else None,
            "due_at": None if all_day else _iso_or_none(due),
            "all_day": all_day,
            "priority": task.get("priority"),
            "status": task.get("status"),
            "project": task.get("project"),
            "href": task.get("href"),
            "actions": _open_action("Open", task.get("href")),
        },
        keep=("href",),
    )


def _followup_item(row: Dict[str, Any], ctx: HomeContext) -> Dict[str, Any]:
    moment = row.get("next_action_at")
    today = _local_date(ctx.now, ctx.tz)
    name = row.get("name")
    return _compact(
        {
            "id": f"co:followup:{row.get('id')}",
            "app": "customer-ops",
            "kind": "follow_up",
            "title": f"Follow up with {name}" if name else "Customer follow-up",
            "origin": "system",
            "due_at": _iso_or_none(moment),
            "all_day": False,
            "overdue": _local_date(moment, ctx.tz) < today,
            "stage": row.get("stage"),
            "priority": row.get("priority"),
            "href": row.get("href"),
            "actions": _open_action("Open", row.get("href")),
        },
        keep=("href",),
    )


def build_today(ctx: HomeContext, snaps: Dict[str, AppSnapshot]) -> Dict[str, Any]:
    project, customers = snaps["project-ops"], snaps["customer-ops"]
    tasks_part, followups_part = project.part("my_tasks"), customers.part("followups")
    today = _local_date(ctx.now, ctx.tz)

    items: List[Dict[str, Any]] = []
    counts: Dict[str, Optional[int]] = {
        "tasks_due_today": None,
        "tasks_overdue": None,
        "follow_ups_due": None,
    }
    if tasks_part.status in ANSWERED:
        due_today, overdue = project_task_counts(tasks_part, ctx)
        counts["tasks_due_today"] = len(due_today)
        counts["tasks_overdue"] = overdue
        items.extend(_task_item(task, ctx.tz) for task in due_today[:MAX_TODAY_ITEMS_PER_SOURCE])
    if followups_part.status in ANSWERED:
        due = followups_due(followups_part, ctx)
        counts["follow_ups_due"] = len(due)
        due.sort(key=lambda row: row["next_action_at"])
        items.extend(_followup_item(row, ctx) for row in due[:MAX_TODAY_ITEMS_PER_SOURCE])

    # All-day tasks first, then timed items in time order.
    items.sort(key=lambda item: (0 if item.get("all_day") else 1, item.get("due_at") or ""))
    sources = [source_entry(project, tasks_part, ctx), source_entry(customers, followups_part, ctx)]
    return module("today", sources, bool(items), date=today.isoformat(), counts=counts, items=items)


# --------------------------------------------------------------------------- #
# Since you were last here
# --------------------------------------------------------------------------- #


def build_since_last_visit(
    ctx: HomeContext, snaps: Dict[str, AppSnapshot], cursor_part: Part
) -> Dict[str, Any]:
    meetings, project, research = snaps["meeting-ops"], snaps["project-ops"], snaps["center-deep"]
    sessions_part = meetings.part("sessions")
    tasks_part = project.part("my_tasks")
    notes_part = research.part("notifications")
    sources = [
        ops_center_source(cursor_part, ctx),
        source_entry(meetings, sessions_part, ctx),
        source_entry(project, tasks_part, ctx),
        source_entry(research, notes_part, ctx),
    ]
    counts: Dict[str, Optional[int]] = {
        "meetings_summarized": None,
        "tasks_closed": None,
        "monitor_updates": None,
    }

    if cursor_part.status == UNAVAILABLE:
        return module(
            "since_last_visit", sources, False, override=(UNAVAILABLE, cursor_part.reason or ERROR),
            cursor=None, counts=counts, items=[],
        )
    cursor = parse_iso(cursor_part.data) if cursor_part.status == OK else None
    if cursor is None:
        return module(
            "since_last_visit", sources, False, override=(EMPTY, None),
            cursor=None, counts=counts, items=[],
            note="This is your first visit, so there is nothing to compare yet.",
        )

    rows: List[Tuple[datetime, Dict[str, Any]]] = []
    capped: List[str] = []
    if sessions_part.status in ANSWERED:
        data = sessions_part.data if isinstance(sessions_part.data, dict) else {}
        recent = [s for s in data.get("items") or [] if s.get("created_at") and s["created_at"] > cursor]
        summarized = [s for s in recent if s.get("has_summary")]
        counts["meetings_summarized"] = len(summarized)
        if recent and len(recent) >= int(data.get("limit") or 0) > 0:
            capped.append("meetings_summarized")
        for session in summarized:
            rows.append((session["created_at"], {
                "id": f"mo:session:{session['id']}", "app": "meeting-ops", "kind": "meeting_summarized",
                "title": session["title"], "origin": "system", "at": iso(session["created_at"]),
                "href": session.get("href"),
            }))
    if tasks_part.status in ANSWERED:
        closed = [
            task for task in tasks_part.data or []
            if task.get("status") == "COMPLETED"
            and isinstance(task.get("completed_at"), datetime)
            and task["completed_at"] > cursor
        ]
        counts["tasks_closed"] = len(closed)
        for task in closed:
            rows.append((task["completed_at"], {
                "id": f"po:task:{task['id']}", "app": "project-ops", "kind": "task_closed",
                "title": task["title"], "origin": "system", "at": iso(task["completed_at"]),
                "href": task.get("href"),
            }))
    if notes_part.status in ANSWERED:
        data = notes_part.data if isinstance(notes_part.data, dict) else {}
        fresh = [n for n in data.get("items") or [] if n.get("created_at") and n["created_at"] > cursor]
        counts["monitor_updates"] = len(fresh)
        if fresh and data.get("count_is_lower_bound") and len(fresh) == len(data.get("items") or []):
            capped.append("monitor_updates")
        for note in fresh:
            rows.append((note["created_at"], {
                "id": f"cdr:notification:{note['id']}", "app": "center-deep", "kind": "monitor_update",
                "title": note["title"], "origin": "system", "at": iso(note["created_at"]),
                "href": note.get("run_href"),
            }))

    rows.sort(key=lambda pair: pair[0], reverse=True)
    items = [_compact(row, keep=("href",)) for _, row in rows[:MAX_SINCE_ITEMS]]
    has_changes = any(value for value in counts.values())
    extra: Dict[str, Any] = {"cursor": iso(cursor), "counts": counts, "items": items}
    if capped:
        extra["counts_capped"] = capped
    return module("since_last_visit", sources, has_changes, **extra)


# --------------------------------------------------------------------------- #
# Your apps
# --------------------------------------------------------------------------- #


def safe_companion(companion: Any, ring: str) -> Optional[Dict[str, Any]]:
    """The card's Connect your AI block, kept only when its MCP URL is public
    and on this ring."""

    if not isinstance(companion, dict):
        return None
    mcp_url = public_url(str(companion.get("mcp_url") or ""), ring)
    if not mcp_url:
        return None

    def links(key: str) -> List[Dict[str, str]]:
        safe = []
        for link in companion.get(key) or []:
            if not isinstance(link, dict):
                continue
            url = public_url(str(link.get("url") or ""), ring)
            if url:
                safe.append({"label": short(link.get("label"), 60) or "Download", "url": url})
        return safe

    return _compact({
        "label": short(companion.get("label"), 60) or "Connect your AI",
        "mcp_url": mcp_url,
        "claude_code_command": companion.get("claude_code_command"),
        "client_config": companion.get("client_config"),
        "chatgpt_url": public_url(str(companion.get("chatgpt_url") or ""), ring) or mcp_url,
        "desktop": links("desktop"),
        "mobile": links("mobile"),
    })


def _number(label: str, value: Optional[int], href: Optional[str], singular: Optional[str] = None
            ) -> Optional[Dict[str, Any]]:
    if value is None:
        return None
    shown = singular if (singular and value == 1) else label
    return _compact({"label": shown, "value": value, "href": href}, keep=("href",))


def app_numbers(app: Optional[str], snap: Optional[AppSnapshot], ctx: HomeContext) -> List[Dict[str, Any]]:
    if app is None or snap is None or snap.status != OK:
        return []
    numbers: List[Optional[Dict[str, Any]]] = []
    if app == "project-ops":
        part = snap.part("my_tasks")
        if part.status in ANSWERED:
            due_today, overdue = project_task_counts(part, ctx)
            numbers.append(_number("due today", len(due_today), part.screen))
            numbers.append(_number("overdue", overdue, part.screen))
    elif app == "email-ops":
        part = snap.part("agent_inbox")
        if part.status in ANSWERED:
            numbers.append(_number("drafts waiting", int(part.data.get("count") or 0), part.screen,
                                   "draft waiting"))
    elif app == "meeting-ops":
        part = snap.part("action_items")
        if part.status in ANSWERED:
            numbers.append(_number("open action items", int(part.data.get("count") or 0), part.screen,
                                   "open action item"))
    elif app == "customer-ops":
        part = snap.part("followups")
        if part.status in ANSWERED:
            numbers.append(_number("follow-ups due", len(followups_due(part, ctx)), part.screen,
                                   "follow-up due"))
    elif app == "accounting-ops":
        part = snap.part("approvals")
        if part.status in ANSWERED:
            numbers.append(_number("approvals waiting", int(part.data.get("count") or 0), part.screen,
                                   "approval waiting"))
    return [number for number in numbers if number is not None]


def _live(snap: AppSnapshot) -> Dict[str, Any]:
    live: Dict[str, Any] = {"status": snap.status}
    if snap.status == UNAVAILABLE:
        live["reason"] = snap.reason or ERROR
    if snap.note:
        live["note"] = snap.note
    return live


def build_apps(ctx: HomeContext, snaps: Dict[str, AppSnapshot], apps_part: Part) -> Dict[str, Any]:
    sources = [ops_center_source(apps_part, ctx)]
    items: List[Dict[str, Any]] = []
    if apps_part.status in ANSWERED:
        for card in apps_part.data or []:
            slug = str(card.get("slug") or "")
            app = SLUG_TO_APP.get(slug)
            snap = snaps.get(app) if app else None
            tile = _compact(
                {
                    "slug": slug,
                    "name": short(card.get("name"), 80) or slug,
                    "purpose": short(card.get("purpose"), 180),
                    "origin": "system",
                    "state": card.get("state") or "ready",
                    "open": public_url(str(card.get("launch_url") or ""), ctx.ring),
                    "connect_ai": safe_companion(card.get("companion"), ctx.ring),
                    "numbers": app_numbers(app, snap, ctx),
                    "live": _live(snap) if snap is not None else None,
                },
                keep=("open", "connect_ai"),
            )
            items.append(tile)
    return module("apps", sources, bool(items), items=items)


# --------------------------------------------------------------------------- #
# Recent meetings
# --------------------------------------------------------------------------- #


def build_recent_meetings(ctx: HomeContext, snaps: Dict[str, AppSnapshot]) -> Dict[str, Any]:
    meetings = snaps["meeting-ops"]
    sessions_part, items_part = meetings.part("sessions"), meetings.part("action_items")
    open_by_session: Optional[Counter] = None
    if items_part.status in ANSWERED:
        open_by_session = Counter(row.get("session_key") for row in items_part.data.get("items") or [])

    items: List[Dict[str, Any]] = []
    if sessions_part.status in ANSWERED:
        for session in (sessions_part.data or {}).get("items", [])[:RECENT_MEETINGS]:
            items.append(_compact(
                {
                    "id": f"mo:session:{session['id']}",
                    "app": "meeting-ops",
                    "kind": "meeting",
                    "title": session["title"],
                    "origin": "system",
                    "created_at": _iso_or_none(session.get("created_at")),
                    "duration_seconds": session.get("duration_seconds"),
                    "speakers": session.get("speakers"),
                    "status": session.get("status"),
                    "has_summary": session.get("has_summary"),
                    "open_action_items": (
                        open_by_session.get(session["id"], 0) if open_by_session is not None else None
                    ),
                    "href": session.get("href"),
                    "actions": _open_action("Open", session.get("href")),
                },
                keep=("href", "open_action_items"),
            ))
    sources = [source_entry(meetings, sessions_part, ctx), source_entry(meetings, items_part, ctx)]
    return module("recent_meetings", sources, bool(items), items=items)


# --------------------------------------------------------------------------- #
# Watched topics
# --------------------------------------------------------------------------- #


def build_watched_topics(ctx: HomeContext, snaps: Dict[str, AppSnapshot]) -> Dict[str, Any]:
    research = snaps["center-deep"]
    briefs_part, notes_part = research.part("briefs"), research.part("notifications")

    latest_unread: Dict[str, Dict[str, Any]] = {}
    if notes_part.status in ANSWERED:
        for note in notes_part.data.get("items") or []:  # newest first
            brief_id = note.get("brief_id")
            if brief_id and not note.get("read") and brief_id not in latest_unread:
                latest_unread[brief_id] = note

    items: List[Dict[str, Any]] = []
    if briefs_part.status in ANSWERED:
        watched = [
            brief for brief in briefs_part.data or []
            if brief.get("kind") != "situation" and brief.get("enabled")
        ]
        watched.sort(key=lambda brief: (brief["title"].casefold(), brief["id"]))
        for brief in watched:
            note = latest_unread.get(brief["id"])
            changed = bool(note and note.get("changed"))
            items.append(_compact(
                {
                    "monitor_id": brief["id"],
                    "app": "center-deep",
                    "title": brief["title"],
                    "origin": "system",
                    "changed": changed,
                    "unread": note is not None,
                    "cadence": brief.get("cadence"),
                    "last_run_at": _iso_or_none(brief.get("last_run_at")),
                    "next_run_at": _iso_or_none(brief.get("next_run_at")),
                    "drift_line": text(note.get("line"), "third_party") if changed else None,
                    "href": brief.get("href"),
                    "run_href": note.get("run_href") if note else None,
                    "actions": _open_action("Open run" if note and note.get("run_href") else "Open",
                                            (note or {}).get("run_href") or brief.get("href")),
                },
                keep=("href",),
            ))
    sources = [source_entry(research, briefs_part, ctx), source_entry(research, notes_part, ctx)]
    return module(
        "watched_topics", sources, bool(items),
        changed_count=sum(1 for item in items if item.get("changed")), items=items,
    )


# --------------------------------------------------------------------------- #
# Money (org owners and admins only)
# --------------------------------------------------------------------------- #


def _app_link(origin: Optional[str], href: Any, ring: str) -> Optional[str]:
    if not isinstance(href, str) or not href.strip():
        return None
    href = href.strip()
    if href.startswith("/") and not href.startswith("//"):
        return join_url(origin, href)
    return public_url(href, ring)


def build_money(ctx: HomeContext, snaps: Dict[str, AppSnapshot]) -> Dict[str, Any]:
    accounting = snaps["accounting-ops"]
    brief_part, invoices_part = accounting.part("cfo_brief"), accounting.part("invoices")
    body: Dict[str, Any] = {
        "cash": None,
        "runway_months": None,
        "monthly_burn": None,
        "action_required_total": None,
        "summary_line": None,
        "invoiced_not_due": None,
        "items": [],
    }
    if brief_part.status in ANSWERED and isinstance(brief_part.data, dict):
        brief = brief_part.data
        cash = brief.get("cash") if isinstance(brief.get("cash"), dict) else {}
        body["cash"] = _compact({
            "configured": bool(cash.get("configured")),
            "headline": text(cash.get("headline"), "system"),
            "detail": text(cash.get("detail"), "system"),
            "net_total": cash.get("net_total"),
            "assets_total": cash.get("assets_total"),
            "liabilities_total": cash.get("liabilities_total"),
        })
        body["runway_months"] = cash.get("months_runway")
        body["monthly_burn"] = cash.get("monthly_burn")
        try:
            body["action_required_total"] = int(brief.get("action_required_total") or 0)
        except (TypeError, ValueError):
            body["action_required_total"] = None
        body["summary_line"] = text(brief.get("summary_line"), "system")
        body["onboarding"] = bool(brief.get("onboarding"))
        body["upstream_as_of"] = brief.get("as_of")
        if isinstance(brief.get("sources_ok"), dict):
            body["sources_ok"] = {str(k): bool(v) for k, v in brief["sources_ok"].items()}
        for priority in (brief.get("priorities") or [])[:MAX_MONEY_PRIORITIES]:
            if not isinstance(priority, dict):
                continue
            href = _app_link(accounting.web_base, priority.get("action_href"), ctx.ring)
            body["items"].append(_compact(
                {
                    "id": f"ao:priority:{priority.get('id')}",
                    "app": "accounting-ops",
                    "kind": priority.get("kind"),
                    "severity": priority.get("severity"),
                    "title": short(priority.get("headline")) or "Accounting item",
                    "origin": "system",
                    "detail": text(priority.get("detail"), "third_party"),
                    "href": href,
                    "actions": _open_action(short(priority.get("action_label"), 40) or "Open", href),
                },
                keep=("href",),
            ))
    if invoices_part.status in ANSWERED and isinstance(invoices_part.data, dict):
        body["invoiced_not_due"] = invoices_part.data
    sources = [source_entry(accounting, brief_part, ctx), source_entry(accounting, invoices_part, ctx)]
    has_items = body["cash"] is not None or body["invoiced_not_due"] is not None
    return module("money", sources, has_items, **body)


# --------------------------------------------------------------------------- #
# AI usage and credits (org owners and admins only)
# --------------------------------------------------------------------------- #


def build_usage(ctx: HomeContext, usage_part: Part) -> Dict[str, Any]:
    data = usage_part.data if isinstance(usage_part.data, dict) else {}
    sources = [ops_center_source(usage_part, ctx)]
    return module(
        "usage", sources, usage_part.status == OK,
        credits={
            "last_24_hours": data.get("last_24_hours"),
            "last_30_days": data.get("last_30_days"),
            "pool": data.get("pool"),
        },
        people_using_ai_30_days=data.get("people_using_ai_30_days"),
        services=data.get("services") or [],
    )


# --------------------------------------------------------------------------- #
# Status line
# --------------------------------------------------------------------------- #

_WORDS = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six", 7: "seven",
          8: "eight", 9: "nine", 10: "ten"}


def _count_words(value: int, lower_bound: bool = False) -> str:
    word = _WORDS.get(value, str(value))
    return f"{word} or more" if lower_bound else word


def _join(labels: List[str]) -> str:
    if len(labels) <= 1:
        return "".join(labels)
    return ", ".join(labels[:-1]) + " and " + labels[-1]


def _capital(sentence: str) -> str:
    return sentence[:1].upper() + sentence[1:]


def build_status_line(modules: List[Dict[str, Any]], generated_at: str) -> Dict[str, Any]:
    by_id = {mod["id"]: mod for mod in modules}
    needs, today = by_id["needs_you"], by_id["today"]

    needs_count: Optional[int] = needs.get("count") if needs["status"] in ANSWERED else None
    lower_bound = bool(needs.get("count_is_lower_bound"))
    due: Optional[int] = None
    if today["status"] in ANSWERED:
        counts = today.get("counts") or {}
        due = (counts.get("tasks_due_today") or 0) + (counts.get("follow_ups_due") or 0)

    reauth_labels: List[str] = []
    down_labels: List[str] = []
    for source in needs["source"] + today["source"]:
        if source["status"] != UNAVAILABLE:
            continue
        bucket = reauth_labels if source.get("reason") == REAUTH else down_labels
        if source["label"] not in bucket:
            bucket.append(source["label"])

    sentences: List[str] = []
    if needs_count is None and due is None:
        sentences.append(
            "Sign in again to refresh your apps." if reauth_labels and not down_labels
            else "Your apps could not be checked right now."
        )
    else:
        if needs_count is None:
            sentences.append(
                f"{_capital(_count_words(due))} {'thing is' if due == 1 else 'things are'} due today."
                if due else "Nothing is due today."
            )
        elif needs_count == 0:
            partial = bool(reauth_labels or down_labels)
            sentences.append("Nothing needs you" + (" in the apps that answered" if partial else "") + ".")
            if due:
                sentences.append(
                    f"{_capital(_count_words(due))} {'thing is' if due == 1 else 'things are'} due today."
                )
        else:
            plural = needs_count != 1 or lower_bound
            lead = f"{_capital(_count_words(needs_count, lower_bound))} {'things need' if plural else 'thing needs'} you"
            if due is None:
                sentences.append(lead + ".")
            elif due == 0:
                sentences.append(lead + ", then a quiet day.")
            else:
                sentences.append(lead + f", and {_count_words(due)} {'is' if due == 1 else 'are'} due today.")
        if reauth_labels:
            sentences.append(f"Sign in again to refresh {_join(reauth_labels)}.")
        if down_labels:
            sentences.append(f"{_join(down_labels)} could not be reached.")

    def lit(mod: Dict[str, Any]) -> bool:
        if mod["status"] != OK:
            return False
        if mod["id"] == "needs_you":
            return (mod.get("count") or 0) > 0
        if mod["id"] == "today":
            return bool(mod.get("items"))
        if mod["id"] == "since_last_visit":
            return any((mod.get("counts") or {}).values())
        if mod["id"] == "watched_topics":
            return (mod.get("changed_count") or 0) > 0
        if mod["id"] == "money":
            return (mod.get("action_required_total") or 0) > 0
        return False

    return {
        "text": " ".join(sentences),
        "needs_you_count": needs_count,
        "due_today_count": due,
        "as_of": generated_at,
        "dots": [{"module": mod["id"], "status": mod["status"], "lit": lit(mod)} for mod in modules],
    }
