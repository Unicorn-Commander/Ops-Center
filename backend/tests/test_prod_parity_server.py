"""Focused tests for the server-side prod-parity restores."""

import ast
import asyncio
import hashlib
import json
import logging
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.responses import JSONResponse
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.routing import Route
from starlette.testclient import TestClient

from csrf_protection import CSRFMiddleware, CSRFProtection
from openai_v1_alias import OpenAIV1AliasMiddleware
from rate_limit_keys import uuda_aware_rate_limit_key
from uc_key_validation import check_required_permission


SERVER_PATH = Path(__file__).resolve().parents[1] / "server.py"
SERVER_SOURCE = SERVER_PATH.read_text()

PROD_ONLY_OPERATIONS = (
    "GET /api/v1/admin/trial-codes",
    "POST /api/v1/admin/trial-codes",
    "GET /api/v1/admin/trial-codes/",
    "POST /api/v1/admin/trial-codes/",
    "POST /api/v1/admin/trial-codes/{code_id}/deactivate",
    "GET /api/v1/admin/trial-codes/{code_id}/redemptions",
    "POST /api/v1/mcp/meter",
    "GET /api/v1/public/beta/health",
    "GET /api/v1/public/beta/programs",
    "POST /api/v1/public/beta/signup",
    "POST /api/v1/trial-codes/redeem",
    "GET /api/v1/trial-codes/validate/{code}",
    "GET /api/v1/uuda/drift/checks",
    "POST /api/v1/uuda/drift/checks",
    "DELETE /api/v1/uuda/drift/checks/{key}",
    "GET /api/v1/uuda/drift/history",
    "POST /api/v1/uuda/drift/scan",
    "GET /api/v1/uuda/drift/scheduler",
    "GET /api/v1/uuda/drift/summary",
    "POST /api/v1/uuda/drift/{device_id}/remediate",
    "POST /api/v1/uuda/drift/{device_id}/scan",
    "GET /api/v1/uuda/mcp/approvals",
    "POST /api/v1/uuda/mcp/approvals/{pending_id}/approve",
    "POST /api/v1/uuda/mcp/approvals/{pending_id}/reject",
    "POST /api/v1/uuda/mcp/fanout",
    "POST /api/v1/uuda/mcp/{device_id}/call",
    "GET /api/v1/uuda/mcp/{device_id}/tools",
    "GET /mail/{path}",
    "POST /mail/{path}",
)


def _http_scope(path: str, headers=()):
    return {
        "type": "http",
        "path": path,
        "raw_path": path.encode("utf-8"),
        "query_string": b"",
        "headers": [(name.lower().encode(), value.encode()) for name, value in headers],
        "method": "GET",
        "scheme": "http",
        "server": ("example.test", 80),
        "client": ("198.51.100.10", 1234),
        "root_path": "",
    }


def _run_alias(scope):
    observed = {}

    async def downstream(new_scope, receive, send):
        observed.update(new_scope)

    asyncio.run(OpenAIV1AliasMiddleware(downstream)(scope, None, None))
    return observed


@pytest.mark.parametrize(
    ("path", "expected"),
    (
        ("/v1", "/api/v1/llm/models"),
        ("/v1/", "/api/v1/llm/models"),
        ("/v1/chat/completions", "/api/v1/llm/chat/completions"),
        ("/v1/audio/speech", "/api/v1/audio/speech"),
    ),
)
def test_openai_v1_alias_maps_openai_paths(path, expected):
    observed = _run_alias(_http_scope(path))
    assert observed["path"] == expected
    assert observed["raw_path"] == expected.encode("utf-8")


def test_openai_v1_alias_passes_other_paths_and_non_http_scopes_unchanged():
    other = _http_scope("/api/v1/llm/chat/completions")
    assert _run_alias(other) == other

    websocket = {"type": "websocket", "path": "/v1/chat/completions", "raw_path": b"/v1/chat/completions"}
    assert _run_alias(websocket) == websocket


def _request(path: str, headers=()):
    return Request(_http_scope(path, headers))


