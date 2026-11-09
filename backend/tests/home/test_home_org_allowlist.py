"""HOME_ENABLED_ORG_IDS: the home for listed organizations only.

Both routes run through the real request binding (``get_home_context``) with
the fake Ops-Center modules from ``test_home_route``; the apps are the
fictional ``FakeSuite`` hosts and the receipts are ``test_home_actions``'
in-memory table. Rivergreen Coffee Co. and every id here are fictional.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

import home_api
from home import settings
from homekit import ORG_ID, FakeSuite, suite_routes
from test_home_actions import PO_TASK, ReceiptsDB, action_routes, make_providers, post
from test_home_route import FakeConn, install_fake_ops_center, real_binding_client, session_for

OTHER_ORG = "9a8b7c6d-5e4f-4a3b-8c2d-1e0f9a8b7c6d"
NOT_FOUND = {"detail": "Not Found"}


def state_get(monkeypatch, **fake_kwargs):
    suite = FakeSuite(suite_routes())
    client, calls, conn = real_binding_client(monkeypatch, suite, session=session_for(), **fake_kwargs)
    return client.get("/api/v1/home/state"), suite, conn


def action_post(monkeypatch, **fake_kwargs):
    suite, db, conn = FakeSuite(action_routes()), ReceiptsDB(), FakeConn()
    install_fake_ops_center(monkeypatch, session=session_for(), conn=conn, **fake_kwargs)
    app = FastAPI()
    app.include_router(home_api.router)
    app.dependency_overrides[home_api.get_action_providers] = lambda: make_providers(suite, db)
    return post(TestClient(app), "project-ops", f"po:task:{PO_TASK}", "done"), suite, db, conn


def test_the_list_is_read_by_name_without_case_or_spaces(monkeypatch):
    for unset in (None, "", "  ", " , ,"):
        if unset is None:
            monkeypatch.delenv("HOME_ENABLED_ORG_IDS", raising=False)
        else:
            monkeypatch.setenv("HOME_ENABLED_ORG_IDS", unset)
        assert settings.home_enabled_org_ids() is None
        assert settings.home_enabled_for_org(ORG_ID) and settings.home_enabled_for_org(None)

    monkeypatch.setenv("HOME_ENABLED_ORG_IDS", f" {OTHER_ORG} ,, {ORG_ID.upper()} ")
    assert settings.home_enabled_org_ids() == frozenset({OTHER_ORG, ORG_ID})
    assert settings.home_enabled_for_org(ORG_ID) and settings.home_enabled_for_org(f" {ORG_ID.upper()} ")
    assert not settings.home_enabled_for_org("5f2b9c1e")  # a prefix is not a listed id
    assert not settings.home_enabled_for_org(None) and not settings.home_enabled_for_org("")


def test_unset_changes_nothing(monkeypatch):
    monkeypatch.setenv("HOME_STATE_ENABLED", "true")
    monkeypatch.setenv("HOME_ACTIONS_ENABLED", "true")
    response, suite, _ = state_get(monkeypatch)
    assert response.status_code == 200, response.text
    assert suite.calls
    response, suite, db, _ = action_post(monkeypatch)
    assert response.status_code == 200 and response.json()["outcome"] == "done"
    # The answers for a person with no org, or a stale org cookie, are as before.
    assert state_get(monkeypatch, org_id=None)[0].status_code == 409
    assert state_get(monkeypatch, org_invalid=True)[0].status_code == 403


def test_a_listed_org_gets_both_routes(monkeypatch):
    monkeypatch.setenv("HOME_STATE_ENABLED", "true")
    monkeypatch.setenv("HOME_ACTIONS_ENABLED", "true")
    monkeypatch.setenv("HOME_ENABLED_ORG_IDS", f"{OTHER_ORG}, {ORG_ID.upper()}")
    response, suite, _ = state_get(monkeypatch)
    assert response.status_code == 200, response.text
    assert response.json()["organization"]["id"] == ORG_ID and suite.calls
    response, suite, db, _ = action_post(monkeypatch)
    assert response.status_code == 200, response.text
    assert response.json()["outcome"] == "done" and db.only_row()["org_id"] == ORG_ID


def test_an_unlisted_org_gets_the_flag_off_answer_on_both_routes(monkeypatch):
    monkeypatch.setenv("HOME_STATE_ENABLED", "false")
    monkeypatch.setenv("HOME_ACTIONS_ENABLED", "false")
    flag_off_state, _, _ = state_get(monkeypatch)
    flag_off_action, _, _, _ = action_post(monkeypatch)
    assert (flag_off_state.status_code, flag_off_state.json()) == (404, NOT_FOUND)
    assert (flag_off_action.status_code, flag_off_action.json()) == (404, NOT_FOUND)

    monkeypatch.setenv("HOME_STATE_ENABLED", "true")
    monkeypatch.setenv("HOME_ACTIONS_ENABLED", "true")
    monkeypatch.setenv("HOME_ENABLED_ORG_IDS", OTHER_ORG)
    response, suite, conn = state_get(monkeypatch)
    assert (response.status_code, response.json()) == (404, NOT_FOUND)
    assert response.headers["content-type"] == flag_off_state.headers["content-type"]
    assert "cache-control" not in response.headers
    assert suite.calls == [] and conn.queries == []  # no app, no role lookup

    response, suite, db, conn = action_post(monkeypatch)
    assert (response.status_code, response.json()) == (404, NOT_FOUND)
    assert response.headers["content-type"] == flag_off_action.headers["content-type"]
    assert suite.calls == [] and db.rows == {} and conn.queries == []  # no app, no receipt


def test_with_a_list_no_org_or_a_stale_org_cookie_is_404_and_no_session_is_still_401(monkeypatch):
    monkeypatch.setenv("HOME_STATE_ENABLED", "true")
    monkeypatch.setenv("HOME_ACTIONS_ENABLED", "true")
    monkeypatch.setenv("HOME_ENABLED_ORG_IDS", ORG_ID)
    for fake_kwargs in ({"org_id": None}, {"org_invalid": True}):
        response, suite, _ = state_get(monkeypatch, **fake_kwargs)
        assert (response.status_code, response.json()) == (404, NOT_FOUND), fake_kwargs
        response, suite, db, _ = action_post(monkeypatch, **fake_kwargs)
        assert (response.status_code, response.json()) == (404, NOT_FOUND), fake_kwargs
        assert suite.calls == [] and db.rows == {}

    suite = FakeSuite(suite_routes())
    client, _, _ = real_binding_client(monkeypatch, suite, session={})
    assert client.get("/api/v1/home/state").status_code == 401
