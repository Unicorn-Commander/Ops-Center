"""Org selection fallbacks for billing: switcher cookie hint and the default membership.

2026-11-07: on prod a user in three organizations got 409 "Select an organization before
billing" on every billing read, because the console's org switcher stores its choice in the
``current_org_id`` cookie and billing only read the session. No credentials or services needed.
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
import billing_org_identity as identity

ORG_A = "11111111-1111-4111-8111-111111111111"
ORG_B = "22222222-2222-4222-8222-222222222222"
ORG_C = "33333333-3333-4333-8333-333333333333"
USER = {"sub": "subject-a"}


def request_with_cookie(value):
    return SimpleNamespace(cookies={"current_org_id": value} if value is not None else {})


def rows(*specs):
    return [{"org_id": org, "role": role, "is_default": default} for org, role, default in specs]


@pytest.mark.asyncio
async def test_cookie_hint_selects_among_several_memberships(monkeypatch):
    monkeypatch.setattr(identity, "_membership_orgs", AsyncMock(return_value=rows(
        (ORG_A, "owner", True), (ORG_B, "admin", False))))
    assert await identity.resolve_billing_org(USER, request=request_with_cookie(ORG_B)) == f"org_{ORG_B}"
    assert await identity.resolve_billing_org(USER, request=request_with_cookie(f"org_{ORG_B}")) == f"org_{ORG_B}"


@pytest.mark.asyncio
async def test_cookie_never_grants_membership(monkeypatch):
    """A stale or forged cookie is ignored; the default membership decides instead."""
    monkeypatch.setattr(identity, "_membership_orgs", AsyncMock(return_value=rows(
        (ORG_A, "owner", True), (ORG_B, "admin", False))))
    assert await identity.resolve_billing_org(USER, request=request_with_cookie(ORG_C)) == f"org_{ORG_A}"
    assert await identity.resolve_billing_org(USER, request=request_with_cookie("not-a-uuid")) == f"org_{ORG_A}"


@pytest.mark.asyncio
async def test_single_default_breaks_the_tie_without_a_cookie(monkeypatch):
    monkeypatch.setattr(identity, "_membership_orgs", AsyncMock(return_value=rows(
        (ORG_A, "admin", False), (ORG_B, "admin", False), (ORG_C, "owner", True))))
    assert await identity.resolve_billing_org(USER) == f"org_{ORG_C}"
    assert await identity.resolve_billing_org(USER, request=request_with_cookie(None)) == f"org_{ORG_C}"


@pytest.mark.asyncio
async def test_several_memberships_without_default_or_cookie_still_409(monkeypatch):
    monkeypatch.setattr(identity, "_membership_orgs", AsyncMock(return_value=rows(
        (ORG_A, "admin", False), (ORG_B, "admin", False))))
    with pytest.raises(HTTPException) as error:
        await identity.resolve_billing_org(USER)
    assert error.value.status_code == 409


@pytest.mark.asyncio
async def test_two_defaults_are_no_selection(monkeypatch):
    monkeypatch.setattr(identity, "_membership_orgs", AsyncMock(return_value=rows(
        (ORG_A, "owner", True), (ORG_B, "owner", True))))
    with pytest.raises(HTTPException) as error:
        await identity.resolve_billing_org(USER, request=request_with_cookie(None))
    assert error.value.status_code == 409


@pytest.mark.asyncio
async def test_explicit_session_selection_wins_over_the_cookie(monkeypatch):
    monkeypatch.setattr(identity, "_membership_orgs", AsyncMock(return_value=rows(
        (ORG_A, "owner", True), (ORG_B, "admin", False))))
    assert await identity.resolve_billing_org(USER, {"org_id": ORG_A}, request=request_with_cookie(ORG_B)) == f"org_{ORG_A}"


@pytest.mark.asyncio
async def test_explicit_selection_outside_membership_is_still_refused(monkeypatch):
    monkeypatch.setattr(identity, "_membership_orgs", AsyncMock(return_value=rows((ORG_A, "owner", True))))
    with pytest.raises(HTTPException) as error:
        await identity.resolve_billing_org(USER, {"org_id": ORG_B}, request=request_with_cookie(ORG_B))
    assert error.value.status_code == 403


@pytest.mark.asyncio
async def test_rows_without_is_default_column_keep_working(monkeypatch):
    monkeypatch.setattr(identity, "_membership_orgs", AsyncMock(return_value=[{"org_id": ORG_A, "role": "owner"}]))
    assert await identity.resolve_billing_org(USER, request=request_with_cookie(ORG_B)) == f"org_{ORG_A}"


@pytest.mark.asyncio
async def test_write_role_comes_from_the_selected_membership(monkeypatch):
    monkeypatch.setattr(identity, "_membership_orgs", AsyncMock(return_value=rows(
        (ORG_A, "owner", True), (ORG_B, "member", False))))
    with pytest.raises(HTTPException) as error:
        await identity.resolve_billing_org(USER, request=request_with_cookie(ORG_B), require_write=True)
    assert error.value.status_code == 403
    assert await identity.resolve_billing_org(USER, request=request_with_cookie(ORG_A), require_write=True) == f"org_{ORG_A}"
