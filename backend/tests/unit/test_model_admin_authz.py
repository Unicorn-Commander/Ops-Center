"""Admin authorization on the model-catalog admin routes (model_access_api + model_admin_api).

2026-09-28: every /admin route in model_access_api depended only on litellm_api.get_user_id, which
accepts ANY authenticated caller (GET /admin/models had no auth dependency at all). A logged-in customer
could create, update and delete model_access_control rows, change tier access and tier markups, and read
30 days of platform-wide usage and cost. The routes now take auth_dependencies.require_admin_user, the
console's standard admin gate, as their first dependency; model_admin_api (not mounted today) uses the
same gate instead of its own admin/moderator session check.

These tests pin that:
  * anonymous -> 401 and every non-admin role -> 403 on every /admin route, before any database work
    and before body validation (the requests carry a schema-invalid body);
  * an admin session reaches the handler (the recording fake pool sees the SQL);
  * guard: every route in either module whose path contains /admin has require_admin_user as its FIRST
    dependency, so a new admin route without the gate fails here.

The real require_admin_user runs against an in-memory session store (redis_session is replaced); the DB
pool, Redis cache and audit logger are fakes. No network, database or Redis is needed.
"""
import copy
import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.routing import APIRoute

BACKEND = Path(__file__).resolve().parents[2]

SESSION_USERS = {
    "tok-admin": {"sub": "admin-1", "email": "admin@example.test", "role": "admin"},
    "tok-system-admin": {"sub": "sysadmin-1", "email": "sysadmin@example.test", "role": "system_admin"},
    "tok-legacy-roles-admin": {"sub": "legacy-1", "email": "legacy@example.test", "roles": ["admin"]},
    "tok-viewer": {"sub": "cust-1", "email": "customer@example.test", "role": "viewer"},
    "tok-user": {"sub": "cust-2", "email": "user@example.test", "role": "user"},
    "tok-power-user": {"sub": "power-1", "email": "power@example.test", "role": "power_user"},
    "tok-moderator": {"sub": "mod-1", "email": "mod@example.test", "role": "moderator"},
    "tok-is-admin-flag-only": {"sub": "flag-1", "email": "flag@example.test", "role": "viewer", "is_admin": True},
}
ADMIN_TOKENS = ["tok-admin", "tok-system-admin", "tok-legacy-roles-admin"]
NON_ADMIN_TOKENS = ["tok-viewer", "tok-user", "tok-power-user", "tok-moderator", "tok-is-admin-flag-only"]

SAMPLE_PATH_PARAMS = {"model_id": "probe-model", "tier_code": "trial"}


# ------------------------------------------------------------------------------------------ fakes
class FakeRedisSessionManager:
    """Stands in for redis_session.RedisSessionManager: same dict-like surface, in memory."""

    store = {}

    def __init__(self, *args, **kwargs):
        pass

    def get(self, session_id):
        value = self.store.get(session_id)
        return copy.deepcopy(value) if value is not None else None

    def get_for_request(self, session_id):
        return self.get(session_id)

    def __contains__(self, session_id):
        return session_id in self.store

    def __getitem__(self, session_id):
        return self.get(session_id)


class RecordingConnection:
    def __init__(self, log):
        self.log = log

    async def fetch(self, query, *args):
        self.log.append(query)
        if "SELECT id FROM model_access_control" in " ".join(query.split()):
            return [{"id": "00000000-0000-4000-8000-000000000001"}]
        return []

    async def fetchval(self, query, *args):
        self.log.append(query)
        return 0 if "COUNT(" in query.upper() else "00000000-0000-4000-8000-000000000001"

    async def fetchrow(self, query, *args):
        self.log.append(query)
        return {"id": 1}

    async def execute(self, query, *args):
        self.log.append(query)
        return {"DELETE": "DELETE 1", "INSERT": "INSERT 0 1"}.get(query.split()[0].upper(), "UPDATE 1")


class RecordingPool(RecordingConnection):
    """asyncpg.Pool stand-in: records every statement; acquire() yields a recording connection."""

    def __init__(self):
        super().__init__([])

    def acquire(self):
        pool = self

        class _Acquire:
            async def __aenter__(self):
                return RecordingConnection(pool.log)

            async def __aexit__(self, *exc):
                return False

        return _Acquire()


def fake_module(monkeypatch, name, **attrs):
    module = ModuleType(name)
    module.__dict__.update(attrs)
    monkeypatch.setitem(sys.modules, name, module)
    return module


def import_route(monkeypatch, name):
    spec = importlib.util.spec_from_file_location(name, BACKEND / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)
    return module


async def fake_get_user_id(request: Request) -> str:
    """Mirrors litellm_api.get_user_id's session branch: ANY valid session is accepted, no role check.
    If an /admin route ever goes back to this dependency, the non-admin tests below fail."""
    user = (FakeRedisSessionManager.store.get(request.cookies.get("session_token") or "") or {}).get("user")
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user["sub"]


