"""The home keeps the person's access token usable (``home.session_tokens``).

Keycloak is ``FakeKeycloak`` (an httpx MockTransport) and Redis is ``FakeRedis``:
the few redis-py calls ``RedisSessionStore`` makes, with TTLs on a fake clock
and WATCH/MULTI/EXEC that fails when a watched key changed. server.py is never
imported: its two session-writing spots are read with ``ast`` and the dict each
one builds is evaluated with fictional inputs. Every token is an unsigned,
token-shaped string with fictional claims; the client secret, the Keycloak
hosts, Rivergreen Coffee Co. and its people are fictional.
"""

from __future__ import annotations

import ast
import asyncio
import base64
import json
import logging
import sys
import time
from types import ModuleType, SimpleNamespace
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import parse_qsl

import httpx
import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

import home_api
from home import session_tokens
from home.context import HomeContext
from homekit import BACKEND, NOW, ORG_ID, PERSON_SUB, FakeSuite, load, module_by_id, suite_routes
from test_home_route import real_binding_client

SERVER = BACKEND / "server.py"
NOW_TS = NOW.timestamp()
PREFIX = "session:"
SESSION_ID = "sess-rivergreen-0001"
SECRET = "rivergreen-fictional-client-secret"
KC_INTERNAL = "http://keycloak.rivergreen.example:8080"
KC_EXTERNAL = "https://auth.rivergreen.example"
REALM = "rivergreen"
INTERNAL_ENDPOINT = f"{KC_INTERNAL}/realms/{REALM}/protocol/openid-connect/token"
EXTERNAL_ENDPOINT = f"{KC_EXTERNAL}/realms/{REALM}/protocol/openid-connect/token"
SIGN_IN_ENV = ("KEYCLOAK_URL", "KEYCLOAK_EXTERNAL_URL", "KEYCLOAK_REALM", "EXTERNAL_HOST", session_tokens.CLIENT_SECRET_ENV)


def jwt(kind: str, seconds_left: float, n: int = 1) -> str:
    """Token-shaped, unsigned, fictional: never a credential."""

    def part(data: Dict[str, Any]) -> str:
        return base64.urlsafe_b64encode(json.dumps(data).encode()).decode().rstrip("=")

    claims = {"sub": PERSON_SUB, "exp": int(NOW_TS + seconds_left), "typ": kind, "jti": f"rivergreen-{kind}-{n}"}
    return ".".join([part({"alg": "none"}), part(claims), f"unsigned-{kind}-{n}"])


OLD_ACCESS = jwt("access", 30)
NEW_ACCESS = jwt("access", 900, 2)
OLD_REFRESH = jwt("refresh", 1500)
NEW_REFRESH = jwt("refresh", 1800, 2)
NEVER_LOGGED = (OLD_ACCESS, NEW_ACCESS, OLD_REFRESH, NEW_REFRESH, SECRET, SESSION_ID)


def stored_session(*, access: str = OLD_ACCESS, access_left: Optional[float] = 30, refresh: Optional[str] = OLD_REFRESH,
                   refresh_left: Optional[float] = 1500, login_method: Optional[str] = "oauth_callback") -> Dict[str, Any]:
    return {
        "user": {"sub": PERSON_SUB, "name": "Mara Okonkwo", "email": "mara@rivergreen.example"},
        "access_token": access,
        "refresh_token": refresh,
        "access_token_expires_at": None if access_left is None else NOW_TS + access_left,
        "refresh_token_expires_at": None if refresh_left is None else NOW_TS + refresh_left,
        "login_method": login_method,
        "id_token": "rivergreen-id-token-kept-for-logout",
        "created": NOW_TS - 870,
        "org_id": ORG_ID,
        "org_name": "Rivergreen Coffee Co.",
        "org_role": "owner",
    }


# --------------------------------------------------------------------------- #
# Fakes
# --------------------------------------------------------------------------- #


class FakeWatchError(Exception):
    """redis-py's WatchError, for a fake that runs without redis-py."""


