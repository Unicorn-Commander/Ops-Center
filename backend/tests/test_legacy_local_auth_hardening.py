"""Regression tests for the opt-in legacy local authentication surface."""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi import FastAPI
from fastapi.testclient import TestClient
from auth_manager import AuthManager, LoginCredentials, require_local_auth_enabled
from auth_middleware import AuthenticationMiddleware, build_public_prefixes


def make_manager(monkeypatch, tmp_path, *, enabled, admin_password=None):
    monkeypatch.setenv("AUTH_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("LEGACY_LOCAL_AUTH_ENABLED", "true" if enabled else "false")
    if admin_password is None:
        monkeypatch.delenv("ADMIN_PASSWORD", raising=False)
    else:
        monkeypatch.setenv("ADMIN_PASSWORD", admin_password)
    return AuthManager()


def test_default_disabled_has_no_admin_and_legacy_verify_rejects(monkeypatch, tmp_path):
    manager = make_manager(monkeypatch, tmp_path, enabled=False)

    assert manager.users == {}
    assert manager.verify_token("not-a-token") is None
    assert "/api/v1/auth/login" not in build_public_prefixes(False)


def test_enabled_without_password_has_no_admin(monkeypatch, tmp_path):
    manager = make_manager(monkeypatch, tmp_path, enabled=True)

    assert manager.users == {}


def test_enabled_with_short_password_has_no_admin(monkeypatch, tmp_path):
    manager = make_manager(monkeypatch, tmp_path, enabled=True, admin_password="short")

    assert manager.users == {}


def test_enabled_with_strong_password_can_login(monkeypatch, tmp_path):
    manager = make_manager(
        monkeypatch,
        tmp_path,
        enabled=True,
        admin_password="Strong-local-admin-2026!",
    )

    token = asyncio.run(
        manager.login(
            LoginCredentials(username="ucadmin", password="Strong-local-admin-2026!"),
            {"ip_address": "127.0.0.1", "user_agent": "test"},
        )
    )
    assert manager.verify_token(token.access_token)["role"] == "admin"
    assert "/api/v1/auth/login" in build_public_prefixes(True)


def test_local_auth_dependency_returns_not_found_when_disabled(monkeypatch):
    monkeypatch.setenv("LEGACY_LOCAL_AUTH_ENABLED", "false")

    try:
        asyncio.run(require_local_auth_enabled())
    except Exception as exc:
        assert exc.status_code == 404
    else:
        raise AssertionError("disabled local auth dependency did not reject the request")


def test_disabled_login_is_404_before_session_gate(monkeypatch):
    monkeypatch.setenv("LEGACY_LOCAL_AUTH_ENABLED", "false")
    app = FastAPI()

    @app.post("/api/v1/auth/login")
    async def login_stub():
        return {"unexpected": "reachable"}

    app.add_middleware(AuthenticationMiddleware, enabled=True)
    response = TestClient(app).post("/api/v1/auth/login")

    assert response.status_code == 404
