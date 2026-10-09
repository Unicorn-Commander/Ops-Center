"""Regression tests for shared Redis session configuration and auth fail-fast behavior."""

import importlib.util
import sys
import time
import types
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest
import redis
from fastapi import FastAPI


BACKEND = Path(__file__).resolve().parents[1]


class FakeRedisClient:
    def __init__(self, *, get_error=None):
        self.get_error = get_error
        self.get_calls = 0
        self.ping_calls = 0

    def ping(self):
        self.ping_calls += 1

    def get(self, _key):
        self.get_calls += 1
        if self.get_error:
            raise self.get_error
        return None


def load_redis_session_module(monkeypatch, *, url):
    client = FakeRedisClient()
    captured = {}

    def fake_from_url(redis_url, **kwargs):
        captured["url"] = redis_url
        captured["kwargs"] = kwargs
        return client

    monkeypatch.setattr(redis.Redis, "from_url", staticmethod(fake_from_url))
    monkeypatch.setenv("REDIS_URL", url)
    monkeypatch.setenv("REDIS_CONNECT_ATTEMPTS", "1")
    monkeypatch.setenv("REDIS_CONNECT_RETRY_DELAY", "0")

    module_name = "redis_session_fail_fast_fixture"
    spec = importlib.util.spec_from_file_location(module_name, BACKEND / "redis_session.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module, client, captured


def test_password_from_redis_url_is_applied(monkeypatch):
    module, client, captured = load_redis_session_module(
        monkeypatch,
        url="redis://:fixture%2Fpassword@redis.example:6380/4",
    )

    assert module.redis_session_manager.password == "fixture/password"
    assert captured["url"] == "redis://redis.example:6380/4"
    assert captured["kwargs"]["password"] == "fixture/password"
    assert captured["kwargs"]["retry_on_timeout"] is False
    assert client.ping_calls == 1


def test_request_session_lookup_does_not_sleep_or_retry(monkeypatch):
    module, client, _ = load_redis_session_module(
        monkeypatch,
        url="redis://redis.example:6379/0",
    )
    client.get_error = RuntimeError("redis unavailable")
    sleep = Mock(side_effect=AssertionError("request path slept"))
    monkeypatch.setattr(time, "sleep", sleep)

    started = time.monotonic()
    with pytest.raises(module.RedisSessionUnavailable):
        module.redis_session_manager.get_for_request("session-token")
    elapsed = time.monotonic() - started

    assert elapsed < 1
    assert client.get_calls == 1
    sleep.assert_not_called()


@pytest.mark.asyncio
async def test_invalid_bearer_is_401_before_redis(monkeypatch):
    """A malformed bearer must not reach the request-time Redis accessor."""
    # asyncpg is an optional deployment dependency and is absent from this
    # system Python. The federation router only needs its type names at import.
    if "asyncpg" not in sys.modules:
        try:
            import asyncpg  # noqa: F401
        except ModuleNotFoundError:
            asyncpg_stub = types.ModuleType("asyncpg")
            asyncpg_stub.Pool = object
            asyncpg_stub.Record = dict
            asyncpg_stub.create_pool = None
            asyncpg_stub.connect = None
            monkeypatch.setitem(sys.modules, "asyncpg", asyncpg_stub)

    unavailable = type("RedisSessionUnavailable", (RuntimeError,), {})
    redis_calls = []

    def fail_fast(_token):
        redis_calls.append(_token)
        raise unavailable("redis unavailable")

    fake_redis_session = types.ModuleType("redis_session")
    fake_redis_session.RedisSessionUnavailable = unavailable
    fake_redis_session.redis_session_manager = SimpleNamespace(
        get_for_request=fail_fast,
    )
    monkeypatch.setitem(sys.modules, "redis_session", fake_redis_session)
    monkeypatch.setenv("FEDERATION_KEY", "configured-federation-key")

    if str(BACKEND) not in sys.path:
        sys.path.insert(0, str(BACKEND))
    import federation.auth as federation_auth
    federation_auth._auth = None
    import routers.federation as federation_router

    app = FastAPI()
    app.include_router(federation_router.router)
    started = time.monotonic()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
    ) as client:
        response = await client.get(
            "/api/v1/federation/nodes",
            headers={"Authorization": "Bearer bogus"},
        )
    elapsed = time.monotonic() - started

    assert response.status_code == 401, response.text
    assert elapsed < 1
    assert redis_calls == []