class FakeRedis:
    """GET, SET (NX, PX), PTTL, DEL and WATCH/MULTI/EXEC pipelines, as redis-py
    with ``decode_responses=True`` exposes them, on a millisecond fake clock."""

    def __init__(self):
        self.values: Dict[str, str] = {}
        self.deadlines: Dict[str, int] = {}
        self.versions: Dict[str, int] = {}
        self.clock_ms = 0
        self.commands: List[str] = []
        self.before_exec: Optional[Callable[[List[Tuple[Any, ...]]], None]] = None

    def _live(self, key: str) -> bool:
        deadline = self.deadlines.get(key)
        if deadline is not None and deadline <= self.clock_ms:
            self._remove(key)
        return key in self.values

    def _remove(self, key: str) -> None:
        self.values.pop(key, None)
        self.deadlines.pop(key, None)
        self.versions[key] = self.versions.get(key, 0) + 1

    def _write(self, key: str, value: str, px: Optional[int]) -> None:
        self.values[key] = value
        if px is None:
            self.deadlines.pop(key, None)
        else:
            self.deadlines[key] = self.clock_ms + int(px)
        self.versions[key] = self.versions.get(key, 0) + 1

    def get(self, key):
        self.commands.append(f"GET {key}")
        return self.values[key] if self._live(key) else None

    def set(self, key, value, nx=False, px=None):
        self.commands.append(f"SET {key}")
        if nx and self._live(key):
            return None
        self._write(key, value, px)
        return True

    def pttl(self, key):
        self.commands.append(f"PTTL {key}")
        if not self._live(key):
            return -2
        deadline = self.deadlines.get(key)
        return -1 if deadline is None else deadline - self.clock_ms

    def delete(self, key):
        self.commands.append(f"DEL {key}")
        if not self._live(key):
            return 0
        self._remove(key)
        return 1

    def pipeline(self):
        return FakePipeline(self)

    # Test helpers
    def put_session(self, session: Dict[str, Any], ttl_ms: Optional[int] = 7_200_000) -> None:
        self._write(PREFIX + SESSION_ID, json.dumps(session), ttl_ms)

    def session(self) -> Optional[Dict[str, Any]]:
        raw = self.values.get(PREFIX + SESSION_ID)
        return None if raw is None else json.loads(raw)

    def session_pttl(self) -> int:
        return self.pttl(PREFIX + SESSION_ID)


class FakePipeline:
    def __init__(self, redis: FakeRedis):
        self.redis = redis
        self.watched: Dict[str, int] = {}
        self.queue: Optional[List[Tuple[Any, ...]]] = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.reset()
        return False

    def reset(self):
        self.watched, self.queue = {}, None

    def watch(self, *keys):
        for key in keys:
            self.redis._live(key)
            self.watched[key] = self.redis.versions.get(key, 0)

    def multi(self):
        self.queue = []

    def get(self, key):
        assert self.queue is None, "a read inside MULTI returns nothing in redis-py"
        return self.redis.get(key)

    def pttl(self, key):
        assert self.queue is None
        return self.redis.pttl(key)

    def set(self, key, value, px=None):
        assert self.queue is not None, "a write must be queued after MULTI"
        self.queue.append(("set", key, value, px))

    def delete(self, key):
        assert self.queue is not None
        self.queue.append(("delete", key))

    def execute(self):
        queue = list(self.queue or [])
        if self.redis.before_exec is not None:
            self.redis.before_exec(queue)
        for key, version in self.watched.items():
            self.redis._live(key)
            if self.redis.versions.get(key, 0) != version:
                self.reset()
                raise FakeWatchError()
        for op in queue:
            if op[0] == "set":
                self.redis.set(op[1], op[2], px=op[3])
            else:
                self.redis.delete(op[1])
        self.reset()
        return [True] * len(queue)


def kc_ok(access: str = NEW_ACCESS, refresh: Optional[str] = NEW_REFRESH, expires_in: Any = 900,
          refresh_expires_in: Any = 1800) -> httpx.Response:
    body = {
        "access_token": access, "expires_in": expires_in, "refresh_expires_in": refresh_expires_in,
        "token_type": "Bearer", "id_token": "rivergreen-new-id-token", "not-before-policy": 0,
        "session_state": "rivergreen-session-state", "scope": "openid profile email",
    }
    if refresh is not None:
        body["refresh_token"] = refresh
    return httpx.Response(200, json=body)


class FakeKeycloak:
    """The token endpoint. Answers in order (the last one repeats); an
    exception is raised as the transport would raise it."""

    def __init__(self, *answers: Any, gate: Optional[asyncio.Event] = None,
                 before: Optional[Callable[[httpx.Request], None]] = None):
        self.answers = list(answers) or [kc_ok()]
        self.requests: List[httpx.Request] = []
        self.gate = gate
        self.before = before

    async def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.before is not None:
            self.before(request)
        if self.gate is not None:
            await self.gate.wait()
        answer = self.answers[min(len(self.requests), len(self.answers)) - 1]
        if isinstance(answer, BaseException):
            raise answer
        if callable(answer):
            answer = await answer(request)
        return answer

    def factory(self, timeout: float) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self.handle), timeout=timeout, follow_redirects=False)

    def forms(self) -> List[Dict[str, str]]:
        return [dict(parse_qsl(request.content.decode())) for request in self.requests]


