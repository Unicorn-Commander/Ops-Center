"""Membership authorization against the deployed direct-sub schema contract."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
import billing_org_identity as identity

ORG_A = "11111111-1111-4111-8111-111111111111"
ORG_B = "22222222-2222-4222-8222-222222222222"


@pytest.mark.asyncio
async def test_direct_subject_works_without_user_table(monkeypatch):
    async def fetch(query, subject):
        if 'FROM "user"' in query or 'public."user"' in query:
            raise identity.asyncpg.UndefinedTableError('relation does not exist')
        assert subject == "uchub-subject"
        return [{"org_id": ORG_A, "role": "owner"}]
    conn = SimpleNamespace(fetch=AsyncMock(side_effect=fetch), fetchval=AsyncMock(return_value=False), close=AsyncMock())
    monkeypatch.setattr(identity.asyncpg, "connect", AsyncMock(return_value=conn))
    assert await identity.resolve_billing_org({"sub": "uchub-subject"}) == f"org_{ORG_A}"
    conn.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_selected_org_requires_current_active_membership(monkeypatch):
    lookup = AsyncMock(return_value=[{"org_id": ORG_A, "role": "owner"}])
    monkeypatch.setattr(identity, "_membership_orgs", lookup)
    with pytest.raises(HTTPException) as error:
        await identity.resolve_billing_org({"sub": "uchub-subject", "org_id": ORG_B,
                                           "is_admin": True, "role": "admin"})
    assert error.value.status_code == 403
    lookup.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("has_mapping", [False, True])
async def test_optional_legacy_mapping_is_capability_gated(monkeypatch, has_mapping):
    events = []
    async def fetch(query, subject):
        events.append("legacy" if 'public."user"' in query else "direct")
        assert subject == "uchub-subject"
        if events[-1] == "legacy":
            assert has_mapping
            assert events == ["direct", "capability", "legacy"]
            return [{"org_id": ORG_A, "role": "member"}]
        return []
    async def capability(query):
        events.append("capability")
        assert "information_schema.columns" in query
        assert "oauth_sub" in query
        return has_mapping
    conn = SimpleNamespace(fetch=AsyncMock(side_effect=fetch), fetchval=AsyncMock(side_effect=capability), close=AsyncMock())
    monkeypatch.setattr(identity.asyncpg, "connect", AsyncMock(return_value=conn))
    rows = await identity._membership_orgs("uchub-subject")
    assert bool(rows) == has_mapping
    assert events == (["direct", "capability", "legacy"] if has_mapping else ["direct", "capability"])
    conn.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_active_membership_query_and_pool(monkeypatch):
    from unittest.mock import MagicMock
    conn = SimpleNamespace(fetch=AsyncMock(return_value=[{"org_id": ORG_A, "role": "member"}]), fetchval=AsyncMock())
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=conn)
    context.__aexit__ = AsyncMock(return_value=False)
    pool = SimpleNamespace(acquire=lambda: context)
    connect = AsyncMock(side_effect=AssertionError("Must use supplied pool"))
    monkeypatch.setattr(identity.asyncpg, "connect", connect)
    assert await identity.resolve_billing_org({"sub": "subject", "org_id": ORG_A}, pool=pool) == f"org_{ORG_A}"
    query = conn.fetch.await_args.args[0]
    assert "o.status = 'active'" in query
    assert "COALESCE" not in query
    assert 'public."user"' not in query
    assert "om.role" in query
    conn.fetchval.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["owner", "admin", "billing_admin", "member", "viewer", "", None])
async def test_persisted_role_controls_mutation_not_session_claim(monkeypatch, role):
    monkeypatch.setattr(identity, "_membership_orgs", AsyncMock(return_value=[{"org_id": ORG_A, "role": role}]))
    user = {"sub": "subject", "org_id": ORG_A, "role": "admin", "is_admin": True,
            "attributes": {"org_role": ["owner"]}}
    assert await identity.resolve_billing_org(user) == f"org_{ORG_A}"
    if role in {"owner", "admin", "billing_admin"}:
        assert await identity.resolve_billing_org(user, require_write=True) == f"org_{ORG_A}"
    else:
        with pytest.raises(HTTPException) as error:
            await identity.resolve_billing_org(user, require_write=True)
        assert error.value.status_code == 403


@pytest.mark.asyncio
async def test_revocation_and_role_changes_rechecked_each_call(monkeypatch):
    lookup = AsyncMock(side_effect=[
        [{"org_id": ORG_A, "role": "owner"}],
        [{"org_id": ORG_A, "role": "member"}],
        [],
    ])
    monkeypatch.setattr(identity, "_membership_orgs", lookup)
    user = {"sub": "subject", "org_id": ORG_A}
    assert await identity.resolve_billing_org(user, require_write=True) == f"org_{ORG_A}"
    for _ in range(2):
        with pytest.raises(HTTPException) as error:
            await identity.resolve_billing_org(user, require_write=True)
        assert error.value.status_code == 403
    assert lookup.await_count == 3


@pytest.mark.asyncio
async def test_owner_in_other_tenant_cannot_promote_member_here(monkeypatch):
    monkeypatch.setattr(identity, "_membership_orgs", AsyncMock(return_value=[
        {"org_id": ORG_A, "role": "owner"}, {"org_id": ORG_B, "role": "member"}]))
    with pytest.raises(HTTPException) as error:
        await identity.resolve_billing_org({"sub": "subject", "org_id": ORG_B}, require_write=True)
    assert error.value.status_code == 403


@pytest.mark.asyncio
async def test_conflicting_legacy_roles_do_not_escalate(monkeypatch):
    monkeypatch.setattr(identity, "_membership_orgs", AsyncMock(return_value=[
        {"org_id": ORG_A, "role": "owner"}, {"org_id": ORG_A, "role": "member"}]))
    with pytest.raises(HTTPException) as error:
        await identity.resolve_billing_org({"sub": "subject", "org_id": ORG_A}, require_write=True)
    assert error.value.status_code == 403