def test_uuda_rate_limit_key_uses_agent_bucket_only_for_uuda_paths():
    agent_key = "agent-test-fake"
    expected = "uuda-agent:" + hashlib.sha256(agent_key.encode()).hexdigest()[:32]
    assert uuda_aware_rate_limit_key(_request("/api/v1/uuda/heartbeat", (("X-Agent-Key", agent_key),))) == expected
    assert uuda_aware_rate_limit_key(_request("/api/v1/uuda/heartbeat")) == "198.51.100.10"
    assert uuda_aware_rate_limit_key(_request("/api/v1/compute/heartbeat", (("X-Agent-Key", agent_key),))) == "198.51.100.10"


def _fake_mcp_permission_checker(permissions, app=None):
    return "mcp:*" in permissions or (app is not None and f"mcp:{app}" in permissions)


def test_required_permission_handles_present_absent_mcp_scopes_and_json_columns():
    checker = _fake_mcp_permission_checker
    permissions, allowed = check_required_permission(["llm:models"], None, checker)
    assert permissions == ["llm:models"] and allowed

    permissions, allowed = check_required_permission(["llm:models"], "mcp:accounting-ops", checker)
    assert permissions == ["llm:models"] and not allowed

    _, allowed = check_required_permission(["mcp:*"] , "mcp:accounting-ops", checker)
    assert allowed
    _, allowed = check_required_permission(["mcp:accounting-ops"], "mcp:accounting-ops", checker)
    assert allowed
    _, allowed = check_required_permission(["mcp:other-app"], "mcp:accounting-ops", checker)
    assert not allowed

    permissions, allowed = check_required_permission(
        '["llm:models", "mcp:accounting-ops"]', "mcp:accounting-ops", checker
    )
    assert permissions == ["llm:models", "mcp:accounting-ops"] and allowed
    permissions, allowed = check_required_permission(("mcp:*",), "mcp:accounting-ops", checker)
    assert permissions == ["mcp:*"] and allowed


def test_validate_key_handler_contains_prod_permission_and_key_context_fields():
    assert "check_required_permission(" in SERVER_SOURCE
    assert '"reason": "missing_permission"' in SERVER_SOURCE
    assert '"required_permission": required_permission' in SERVER_SOURCE
    assert '"permissions": permissions' in SERVER_SOURCE
    assert '"key_id": key_info.get("key_id")' in SERVER_SOURCE
    assert 'logger.info(f"validate-key' not in SERVER_SOURCE


def _load_validate_key_handler(monkeypatch, manager, db_pool):
    tree = ast.parse(SERVER_SOURCE)
    function = next(node for node in tree.body if isinstance(node, ast.AsyncFunctionDef) and node.name == "validate_key_endpoint")
    function.decorator_list = []
    fake_api_key_manager = ModuleType("api_key_manager")
    fake_api_key_manager.get_api_key_manager = lambda: manager
    monkeypatch.setitem(sys.modules, "api_key_manager", fake_api_key_manager)
    fake_uc_api_keys = ModuleType("uc_api_keys")
    fake_uc_api_keys.key_has_mcp_permission = _fake_mcp_permission_checker
    monkeypatch.setitem(sys.modules, "uc_api_keys", fake_uc_api_keys)
    namespace = {
        "Request": Request,
        "HTTPException": HTTPException,
        "JSONResponse": JSONResponse,
        "check_required_permission": check_required_permission,
        "db_pool": db_pool,
        "logger": logging.getLogger("test.validate-key"),
    }
    module = ast.Module(body=[function], type_ignores=[])
    ast.fix_missing_locations(module)
    exec(compile(module, str(SERVER_PATH), "exec"), namespace)
    return namespace["validate_key_endpoint"]


class _FakePoolAcquire:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    async def fetchrow(self, query, user_id):
        return None


class _FakePool:
    def acquire(self):
        return _FakePoolAcquire()


class _FakeKeyManager:
    def __init__(self, info):
        self.info = info
        self.presented_key = None

    async def validate_api_key(self, presented_key):
        self.presented_key = presented_key
        return self.info


class _FakeRequest:
    def __init__(self, body):
        self.body = body

    async def json(self):
        return self.body