@pytest.fixture(autouse=True)
def sign_in_env(monkeypatch):
    for name in SIGN_IN_ENV:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("KEYCLOAK_URL", KC_INTERNAL)
    monkeypatch.setenv("KEYCLOAK_EXTERNAL_URL", KC_EXTERNAL)
    monkeypatch.setenv("KEYCLOAK_REALM", REALM)
    monkeypatch.setenv(session_tokens.CLIENT_SECRET_ENV, SECRET)
    yield


def store_for(redis: FakeRedis) -> session_tokens.RedisSessionStore:
    return session_tokens.RedisSessionStore(redis, PREFIX, watch_error=FakeWatchError)


async def usable(session: Dict[str, Any], redis: FakeRedis, keycloak: FakeKeycloak, *, timeout: float = 2.0,
                 request_url: str = "https://home.rivergreen.example/api/v1/home/state") -> Optional[str]:
    return await session_tokens.usable_access_token(
        SESSION_ID, dict(session), now=NOW_TS, timeout=timeout, request_url=request_url,
        store=store_for(redis), client_factory=keycloak.factory,
    )


def lock_key() -> str:
    return session_tokens.RedisSessionStore.lock_key(SESSION_ID)


def assert_nothing_secret_logged(caplog):
    for value in NEVER_LOGGED:
        assert value not in caplog.text
    for record in caplog.records:
        rendered = record.getMessage()
        for value in NEVER_LOGGED:
            assert value not in rendered


# --------------------------------------------------------------------------- #
# Sign-in: what both paths now keep in the session
# --------------------------------------------------------------------------- #


def test_login_fields_come_from_the_token_response():
    tokens = {"access_token": OLD_ACCESS, "expires_in": 300, "refresh_expires_in": 1800, "refresh_token": OLD_REFRESH}
    fields = session_tokens.login_token_fields(tokens, "oauth_callback", now=NOW_TS)
    assert fields == {
        "refresh_token": OLD_REFRESH,
        "access_token_expires_at": NOW_TS + 300,
        "refresh_token_expires_at": NOW_TS + 1800,
        "login_method": "oauth_callback",
    }


def test_login_fields_fall_back_to_the_tokens_exp_claims():
    # No expires_in: the access token's exp. refresh_expires_in 0 (Keycloak's
    # "no expiry" value): the refresh token's own exp.
    tokens = {"access_token": OLD_ACCESS, "refresh_expires_in": 0, "refresh_token": OLD_REFRESH}
    fields = session_tokens.login_token_fields(tokens, "direct_login", now=NOW_TS)
    assert fields["access_token_expires_at"] == int(NOW_TS + 30)
    assert fields["refresh_token_expires_at"] == int(NOW_TS + 1500)
    assert fields["refresh_token"] == OLD_REFRESH and fields["login_method"] == "direct_login"

    opaque = session_tokens.login_token_fields({"access_token": "opaque", "refresh_token": "opaque-too"}, "direct_login")
    assert opaque["access_token_expires_at"] is None and opaque["refresh_token_expires_at"] is None
    assert opaque["refresh_token"] == "opaque-too"


@pytest.mark.parametrize("tokens", [
    None, [], "text", {"refresh_token": 42, "expires_in": "soon"}, {"access_token": "a.b.c", "expires_in": True},
    {"access_token": "x.%%%.y", "refresh_token": "x.e30.y", "expires_in": float("nan"), "refresh_expires_in": -5},
])
def test_login_fields_never_raise_and_store_no_refresh_token_they_cannot_read(tokens):
    fields = session_tokens.login_token_fields(tokens, "oauth_callback")
    assert fields["login_method"] == "oauth_callback"
    assert set(fields) == {"refresh_token", "access_token_expires_at", "refresh_token_expires_at", "login_method"}
    if not isinstance(tokens, dict) or not isinstance(tokens.get("refresh_token"), str):
        assert fields["refresh_token"] is None


def sign_in_session_node(function: str) -> Tuple[ast.Dict, ast.AsyncFunctionDef]:
    tree = ast.parse(SERVER.read_text(encoding="utf-8"))
    handler = next(n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef) and n.name == function)
    found = [
        node.value for node in ast.walk(handler)
        if isinstance(node, ast.Assign) and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Subscript)
        and isinstance(node.targets[0].value, ast.Name) and node.targets[0].value.id == "sessions"
        and isinstance(node.value, ast.Dict)
        and any(isinstance(k, ast.Constant) and k.value == "user" for k in node.value.keys)
    ]
    assert len(found) == 1, function
    return found[0], handler


