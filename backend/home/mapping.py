"""Ops-Center organization to app workspace mapping.

Lookup order (User Home design, lane H1):

1. The Ops-Center org id itself. This is the provisioners' convention; for
   example Accounting-Ops creates an entitled org's workspace with the org UUID
   as its id (Accounting-Ops ``app/api/onboarding.py:126-131``).
2. A row in ``org_app_workspaces`` (``migrations/home_org_app_workspaces_20261108.sql``).
3. Otherwise the module is ``not_set_up``.

A candidate is used only when the app confirms the person is an active member
of that workspace (through the app's own workspace list or membership check),
so a wrong guess never shows another organization's records.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Optional

logger = logging.getLogger(__name__)

ORIGIN_ORG_ID = "org_id"
ORIGIN_TABLE = "org_app_workspaces"

LOOKUP_SQL = """
    SELECT app, workspace_id
    FROM org_app_workspaces
    WHERE org_id = $1::uuid
"""


@dataclass(frozen=True)
class WorkspaceCandidate:
    workspace_id: str
    origin: str


def workspace_candidates(
    org_id: str, app: str, rows: Optional[Mapping[str, str]] = None
) -> List[WorkspaceCandidate]:
    """Ordered candidates for ``app``: the org id, then the table row."""

    candidates: List[WorkspaceCandidate] = []
    org = (org_id or "").strip()
    if org:
        candidates.append(WorkspaceCandidate(org, ORIGIN_ORG_ID))
    mapped = ((rows or {}).get(app) or "").strip()
    if mapped and mapped.lower() != org.lower():
        candidates.append(WorkspaceCandidate(mapped, ORIGIN_TABLE))
    return candidates


def choose_workspace(
    candidates: Iterable[WorkspaceCandidate], member_ids: Iterable[str]
) -> Optional[WorkspaceCandidate]:
    """First candidate the person is a member of, in lookup order."""

    members = {str(value).strip().lower() for value in member_ids if value is not None}
    for candidate in candidates:
        if candidate.workspace_id.strip().lower() in members:
            return candidate
    return None


def _is_missing_relation(exc: BaseException) -> bool:
    return getattr(exc, "sqlstate", None) in {"42P01", "42703"} or type(exc).__name__ in {
        "UndefinedTableError",
        "UndefinedColumnError",
    }


async def load_workspace_rows(conn: Any, org_id: str) -> Dict[str, str]:
    """``{app: workspace_id}`` for one org. Empty when the table is not migrated
    yet or the lookup fails; the org id candidate still applies then."""

    try:
        rows = await conn.fetch(LOOKUP_SQL, org_id)
    except Exception as exc:  # noqa: BLE001 - the mapping must never break the home
        if _is_missing_relation(exc):
            logger.info("home state: org_app_workspaces is not migrated yet")
        else:
            logger.warning("home state: workspace mapping lookup failed (%s)", type(exc).__name__)
        return {}
    mapping: Dict[str, str] = {}
    for row in rows or []:
        try:
            app = str(row["app"]).strip()
            workspace = str(row["workspace_id"]).strip()
        except (KeyError, TypeError, IndexError):
            continue
        if app and workspace:
            mapping[app] = workspace
    return mapping
