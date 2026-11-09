"""Org to workspace lookup order: the org id, then org_app_workspaces, else not set up."""

from __future__ import annotations

import pytest

from home.mapping import (
    ORIGIN_ORG_ID,
    ORIGIN_TABLE,
    WorkspaceCandidate,
    choose_workspace,
    load_workspace_rows,
    workspace_candidates,
)
from homekit import ORG_ID, FakeSuite, load, make_ctx, make_providers, module_by_id, source_for, suite_routes
from home.aggregator import build_home_state

MAPPED = "b7e4c2d0-1111-4222-8333-444455556666"


def test_candidates_put_the_org_id_first_then_the_table_row():
    candidates = workspace_candidates(ORG_ID, "project-ops", {"project-ops": MAPPED})
    assert candidates == [
        WorkspaceCandidate(ORG_ID, ORIGIN_ORG_ID),
        WorkspaceCandidate(MAPPED, ORIGIN_TABLE),
    ]


def test_candidates_without_a_row_or_with_a_duplicate_row():
    assert workspace_candidates(ORG_ID, "project-ops", {}) == [WorkspaceCandidate(ORG_ID, ORIGIN_ORG_ID)]
    assert workspace_candidates(ORG_ID, "project-ops", {"email-ops": MAPPED}) == [
        WorkspaceCandidate(ORG_ID, ORIGIN_ORG_ID)
    ]
    assert workspace_candidates(ORG_ID, "project-ops", {"project-ops": ORG_ID.upper()}) == [
        WorkspaceCandidate(ORG_ID, ORIGIN_ORG_ID)
    ]


def test_choose_prefers_the_org_id_when_both_are_memberships():
    candidates = workspace_candidates(ORG_ID, "email-ops", {"email-ops": MAPPED})
    chosen = choose_workspace(candidates, [MAPPED, ORG_ID])
    assert chosen.workspace_id == ORG_ID and chosen.origin == ORIGIN_ORG_ID


def test_choose_falls_back_to_the_table_row_then_to_nothing():
    candidates = workspace_candidates(ORG_ID, "email-ops", {"email-ops": MAPPED})
    chosen = choose_workspace(candidates, [MAPPED.upper(), "unrelated"])
    assert chosen.workspace_id == MAPPED and chosen.origin == ORIGIN_TABLE
    assert choose_workspace(candidates, ["unrelated"]) is None
    assert choose_workspace(candidates, []) is None


class RowsConn:
    def __init__(self, rows=None, error=None):
        self.rows, self.error, self.params = rows or [], error, None

    async def fetch(self, query, *params):
        self.params = params
        if self.error:
            raise self.error
        return self.rows


class MissingTable(Exception):
    sqlstate = "42P01"


@pytest.mark.asyncio
async def test_load_rows_reads_one_org_and_tolerates_a_missing_table():
    conn = RowsConn([{"app": "meeting-ops", "workspace_id": "rivergreen-coffee"},
                     {"app": "email-ops", "workspace_id": MAPPED}])
    assert await load_workspace_rows(conn, ORG_ID) == {"meeting-ops": "rivergreen-coffee", "email-ops": MAPPED}
    assert conn.params == (ORG_ID,)
    assert await load_workspace_rows(RowsConn(error=MissingTable("no table")), ORG_ID) == {}
    assert await load_workspace_rows(RowsConn(error=RuntimeError("db down")), ORG_ID) == {}


def profile_with(*workspace_ids):
    profile = load("po_profile")
    profile["workspaces"] = [
        {"workspaceId": ws, "slug": f"ws-{i}", "displayName": f"Workspace {i}", "role": "MEMBER",
         "isDefault": i == 0}
        for i, ws in enumerate(workspace_ids)
    ]
    return profile


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "memberships, expected_header, expected_origin",
    [
        ((ORG_ID, MAPPED), ORG_ID, "org_id"),
        ((MAPPED,), MAPPED, "org_app_workspaces"),
        ((), None, None),
    ],
)
async def test_lookup_order_end_to_end(memberships, expected_header, expected_origin):
    routes = suite_routes()
    routes["/api/v1/auth/profile"] = profile_with(*memberships)
    suite = FakeSuite(routes)
    providers = make_providers(suite, rows={"project-ops": MAPPED, "meeting-ops": "rivergreen-coffee"})
    document = await build_home_state(make_ctx(), providers)
    today = module_by_id(document, "today")
    project = source_for(today, "project-ops")
    task_calls = [r for r in suite.calls if r.url.path == "/api/v1/tasks/my-tasks"]
    if expected_header is None:
        assert project["status"] == "not_set_up"
        assert task_calls == []
    else:
        assert project["status"] == "ok"
        assert project["workspace"] == expected_header
        assert {r.headers["x-workspace-id"] for r in task_calls} == {expected_header}