@pytest.mark.parametrize("function, kept", [
    ("direct_login", {"user", "access_token", "created", "org_id", "org_name", "org_role"}),
    ("oauth_callback", {"user", "access_token", "id_token", "created", "org_id", "org_name", "org_role",
                        "subscription_tier"}),
])
def test_both_sign_in_paths_store_the_refresh_token_and_expiries(monkeypatch, function, kept):
    node, handler = sign_in_session_node(function)
    # The helper is imported inside the handler, just before the session is written.
    imports = [n for n in ast.walk(handler) if isinstance(n, ast.ImportFrom) and n.module == "home.session_tokens"]
    assert [alias.name for n in imports for alias in n.names] == ["login_token_fields"]
    assert imports[0].lineno < node.lineno

    created = NOW_TS - 5
    monkeypatch.setattr(session_tokens, "time", SimpleNamespace(time=lambda: created))
    tokens = {"access_token": OLD_ACCESS, "expires_in": 300, "refresh_expires_in": 1800,
              "refresh_token": OLD_REFRESH, "id_token": "rivergreen-id-token"}
    user_info = {"sub": PERSON_SUB, "preferred_username": "mara", "role": "viewer"}
    org_context = {"org_id": ORG_ID, "org_name": "Rivergreen Coffee Co.", "org_role": "owner",
                   "subscription_tier": "managed"}
    namespace = {
        "user_info": user_info, "access_token": OLD_ACCESS, "tokens": tokens, "org_context": org_context,
        "time": SimpleNamespace(time=lambda: created), "login_token_fields": session_tokens.login_token_fields,
    }
    session = eval(compile(ast.Expression(body=node), str(SERVER), "eval"), namespace)  # noqa: S307 - server.py's own literal

    assert set(session) == kept | {"refresh_token", "access_token_expires_at", "refresh_token_expires_at", "login_method"}
    assert session["refresh_token"] == OLD_REFRESH
    assert session["access_token_expires_at"] == created + 300
    assert session["refresh_token_expires_at"] == created + 1800
    assert session["login_method"] == function
    # Everything that was there before is there, unchanged.
    assert session["user"] is user_info and session["access_token"] == OLD_ACCESS and session["created"] == created
    assert (session["org_id"], session["org_name"], session["org_role"]) == (ORG_ID, "Rivergreen Coffee Co.", "owner")
    if function == "oauth_callback":
        assert session["id_token"] == "rivergreen-id-token" and session["subscription_tier"] == "managed"


def test_the_refresh_goes_where_each_sign_in_path_got_its_tokens(monkeypatch):
    source = SERVER.read_text(encoding="utf-8")
    tree = ast.parse(source)

    def handler_source(name: str) -> str:
        node = next(n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef) and n.name == name)
        return ast.get_source_segment(source, node)

    direct, callback = handler_source("direct_login"), handler_source("oauth_callback")
    # The settings mirrored in session_tokens are still the ones server.py uses.
    assert 'OAUTH_CLIENT_ID = "ops-center"' in source and session_tokens.OAUTH_CLIENT_ID == "ops-center"
    assert f'OAUTH_CLIENT_SECRET = os.environ.get("{session_tokens.CLIENT_SECRET_ENV}"' in source
    assert 'EXTERNAL_HOST = os.environ.get("EXTERNAL_HOST", "192.168.1.135")' in source
    assert 'keycloak_realm = os.getenv("KEYCLOAK_REALM", "master")' in direct
    assert 'if "yoda.unicorncommander.ai" in str(request.url):' in direct
    assert 'auth_url = os.getenv("KEYCLOAK_EXTERNAL_URL", f"https://auth.{EXTERNAL_HOST}")' in direct
    assert 'token_url = f"{auth_url}/realms/{keycloak_realm}/protocol/openid-connect/token"' in direct
    assert 'keycloak_realm = os.getenv("KEYCLOAK_REALM", "uchub")' in callback
    assert 'keycloak_url = os.getenv("KEYCLOAK_URL", "http://centerdeep-keycloak:8080")' in callback
    assert 'token_url = f"{keycloak_url}/realms/{keycloak_realm}/protocol/openid-connect/token"' in callback
    for handler in (direct, callback):
        assert '"client_id": OAUTH_CLIENT_ID' in handler and '"client_secret": OAUTH_CLIENT_SECRET' in handler

    endpoint = session_tokens.token_endpoint
    assert endpoint("oauth_callback") == INTERNAL_ENDPOINT
    assert endpoint("direct_login") == EXTERNAL_ENDPOINT
    assert endpoint("direct_login", "https://yoda.unicorncommander.ai/api/v1/home/state") == (
        f"https://auth.yoda.unicorncommander.ai/realms/{REALM}/protocol/openid-connect/token"
    )
    monkeypatch.delenv("KEYCLOAK_EXTERNAL_URL")
    monkeypatch.setenv("EXTERNAL_HOST", "rivergreen.example")
    assert endpoint("direct_login") == f"https://auth.rivergreen.example/realms/{REALM}/protocol/openid-connect/token"
    for name in ("KEYCLOAK_URL", "KEYCLOAK_REALM", "EXTERNAL_HOST"):
        monkeypatch.delenv(name)
    assert endpoint("oauth_callback") == "http://centerdeep-keycloak:8080/realms/uchub/protocol/openid-connect/token"
    assert endpoint("direct_login") == "https://auth.192.168.1.135/realms/master/protocol/openid-connect/token"
    assert endpoint(None) is None and endpoint("password") is None


