"""Unit coverage for the route-scoped onboarding service-key contract."""

import hashlib
import json
import os
import secrets
import sys

import pytest
from fastapi import HTTPException
from starlette.requests import Request

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import auth_dependencies


def _request(method, path, headers=None):
    raw_headers = [(key.lower().encode(), value.encode()) for key, value in (headers or {}).items()]
    return Request(
        {
            "type": "http",
            "method": method,
            "path": path,
            "root_path": "",
            "scheme": "http",
            "server": ("testserver", 80),
            "client": ("127.0.0.1", 1234),
            "headers": raw_headers,
            "query_string": b"",
            "path_params": {},
        }
    )


def _configure_key(monkeypatch, key, routes):
    monkeypatch.setenv(
        auth_dependencies.SERVICE_KEY_HASHES_ENV,
        json.dumps({"onboarding": hashlib.sha256(key.encode()).hexdigest()}),
    )
    monkeypatch.setenv(
        auth_dependencies.SERVICE_KEY_ROUTE_ALLOWLIST_ENV,
        json.dumps({"onboarding": routes}),
    )


@pytest.mark.asyncio
async def test_service_key_is_accepted_on_allowlisted_route_and_audited(monkeypatch):
    key = secrets.token_urlsafe(24)
    _configure_key(monkeypatch, key, ["org_member_add"])
    audit_rows = []

    async def fake_audit(request, **kwargs):
        audit_rows.append(kwargs)

    monkeypatch.setattr(auth_dependencies, "write_organization_audit_log", fake_audit)
    request = _request(
        "POST",
        "/api/v1/org/123e4567-e89b-12d3-a456-426614174000/members",
        {
            "X-Ops-Center-Service-Key": key,
            "X-Acting-User": "fictional-onboarding-user",
        },
    )

    user = await auth_dependencies.require_admin_user(request)
    cached_user = await auth_dependencies.require_authenticated_user(request)

    assert user["user_id"] == "service-key:onboarding"
    assert cached_user is user
    assert user["is_admin"] is True
    assert audit_rows == [
        {
            "org_id": "123e4567-e89b-12d3-a456-426614174000",
            "principal": "service-key:onboarding",
            "action": "service-key.org_member_add",
            "details": {"acting_user": "fictional-onboarding-user"},
        }
    ]


@pytest.mark.asyncio
async def test_service_key_authorization_header_is_accepted(monkeypatch):
    key = secrets.token_urlsafe(24)
    _configure_key(monkeypatch, key, ["POST /api/v1/org"])
    monkeypatch.setattr(auth_dependencies, "write_organization_audit_log", _noop_audit)

    user = await auth_dependencies.require_authenticated_user(
        _request("POST", "/api/v1/org", {"Authorization": f"Bearer {key}"})
    )

    assert user["user_id"] == "service-key:onboarding"


@pytest.mark.asyncio
async def test_valid_service_key_is_refused_on_nonlisted_route(monkeypatch):
    key = secrets.token_urlsafe(24)
    _configure_key(monkeypatch, key, ["org_create"])
    monkeypatch.setattr(auth_dependencies, "write_organization_audit_log", _noop_audit)

    with pytest.raises(HTTPException) as exc_info:
        await auth_dependencies.require_admin_user(
            _request("POST", "/api/v1/admin/billing/provision-paid-org", {"Authorization": f"Bearer {key}"})
        )

    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_wrong_service_key_is_401_and_does_not_audit(monkeypatch):
    configured_key = secrets.token_urlsafe(24)
    wrong_key = secrets.token_urlsafe(24)
    _configure_key(monkeypatch, configured_key, ["org_create"])
    audit_rows = []

    async def fake_audit(request, **kwargs):
        audit_rows.append(kwargs)

    monkeypatch.setattr(auth_dependencies, "write_organization_audit_log", fake_audit)

    with pytest.raises(HTTPException) as exc_info:
        await auth_dependencies.require_authenticated_user(
            _request("POST", "/api/v1/org", {"X-Ops-Center-Service-Key": wrong_key})
        )

    assert exc_info.value.status_code == 401
    assert audit_rows == []


@pytest.mark.asyncio
async def test_organization_audit_writer_inserts_principal_and_acting_note(monkeypatch):
    executed = []

    class FakeConnection:
        async def execute(self, *args):
            executed.append(args)

    class Acquire:
        async def __aenter__(self):
            return FakeConnection()

        async def __aexit__(self, exc_type, exc_value, traceback):
            return False

    class FakePool:
        def acquire(self):
            return Acquire()

    async def fake_pool():
        return FakePool()

    monkeypatch.setattr(auth_dependencies, "_get_audit_pool", fake_pool)
    request = _request("POST", "/api/v1/org/123e4567-e89b-12d3-a456-426614174000/members")

    await auth_dependencies.write_organization_audit_log(
        request,
        org_id="123e4567-e89b-12d3-a456-426614174000",
        principal="service-key:onboarding",
        action="service-key.org_member_add",
        details={"acting_user": "fictional-onboarding-user"},
    )

    assert len(executed) == 1
    query, org_id, principal, action, resource_type, resource_id, details, ip, user_agent = executed[0]
    assert "organization_audit_log" in query
    assert org_id == "123e4567-e89b-12d3-a456-426614174000"
    assert principal == "service-key:onboarding"
    assert action == "service-key.org_member_add"
    assert resource_type == "onboarding_route"
    assert resource_id == "123e4567-e89b-12d3-a456-426614174000"
    assert json.loads(details)["acting_user"] == "fictional-onboarding-user"
    assert ip == "127.0.0.1"
    assert user_agent is None


@pytest.mark.asyncio
async def test_entitlements_shape_adds_nullable_organization_metadata(monkeypatch):
    entitlements_api = pytest.importorskip("entitlements_api")

    class FakeConnection:
        async def fetchrow(self, query, *params):
            if "organization_members" in query:
                return {"org_id": "123e4567-e89b-12d3-a456-426614174000", "role": "owner"}
            return {
                "plan_tier": "professional",
                "org_name": "Fictional Cloud",
                "display_name": None,
                "slug": "fictional-cloud",
            }

        async def close(self):
            pass

    token = secrets.token_urlsafe(18)

    async def fake_db_connection():
        return FakeConnection()

    monkeypatch.setattr(entitlements_api, "_verify_bearer", lambda value: {"sub": "fictional-user"})
    monkeypatch.setattr(entitlements_api, "get_combined_features", _features)
    monkeypatch.setattr(entitlements_api, "get_db_connection", fake_db_connection)

    result = await entitlements_api.get_entitlements(
        _request("GET", "/api/v1/entitlements", {"Authorization": f"Bearer {token}"})
    )

    assert result == {
        "org_id": "123e4567-e89b-12d3-a456-426614174000",
        "org_name": "Fictional Cloud",
        "display_name": None,
        "slug": "fictional-cloud",
        "tier": "professional",
        "role": "owner",
        "entitlements": ["fictional_feature"],
    }


async def _noop_audit(request, **kwargs):
    return None


async def _features(tier, org_id, conn):
    return {"fictional_feature"}