def test_validate_key_handler_returns_prod_permission_denial_and_key_id(monkeypatch):
    denial_manager = _FakeKeyManager(
        {"user_id": "fake-user", "permissions": ["llm:models"], "key_id": "fake-key-id"}
    )
    handler = _load_validate_key_handler(monkeypatch, denial_manager, _FakePool())
    denial_response = asyncio.run(
        handler(_FakeRequest({"key": "uc_test_fake", "required_permission": "mcp:accounting-ops"}))
    )
    denial = json.loads(denial_response.body)
    assert denial_response.status_code == 200
    assert denial == {
        "valid": False,
        "reason": "missing_permission",
        "required_permission": "mcp:accounting-ops",
        "permissions": ["llm:models"],
    }

    valid_manager = _FakeKeyManager(
        {
            "user_id": "fake-user",
            "permissions": '["mcp:accounting-ops"]',
            "key_id": "fake-key-id",
        }
    )
    handler = _load_validate_key_handler(monkeypatch, valid_manager, _FakePool())
    valid_response = asyncio.run(
        handler(_FakeRequest({"key": "uc_test_fake", "required_permission": "mcp:accounting-ops"}))
    )
    valid = json.loads(valid_response.body)
    assert valid["valid"] is True
    assert valid["user"]["key_id"] == "fake-key-id"
    assert valid["user"]["permissions"] == ["mcp:accounting-ops"]


def _signup_condition():
    tree = ast.parse(SERVER_SOURCE)
    oauth_login = next(node for node in tree.body if isinstance(node, ast.AsyncFunctionDef) and node.name == "oauth_login")
    return next(
        node.test
        for node in ast.walk(oauth_login)
        if isinstance(node, ast.If) and "KEYCLOAK_REGISTRATION_ENABLED" in ast.unparse(node.test)
    )


def _evaluate_signup_condition(value):
    getenv = lambda name, default="": value if name == "KEYCLOAK_REGISTRATION_ENABLED" else default
    namespace = {"os": SimpleNamespace(getenv=getenv), "signup": True}
    expression = ast.Expression(_signup_condition())
    ast.fix_missing_locations(expression)
    return eval(compile(expression, str(SERVER_PATH), "eval"), namespace)


def test_signup_prompt_is_enabled_only_for_truthy_registration_env(monkeypatch):
    assert _evaluate_signup_condition("1") is True
    assert _evaluate_signup_condition("true") is True
    assert _evaluate_signup_condition("yes") is True
    assert _evaluate_signup_condition("") is False
    assert _evaluate_signup_condition("0") is False
    monkeypatch.delenv("KEYCLOAK_REGISTRATION_ENABLED", raising=False)
    assert 'os.getenv("KEYCLOAK_REGISTRATION_ENABLED", "")' in SERVER_SOURCE


def _csrf_client():
    async def endpoint(request):
        return JSONResponse({"ok": True})

    routes = [
        Route(path, endpoint, methods=["POST"])
        for path in (
            "/api/v1/audio/speech",
            "/api/v1/mcp/meter",
            "/api/v1/llm/chat/completions",
            "/api/v1/account/uc-api-keys/mint-via-token",
            "/api/v1/account/uc-api-keys/revoke-self",
        )
    ]
    app = Starlette(routes=routes)
    app.add_middleware(
        CSRFMiddleware,
        csrf_protect=CSRFProtection(secret_key="t" * 32),
        exempt_urls={"/never-matches/"},
        enabled=True,
        sessions_store={"fictional-session": {}},
    )
    app.add_middleware(OpenAIV1AliasMiddleware)
    return TestClient(app)


@pytest.mark.parametrize(
    "path",
    (
        "/api/v1/audio/speech",
        "/api/v1/mcp/meter",
        "/v1/chat/completions",
        "/api/v1/account/uc-api-keys/mint-via-token",
        "/api/v1/account/uc-api-keys/revoke-self",
    ),
)
def test_bearer_without_session_skips_csrf_for_restored_machine_paths(path):
    response = _csrf_client().post(path, headers={"Authorization": "Bearer x"}, json={})
    assert response.status_code == 200


@pytest.mark.parametrize(
    "path",
    (
        "/api/v1/audio/speech",
        "/api/v1/mcp/meter",
        "/v1/chat/completions",
        "/api/v1/account/uc-api-keys/mint-via-token",
        "/api/v1/account/uc-api-keys/revoke-self",
    ),
)
def test_bearer_with_session_still_requires_csrf_for_restored_machine_paths(path):
    client = _csrf_client()
    client.cookies.set("session_token", "fictional-session")
    response = client.post(path, headers={"Authorization": "Bearer x"}, json={})
    assert response.status_code == 403