# --------------------------------------------------------------------------- #
# The refresh
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
@pytest.mark.parametrize("seconds_left", [61, 600])
async def test_a_fresh_token_is_used_as_is_without_keycloak_or_redis(seconds_left):
    redis, keycloak = FakeRedis(), FakeKeycloak()
    session = stored_session(access_left=seconds_left)
    redis.put_session(session)
    redis.commands.clear()
    assert await usable(session, redis, keycloak) == OLD_ACCESS
    assert keycloak.requests == [] and redis.commands == []


@pytest.mark.asyncio
async def test_a_token_near_expiry_is_refreshed_once_and_the_session_updated(caplog):
    caplog.set_level(logging.DEBUG)
    redis, keycloak = FakeRedis(), FakeKeycloak(kc_ok())
    session = stored_session(access_left=60)  # "expires within 60 s" includes 60
    redis.put_session(session)
    redis.clock_ms = 870_000  # the session is 14.5 minutes old
    ttl_before = redis.session_pttl()

    assert await usable(session, redis, keycloak) == NEW_ACCESS

    assert [str(r.url) for r in keycloak.requests] == [INTERNAL_ENDPOINT]
    assert keycloak.requests[0].method == "POST"
    assert keycloak.forms() == [{
        "grant_type": "refresh_token", "refresh_token": OLD_REFRESH, "client_id": "ops-center", "client_secret": SECRET,
    }]
    stored = redis.session()
    assert stored == {
        **session,
        "access_token": NEW_ACCESS,
        "refresh_token": NEW_REFRESH,
        "access_token_expires_at": NOW_TS + 900,
        "refresh_token_expires_at": NOW_TS + 1800,
    }  # and nothing else changed: user, id_token, created, org, login_method
    assert redis.session_pttl() == ttl_before  # the session ends when it would have ended
    assert redis.get(lock_key()) is None  # the lock is gone
    assert "home session: access token refreshed" in caplog.text
    assert_nothing_secret_logged(caplog)

    # The next request finds the new token fresh: no second refresh.
    assert await usable(stored, redis, keycloak) == NEW_ACCESS
    assert len(keycloak.requests) == 1


@pytest.mark.asyncio
async def test_a_password_sign_in_refreshes_at_the_url_it_signed_in_at():
    redis, keycloak = FakeRedis(), FakeKeycloak(kc_ok())
    session = stored_session(login_method="direct_login")
    redis.put_session(session)
    assert await usable(session, redis, keycloak) == NEW_ACCESS
    assert [str(r.url) for r in keycloak.requests] == [EXTERNAL_ENDPOINT]


@pytest.mark.asyncio
async def test_without_a_new_refresh_token_the_old_one_stays():
    redis, keycloak = FakeRedis(), FakeKeycloak(kc_ok(refresh=None, expires_in=None))
    session = stored_session()
    redis.put_session(session)
    assert await usable(session, redis, keycloak) == NEW_ACCESS
    stored = redis.session()
    assert stored["refresh_token"] == OLD_REFRESH
    assert stored["refresh_token_expires_at"] == session["refresh_token_expires_at"]
    assert stored["access_token_expires_at"] == int(NOW_TS + 900)  # the new token's exp claim


async def _slow(request: httpx.Request) -> httpx.Response:
    await asyncio.sleep(5)
    return kc_ok()


async def _echo_html(request: httpx.Request) -> httpx.Response:
    return httpx.Response(500, text=f"<html>{request.content.decode()} {OLD_REFRESH}</html>")