@pytest.fixture
def modules(monkeypatch):
    monkeypatch.setattr(FakeRedisSessionManager, "store", {
        token: {"user": dict(user), "org_id": "org-" + token} for token, user in SESSION_USERS.items()})
    fake_module(monkeypatch, "redis_session", RedisSessionManager=FakeRedisSessionManager,
                RedisSessionUnavailable=RuntimeError,
                redis_session_manager=FakeRedisSessionManager())
    # model_access_api's heavy siblings: only their names are needed by the admin routes.
    fake_module(monkeypatch, "litellm_credit_system", CreditSystem=type("CreditSystem", (), {}))
    fake_module(monkeypatch, "byok_manager", BYOKManager=type("BYOKManager", (), {}))
    fake_module(monkeypatch, "litellm_api", get_user_id=fake_get_user_id)
    audit = SimpleNamespace(log=AsyncMock())
    fake_module(monkeypatch, "audit_logger", audit_logger=audit)
    fake_module(monkeypatch, "audit_helpers", get_client_ip=lambda request: "203.0.113.9",
                get_user_agent=lambda request: "pytest")
    auth_dependencies = import_route(monkeypatch, "auth_dependencies")
    access = import_route(monkeypatch, "model_access_api")
    admin = import_route(monkeypatch, "model_admin_api")

    pool = RecordingPool()
    redis = SimpleNamespace(get=AsyncMock(return_value=None), setex=AsyncMock(), delete=AsyncMock())

    async def get_pool():
        return pool

    async def get_redis():
        return redis

    access_app = FastAPI()
    access_app.include_router(access.router)
    access_app.dependency_overrides[access.get_db_pool] = get_pool
    admin_app = FastAPI()
    admin_app.include_router(admin.router)
    admin_app.dependency_overrides[admin.get_db_pool] = get_pool
    admin_app.dependency_overrides[admin.get_redis_client] = get_redis
    return SimpleNamespace(access=access, admin=admin, access_app=access_app, admin_app=admin_app,
                           pool=pool, audit=audit, require_admin_user=auth_dependencies.require_admin_user)


def admin_routes(router):
    """Every (method, path, route) in a router whose path contains /admin."""
    out = []
    for route in router.routes:
        if isinstance(route, APIRoute) and "/admin" in route.path:
            for method in sorted(route.methods - {"HEAD"}):
                out.append((method, route.path, route))
    return out


def concrete(path):
    for name, value in SAMPLE_PATH_PARAMS.items():
        path = path.replace("{" + name + "}", value)
    return path


async def send(app, method, path, token=None, json=None, params=None):
    cookies = {"session_token": token} if token else {}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
                                 base_url="http://test",
                                 cookies=cookies) as client:
        kwargs = {"params": params}
        if json is not None:
            kwargs["json"] = json
        return await client.request(method, path, **kwargs)


# A body that fails every admin route's schema: auth must answer before validation does.
INVALID_BODY = {"unexpected": "field"}

# Minimal valid requests, so an admin gets all the way into the handler.
ACCESS_ADMIN_REQUESTS = {
    ("GET", "/api/v1/models/admin/models"): {},
    ("POST", "/api/v1/models/admin/models"): {"json": {
        "model_id": "probe-model", "provider": "openai", "display_name": "Probe",
        "pricing": {"input_per_1k": 0.001, "output_per_1k": 0.002}}},
    ("PUT", "/api/v1/models/admin/models/{model_id}"): {"json": {"display_name": "Probe renamed"}},
    ("DELETE", "/api/v1/models/admin/models/{model_id}"): {},
    ("GET", "/api/v1/models/admin/models/analytics"): {},
    ("POST", "/api/v1/models/admin/tiers/{tier_code}/models"): {"json": ["probe-model"]},
    ("DELETE", "/api/v1/models/admin/tiers/{tier_code}/models/{model_id}"): {},
    ("PUT", "/api/v1/models/admin/models/{model_id}/tiers"): {"json": {"trial": True}},
    ("GET", "/api/v1/models/admin/tiers/{tier_code}/models"): {},
    ("PUT", "/api/v1/models/admin/tiers/{tier_code}/models/{model_id}/markup"): {"params": {"markup_multiplier": 1.5}},
}
ADMIN_API_ADMIN_REQUESTS = {
    ("GET", "/api/v1/models/admin/models"): {},
    ("POST", "/api/v1/models/admin/models"): {"json": {
        "model_id": "probe-model", "provider": "openai", "display_name": "Probe",
        "pricing": {"input_per_1k": 0.001, "output_per_1k": 0.002}}},
    ("GET", "/api/v1/models/admin/models/{model_id}"): {},
    ("PUT", "/api/v1/models/admin/models/{model_id}"): {"json": {"display_name": "Probe renamed"}},
    ("DELETE", "/api/v1/models/admin/models/{model_id}"): {},
    ("PATCH", "/api/v1/models/admin/models/{model_id}/toggle"): {},
    ("GET", "/api/v1/models/admin/models/stats/summary"): {},
}


def pick(mods, which):
    return (mods.access, mods.access_app) if which == "access" else (mods.admin, mods.admin_app)