def _included_router_names():
    tree = ast.parse(SERVER_SOURCE)
    names = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr != "include_router" or not node.args:
            continue
        router = node.args[0]
        if isinstance(router, ast.Name):
            names.append(router.id)
        elif isinstance(router, ast.Attribute) and isinstance(router.value, ast.Name):
            names.append(f"{router.value.id}.{router.attr}")
    return names


def test_all_prod_only_route_families_are_registered_before_spa_catchall():
    names = set(_included_router_names())
    operation_router = {
        **{operation: "trial_codes_admin_router" for operation in PROD_ONLY_OPERATIONS[:6]},
        "POST /api/v1/mcp/meter": "mcp_meter_router",
        "GET /api/v1/public/beta/health": "beta_signup_router",
        "GET /api/v1/public/beta/programs": "beta_signup_router",
        "POST /api/v1/public/beta/signup": "beta_signup_router",
        "POST /api/v1/trial-codes/redeem": "trial_codes_user_router",
        "GET /api/v1/trial-codes/validate/{code}": "trial_codes_user_router",
        **{operation: "uuda_drift_router" for operation in PROD_ONLY_OPERATIONS[12:15]},
        "GET /api/v1/uuda/drift/history": "uuda_scheduler_mod.router",
        "POST /api/v1/uuda/drift/scan": "uuda_drift_router",
        "GET /api/v1/uuda/drift/scheduler": "uuda_scheduler_mod.router",
        "GET /api/v1/uuda/drift/summary": "uuda_scheduler_mod.router",
        "POST /api/v1/uuda/drift/{device_id}/remediate": "uuda_drift_router",
        "POST /api/v1/uuda/drift/{device_id}/scan": "uuda_drift_router",
        "GET /api/v1/uuda/mcp/approvals": "uuda_mcp_router",
        "POST /api/v1/uuda/mcp/approvals/{pending_id}/approve": "uuda_mcp_router",
        "POST /api/v1/uuda/mcp/approvals/{pending_id}/reject": "uuda_mcp_router",
        "POST /api/v1/uuda/mcp/fanout": "uuda_mcp_router",
        "POST /api/v1/uuda/mcp/{device_id}/call": "uuda_mcp_router",
        "GET /api/v1/uuda/mcp/{device_id}/tools": "uuda_mcp_router",
        "GET /mail/{path}": "listmonk_public_router",
        "POST /mail/{path}": "listmonk_public_router",
    }
    assert set(operation_router) == set(PROD_ONLY_OPERATIONS)
    assert set(operation_router.values()).issubset(names)
    assert "uuda_router" in names
    assert "uuda_scheduler_mod.router" in names
    assert "uuda_scheduler_mod.attach(app)" in SERVER_SOURCE
    assert "_UUDA_IMPORT_ERROR" in SERVER_SOURCE
    assert 'logger.error("UUDA control plane NOT mounted' in SERVER_SOURCE

    beta_position = SERVER_SOURCE.index("app.include_router(beta_signup_router)")
    mail_position = SERVER_SOURCE.index("app.include_router(listmonk_public_router)")
    catchall_position = SERVER_SOURCE.index('\n@app.get("/{full_path:path}")')
    assert beta_position < catchall_position
    assert mail_position < catchall_position


def test_alias_is_last_server_middleware_and_both_limiters_use_uuda_key():
    tree = ast.parse(SERVER_SOURCE)
    middleware_calls = sorted([
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "add_middleware"
    ], key=lambda node: node.lineno)
    assert isinstance(middleware_calls[-1].args[0], ast.Name)
    assert middleware_calls[-1].args[0].id == "OpenAIV1AliasMiddleware"

    limiter_calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "Limiter"
    ]
    assert len(limiter_calls) == 2
    assert all(
        any(
            keyword.arg == "key_func"
            and isinstance(keyword.value, ast.Name)
            and keyword.value.id == "uuda_aware_rate_limit_key"
            for keyword in call.keywords
        )
        for call in limiter_calls
    )