async def _answer_without_token(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={"token_type": "Bearer", "refresh_token": NEW_REFRESH, "echo": SECRET})


@pytest.mark.asyncio
@pytest.mark.parametrize("answer, logged", [
    (httpx.Response(400, json={"error": "invalid_grant", "error_description": f"Token is not active {OLD_REFRESH}"}),
     "HTTP 400, invalid_grant"),
    (httpx.Response(401, json={"error": "invalid_client", "error_description": f"bad secret {SECRET}"}),
     "HTTP 401, invalid_client"),
    (httpx.Response(400, json={"error": f"made-up {OLD_REFRESH}"}), "(HTTP 400)"),
    (_echo_html, "(HTTP 500)"),
    (httpx.Response(200, text=f"not json {NEW_ACCESS}"), "was not JSON"),
    (_answer_without_token, "had no access token"),
    (httpx.ConnectError("connection refused"), "could not reach Keycloak (ConnectError)"),
    (_slow, "timed out"),
])
async def test_a_failed_refresh_is_reauth_and_logs_no_token_secret_or_body(caplog, answer, logged):
    caplog.set_level(logging.DEBUG)
    redis, keycloak = FakeRedis(), FakeKeycloak(answer)
    session = stored_session()
    redis.put_session(session)

    started = time.monotonic()
    assert await usable(session, redis, keycloak, timeout=0.3) is None
    assert time.monotonic() - started < 2.0

    assert len(keycloak.requests) == 1
    assert redis.session() == session  # nothing written
    assert redis.get(lock_key()) is None  # and the lock released
    assert logged in caplog.text
    assert "error_description" not in caplog.text and "<html>" not in caplog.text
    assert_nothing_secret_logged(caplog)


@pytest.mark.asyncio
async def test_an_expired_refresh_token_is_reauth_without_calling_keycloak():
    redis, keycloak = FakeRedis(), FakeKeycloak(kc_ok())
    session = stored_session(refresh_left=-1)
    redis.put_session(session)
    assert await usable(session, redis, keycloak) is None

    # No stored expiry: the refresh token's own exp claim decides.
    session = stored_session(refresh=jwt("refresh", -10), refresh_left=None)
    redis.put_session(session)
    assert await usable(session, redis, keycloak) is None
    assert keycloak.requests == []


@pytest.mark.asyncio
async def test_two_requests_at_once_spend_the_refresh_token_once():
    gate = asyncio.Event()
    redis, keycloak = FakeRedis(), FakeKeycloak(kc_ok(), gate=gate)
    session = stored_session()
    redis.put_session(session)

    first = asyncio.ensure_future(usable(session, redis, keycloak))
    second = asyncio.ensure_future(usable(session, redis, keycloak))
    await asyncio.sleep(0.15)  # both are in: one holds the lock and waits on Keycloak, one waits on it
    assert len(keycloak.requests) == 1 and not first.done() and not second.done()
    gate.set()
    assert await asyncio.gather(first, second) == [NEW_ACCESS, NEW_ACCESS]
    assert len(keycloak.requests) == 1
    assert redis.session()["refresh_token"] == NEW_REFRESH


@pytest.mark.asyncio
async def test_when_the_lock_holder_fails_the_waiter_does_not_spend_the_token_again():
    gate = asyncio.Event()
    redis = FakeRedis()
    keycloak = FakeKeycloak(httpx.Response(400, json={"error": "invalid_grant"}), gate=gate)
    session = stored_session()
    redis.put_session(session)

    first = asyncio.ensure_future(usable(session, redis, keycloak))
    second = asyncio.ensure_future(usable(session, redis, keycloak))
    await asyncio.sleep(0.15)
    gate.set()
    assert await asyncio.gather(first, second) == [None, None]
    assert len(keycloak.requests) == 1


@pytest.mark.asyncio
async def test_a_lock_that_never_clears_is_waited_on_only_within_the_limit():
    redis, keycloak = FakeRedis(), FakeKeycloak(kc_ok())
    session = stored_session()
    redis.put_session(session)
    redis.set(lock_key(), "another-worker", nx=True, px=60_000)

    started = time.monotonic()
    assert await usable(session, redis, keycloak, timeout=0.3) is None
    assert 0.25 <= time.monotonic() - started < 2.0
    assert keycloak.requests == []
    assert redis.get(lock_key()) == "another-worker"  # never someone else's to delete