# ------------------------------------------------------------------------------------------ guard
@pytest.mark.parametrize("which,minimum", [("access", 10), ("admin", 7)])
def test_every_admin_route_has_require_admin_user_as_first_dependency(modules, which, minimum):
    module, _ = pick(modules, which)
    routes = admin_routes(module.router)
    assert len(routes) >= minimum, f"{module.__name__}: expected at least {minimum} /admin routes, found {len(routes)}"
    missing = []
    for method, path, route in routes:
        first = route.dependant.dependencies[0].call if route.dependant.dependencies else None
        if first is not modules.require_admin_user:
            missing.append(f"{method} {path} (first dependency: {getattr(first, '__name__', first)})")
    assert not missing, "admin routes without require_admin_user as their FIRST dependency:\n" + "\n".join(missing)


def test_admin_request_tables_cover_every_admin_route(modules):
    """Keep the valid-request tables in step with the routers, so no admin route escapes the admin test."""
    for which, table in (("access", ACCESS_ADMIN_REQUESTS), ("admin", ADMIN_API_ADMIN_REQUESTS)):
        module, _ = pick(modules, which)
        assert {(m, p) for m, p, _ in admin_routes(module.router)} == set(table), module.__name__


def test_user_facing_routes_do_not_need_admin(modules):
    """/available and /categorized stay open to any authenticated user (they are not admin surfaces)."""
    for route in modules.access.router.routes:
        if route.path in ("/api/v1/models/available", "/api/v1/models/categorized"):
            calls = [d.call for d in route.dependant.dependencies]
            assert modules.require_admin_user not in calls
            assert modules.access.get_user_id in calls


# ------------------------------------------------------------------------------------------ HTTP
def _cases(which, table):
    return [pytest.param(which, method, path, id=f"{which}:{method}:{path}") for method, path in table]


ALL_CASES = _cases("access", ACCESS_ADMIN_REQUESTS) + _cases("admin", ADMIN_API_ADMIN_REQUESTS)


@pytest.mark.asyncio
@pytest.mark.parametrize("which,method,path", ALL_CASES)
async def test_anonymous_gets_401_and_no_database_work(modules, which, method, path):
    _, app = pick(modules, which)
    body = INVALID_BODY if method in ("POST", "PUT", "PATCH") else None
    response = await send(app, method, concrete(path), json=body)
    assert response.status_code == 401, response.text
    assert modules.pool.log == []


@pytest.mark.asyncio
@pytest.mark.parametrize("token", NON_ADMIN_TOKENS)
@pytest.mark.parametrize("which,method,path", ALL_CASES)
async def test_non_admin_session_gets_403_before_validation_and_database(modules, which, method, path, token):
    _, app = pick(modules, which)
    body = INVALID_BODY if method in ("POST", "PUT", "PATCH") else None
    response = await send(app, method, concrete(path), token=token, json=body)
    assert response.status_code == 403, response.text
    assert modules.pool.log == []
    modules.audit.log.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("which,method,path", ALL_CASES)
async def test_unknown_session_gets_401(modules, which, method, path):
    _, app = pick(modules, which)
    response = await send(app, method, concrete(path), token="tok-expired-or-forged")
    assert response.status_code == 401, response.text
    assert modules.pool.log == []


@pytest.mark.asyncio
@pytest.mark.parametrize("token", ADMIN_TOKENS)
@pytest.mark.parametrize("method,path", list(ACCESS_ADMIN_REQUESTS))
async def test_admin_reaches_model_access_handler(modules, method, path, token):
    request = ACCESS_ADMIN_REQUESTS[(method, path)]
    response = await send(modules.access_app, method, concrete(path), token=token,
                          json=request.get("json"), params=request.get("params"))
    assert response.status_code == 200, response.text
    assert modules.pool.log, "handler did not run: no SQL reached the pool"


@pytest.mark.asyncio
@pytest.mark.parametrize("method,path", list(ADMIN_API_ADMIN_REQUESTS))
async def test_admin_reaches_model_admin_api_handler(modules, method, path):
    request = ADMIN_API_ADMIN_REQUESTS[(method, path)]
    response = await send(modules.admin_app, method, concrete(path), token="tok-admin",
                          json=request.get("json"), params=request.get("params"))
    # The fake rows are not full catalog rows, so some handlers answer 404/500 after querying;
    # what matters here is that the admin passed the gate and the handler body ran.
    assert response.status_code not in (401, 403), response.text
    assert modules.pool.log, "handler did not run: no SQL reached the pool"


@pytest.mark.asyncio
async def test_customer_cannot_change_a_tier_markup(modules):
    """The concrete abuse case: a customer session setting a tier markup to zero."""
    path = concrete("/api/v1/models/admin/tiers/{tier_code}/models/{model_id}/markup")
    response = await send(modules.access_app, "PUT", path, token="tok-viewer", params={"markup_multiplier": 0.0})
    assert response.status_code == 403
    assert not any("tier_model_access" in q for q in modules.pool.log)
    response = await send(modules.access_app, "PUT", path, token="tok-admin", params={"markup_multiplier": 0.0})
    assert response.status_code == 200
    assert any("UPDATE tier_model_access" in " ".join(q.split()) for q in modules.pool.log)