@pytest.mark.asyncio
async def test_a_refresh_finished_elsewhere_while_waiting_for_the_lock_is_used():
    redis, keycloak = FakeRedis(), FakeKeycloak(kc_ok())
    stale = stored_session()
    redis.put_session({**stale, "access_token": NEW_ACCESS, "access_token_expires_at": NOW_TS + 900})
    # The request read the session a moment before another worker refreshed it.
    assert await usable(stale, redis, keycloak) == NEW_ACCESS
    assert keycloak.requests == []


@pytest.mark.asyncio
async def test_a_session_signed_out_during_the_refresh_is_not_brought_back():
    redis = FakeRedis()
    keycloak = FakeKeycloak(kc_ok(), before=lambda request: redis.delete(PREFIX + SESSION_ID))
    session = stored_session()
    redis.put_session(session)
    assert await usable(session, redis, keycloak) is None
    assert redis.session() is None and PREFIX + SESSION_ID not in redis.values


@pytest.mark.asyncio
async def test_a_session_write_that_lands_during_the_refresh_is_kept():
    redis, keycloak = FakeRedis(), FakeKeycloak(kc_ok())
    session = stored_session()
    redis.put_session(session)
    ttl_before = redis.session_pttl()
    other_org = "9a8b7c6d-5e4f-4a3b-8c2d-1e0f9a8b7c6d"
    raced = []

    def org_switch_lands_first(queue):
        if not raced and any(op[1] == PREFIX + SESSION_ID for op in queue):
            raced.append(True)
            current = json.loads(redis.values[PREFIX + SESSION_ID])
            redis.set(PREFIX + SESSION_ID, json.dumps({**current, "org_id": other_org}), px=redis.session_pttl())

    redis.before_exec = org_switch_lands_first
    assert await usable(session, redis, keycloak) == NEW_ACCESS
    stored = redis.session()
    assert raced and stored["org_id"] == other_org and stored["access_token"] == NEW_ACCESS
    assert redis.session_pttl() == ttl_before


@pytest.mark.asyncio
async def test_a_session_from_before_this_change_works_until_its_token_runs_out():
    redis, keycloak = FakeRedis(), FakeKeycloak(kc_ok())
    legacy = {"user": {"sub": PERSON_SUB}, "access_token": jwt("access", 600), "org_id": ORG_ID}
    assert await usable(legacy, redis, keycloak) == legacy["access_token"]
    legacy["access_token"] = OLD_ACCESS  # 30 s left and no refresh token
    assert await usable(legacy, redis, keycloak) is None
    assert keycloak.requests == [] and redis.commands == []


@pytest.mark.asyncio
async def test_no_refresh_without_the_client_secret_or_a_known_sign_in_path(monkeypatch):
    redis, keycloak = FakeRedis(), FakeKeycloak(kc_ok())
    session = stored_session()
    redis.put_session(session)
    assert await usable(stored_session(login_method=None), redis, keycloak) is None
    monkeypatch.delenv(session_tokens.CLIENT_SECRET_ENV)
    assert await usable(session, redis, keycloak) is None
    # And no session store at all (the conftest default) is a plain None too.
    monkeypatch.setenv(session_tokens.CLIENT_SECRET_ENV, SECRET)
    assert await session_tokens.usable_access_token(
        SESSION_ID, session, now=NOW_TS, timeout=1.0, client_factory=keycloak.factory
    ) is None
    assert keycloak.requests == []


def test_the_lock_is_released_only_by_its_owner_and_names_no_session():
    redis = FakeRedis()
    store = store_for(redis)
    assert store.acquire(SESSION_ID, "owner-a", 3000) is True
    assert store.acquire(SESSION_ID, "owner-b", 3000) is False
    store.release(SESSION_ID, "owner-b")
    assert store.locked(SESSION_ID)
    store.release(SESSION_ID, "owner-a")
    assert not store.locked(SESSION_ID)
    key = lock_key()
    assert SESSION_ID not in key and not key.startswith(PREFIX)
    assert redis.set(key, "x", nx=True, px=3000) and redis.pttl(key) == 3000


# --------------------------------------------------------------------------- #
# Through the routes
# --------------------------------------------------------------------------- #


def install_fakes(monkeypatch, redis: FakeRedis, keycloak: FakeKeycloak):
    monkeypatch.setattr(session_tokens, "default_store", lambda: store_for(redis))
    monkeypatch.setattr(session_tokens, "keycloak_client_factory", keycloak.factory)
    monkeypatch.setattr(home_api, "utc_now", lambda: NOW)


def state_client(monkeypatch, suite: FakeSuite, session: Dict[str, Any]) -> TestClient:
    """The real request binding (test_home_route), with every app entitled."""

    client, _, _ = real_binding_client(monkeypatch, suite, session=session)

    async def get_my_apps(request, user_tier):
        return load("oc_apps")

    sys.modules["my_apps_api"].get_my_apps = get_my_apps
    return client


def test_the_state_route_forwards_the_refreshed_token(monkeypatch, caplog):
    caplog.set_level(logging.DEBUG)
    monkeypatch.setenv("HOME_STATE_ENABLED", "true")
    redis, keycloak = FakeRedis(), FakeKeycloak(kc_ok())
    session = stored_session()
    redis.put_session(session)
    install_fakes(monkeypatch, redis, keycloak)
    suite = FakeSuite(suite_routes())
    client = state_client(monkeypatch, suite, session)

    response = client.get("/api/v1/home/state", headers={"Cookie": f"session_token={SESSION_ID}"})
    assert response.status_code == 200, response.text
    assert {r.url.host for r in suite.calls} == {
        "api.projectops.example.com", "meetings.example.com", "mail-ops.example.com", "ledger-api.example.com",
        "api.customers.example.com", "research.example.com",
    }  # every app was called, each with the refreshed token
    assert all(r.headers["authorization"] == f"Bearer {NEW_ACCESS}" for r in suite.calls)
    assert len(keycloak.requests) == 1 and redis.session()["access_token"] == NEW_ACCESS
    for value in NEVER_LOGGED:
        assert value not in response.text
    assert_nothing_secret_logged(caplog)


def test_the_state_route_says_sign_in_again_when_the_refresh_fails(monkeypatch, caplog):
    caplog.set_level(logging.DEBUG)
    monkeypatch.setenv("HOME_STATE_ENABLED", "true")
    redis = FakeRedis()
    keycloak = FakeKeycloak(httpx.Response(400, json={"error": "invalid_grant", "error_description": OLD_REFRESH}))
    session = stored_session()
    redis.put_session(session)
    install_fakes(monkeypatch, redis, keycloak)
    suite = FakeSuite(suite_routes())
    client = state_client(monkeypatch, suite, session)

    response = client.get("/api/v1/home/state", headers={"Cookie": f"session_token={SESSION_ID}"})
    assert response.status_code == 200, response.text
    body = response.json()
    for module_id in ("needs_you", "today", "recent_meetings", "watched_topics"):
        module = module_by_id(body, module_id)
        assert module["status"] == "unavailable" and module["reason"] == "reauth", module_id
    assert suite.calls == []  # no app is called with a token that is about to lapse
    assert redis.session() == session
    assert_nothing_secret_logged(caplog)


def test_the_action_route_forwards_the_refreshed_token(monkeypatch):
    from test_home_actions import PO_STATUS, PO_TASK, OpsCenterConn, ReceiptsDB, action_routes, post

    monkeypatch.setenv("HOME_ACTIONS_ENABLED", "true")
    redis, keycloak = FakeRedis(), FakeKeycloak(kc_ok())
    session = stored_session()
    redis.put_session(session)
    install_fakes(monkeypatch, redis, keycloak)

    db = ReceiptsDB()
    conn = OpsCenterConn(db)
    my_apps = ModuleType("my_apps_api")
    my_apps._session_data_from_request = (
        lambda request: dict(session) if request.cookies.get("session_token") == SESSION_ID else None
    )
    my_apps._session_subject = lambda data: (data.get("user") or {}).get("sub")

    async def get_user_org_from_session(request):
        request.state.current_org_name = "Rivergreen Coffee Co."
        return ORG_ID

    async def get_db_connection():
        return conn

    my_apps.get_user_org_from_session = get_user_org_from_session
    my_apps.get_db_connection = get_db_connection
    monkeypatch.setitem(sys.modules, "my_apps_api", my_apps)

    suite = FakeSuite(action_routes())
    app = FastAPI()
    app.include_router(home_api.router)

    async def providers_with_fake_http(ctx: HomeContext = Depends(home_api.get_home_context)):
        providers = await home_api.get_action_providers(ctx)
        providers.client_factory = suite.factory
        return providers

    app.dependency_overrides[home_api.get_action_providers] = providers_with_fake_http
    client = TestClient(app, cookies={"session_token": SESSION_ID})
    response = post(client, "project-ops", f"po:task:{PO_TASK}", "done")
    assert response.status_code == 200, response.text
    assert response.json()["outcome"] == "done"
    write = next(r for r in suite.calls if r.url.path == PO_STATUS)
    assert write.headers["authorization"] == f"Bearer {NEW_ACCESS}"
    assert all(r.headers["authorization"] == f"Bearer {NEW_ACCESS}" for r in suite.calls)
    assert len(keycloak.requests) == 1
