"""
Inbound service keys come from OPS_CENTER_SERVICE_KEY_HASHES (sha256 only), never from source.

Covers: valid / invalid / unset keys, X-User-ID only for services allowed to act as a
user, the LLM API dependency (get_user_id), the credit middleware, A2A failing closed,
and the outbound Colonel key having no literal default. Every key here is synthetic,
generated per test run.
"""

import asyncio
import hashlib
import json
import os
import secrets
import subprocess
import sys

import pytest
from fastapi import HTTPException
from starlette.requests import Request

import service_keys
from service_keys import (
    ServiceKeyUserContextForbidden,
    canonical_service_name,
    configured_services,
    match_service_key,
    reset_service_key_cache,
    resolve_principal,
)

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _new_key(service: str) -> str:
    # Synthetic, random per run: never a real or leaked key.
    return f"sk-{service}-{secrets.token_urlsafe(24)}"


def _sha(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def _run(coro):
    return asyncio.run(coro)


def _request(headers=None, cookies=None) -> Request:
    raw = [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
    if cookies:
        raw.append((b"cookie", "; ".join(f"{k}={v}" for k, v in cookies.items()).encode()))
    scope = {"type": "http", "method": "POST", "path": "/api/v1/llm/chat/completions",
             "headers": raw, "query_string": b""}
    return Request(scope)


@pytest.fixture
def keys(monkeypatch):
    """Configure three services: majiks (may act as a user), colonel, and one without an org."""
    k = {"majiks": _new_key("majiks"), "colonel": _new_key("colonel"), "orgless": _new_key("orgless")}
    monkeypatch.setenv(service_keys.HASHES_ENV, json.dumps({name: _sha(v) for name, v in k.items()}))
    monkeypatch.setenv(service_keys.ACT_AS_USER_ENV, "majiks")
    reset_service_key_cache()
    yield k
    reset_service_key_cache()


# ---------------------------------------------------------------- service_keys module

def test_valid_key_matches_its_service(keys):
    m = match_service_key(keys["majiks"])
    assert m is not None and m.service == "majiks-service"
    assert m.act_as_user is True
    assert m.org_id == service_keys.SERVICE_ORG_IDS["majiks-service"]
    c = match_service_key(keys["colonel"])
    assert c.service == "colonel-service" and c.act_as_user is False


def test_invalid_key_is_rejected(keys):
    assert match_service_key(_new_key("majiks")) is None
    assert match_service_key(keys["majiks"] + "x") is None
    assert match_service_key("") is None
    assert match_service_key(None) is None


def test_unset_env_disables_every_service(monkeypatch):
    monkeypatch.delenv(service_keys.HASHES_ENV, raising=False)
    monkeypatch.delenv(service_keys.ACT_AS_USER_ENV, raising=False)
    reset_service_key_cache()
    try:
        assert configured_services() == frozenset()
        assert match_service_key(_new_key("majiks")) is None
    finally:
        reset_service_key_cache()


def test_malformed_config_disables_service_keys(monkeypatch):
    key = _new_key("majiks")
    for raw in ("not json", json.dumps([_sha(key)]), json.dumps({"majiks": key}),   # plaintext pasted, not a hash
                json.dumps({"majiks": "abc"}), json.dumps({"Bad Name!": _sha(key)})):
        monkeypatch.setenv(service_keys.HASHES_ENV, raw)
        reset_service_key_cache()
        assert match_service_key(key) is None, raw[:20]
    reset_service_key_cache()


def test_one_bad_entry_does_not_disable_the_others(monkeypatch):
    good = _new_key("colonel")
    monkeypatch.setenv(service_keys.HASHES_ENV, json.dumps({"majiks": "zz", "colonel": _sha(good)}))
    reset_service_key_cache()
    try:
        assert configured_services() == frozenset({"colonel-service"})
        assert match_service_key(good).service == "colonel-service"
    finally:
        reset_service_key_cache()


def test_hash_is_case_insensitive_and_names_are_canonical(monkeypatch):
    key = _new_key("majiks")
    monkeypatch.setenv(service_keys.HASHES_ENV, json.dumps({"majiks-service": _sha(key).upper()}))
    monkeypatch.setenv(service_keys.ACT_AS_USER_ENV, '["majiks"]')
    reset_service_key_cache()
    try:
        m = match_service_key(key)
        assert m.service == "majiks-service" and m.act_as_user is True
        assert canonical_service_name("Majiks") == canonical_service_name("majiks-service") == "majiks-service"
    finally:
        reset_service_key_cache()


def test_act_as_user_needs_a_configured_hash(monkeypatch):
    key = _new_key("colonel")
    monkeypatch.setenv(service_keys.HASHES_ENV, json.dumps({"colonel": _sha(key)}))
    monkeypatch.setenv(service_keys.ACT_AS_USER_ENV, "majiks,brigade")   # neither is configured
    reset_service_key_cache()
    try:
        assert match_service_key(key).act_as_user is False
    finally:
        reset_service_key_cache()


def test_resolve_principal(keys):
    majiks = match_service_key(keys["majiks"])
    colonel = match_service_key(keys["colonel"])
    orgless = match_service_key(keys["orgless"])
    assert resolve_principal(majiks, "user-123") == ("user-123", False)
    assert resolve_principal(majiks, None) == (f"org_{service_keys.SERVICE_ORG_IDS['majiks-service']}", True)
    assert resolve_principal(colonel, "") == (f"org_{service_keys.SERVICE_ORG_IDS['colonel-service']}", True)
    with pytest.raises(ServiceKeyUserContextForbidden):
        resolve_principal(colonel, "user-123")
    assert resolve_principal(orgless, None) == (None, True)


# ---------------------------------------------------------------- LLM API dependency

@pytest.fixture
def litellm_api():
    try:
        import litellm_api as mod
    except Exception as exc:  # pragma: no cover - environment dependent
        pytest.skip(f"litellm_api is not importable here: {exc}")
    return mod


def test_get_user_id_service_key_bills_service_org(keys, litellm_api):
    uid = _run(litellm_api.get_user_id(_request(), authorization=f"Bearer {keys['colonel']}"))
    assert uid == f"org_{service_keys.SERVICE_ORG_IDS['colonel-service']}"


def test_get_user_id_x_user_id_only_for_allowed_service(keys, litellm_api):
    uid = _run(litellm_api.get_user_id(_request({"X-User-ID": "user-abc"}), authorization=f"Bearer {keys['majiks']}"))
    assert uid == "user-abc"
    with pytest.raises(HTTPException) as exc:
        _run(litellm_api.get_user_id(_request({"X-User-ID": "user-abc"}), authorization=f"Bearer {keys['colonel']}"))
    assert exc.value.status_code == 403


def test_get_user_id_rejects_unknown_and_unset_keys(keys, litellm_api, monkeypatch):
    with pytest.raises(HTTPException) as exc:
        _run(litellm_api.get_user_id(_request({"X-User-ID": "user-abc"}), authorization=f"Bearer {_new_key('majiks')}"))
    assert exc.value.status_code == 401
    monkeypatch.delenv(service_keys.HASHES_ENV)
    reset_service_key_cache()
    with pytest.raises(HTTPException) as exc:
        _run(litellm_api.get_user_id(_request(), authorization=f"Bearer {keys['colonel']}"))
    assert exc.value.status_code == 401


def test_get_user_id_service_without_org_is_a_server_error(keys, litellm_api):
    with pytest.raises(HTTPException) as exc:
        _run(litellm_api.get_user_id(_request(), authorization=f"Bearer {keys['orgless']}"))
    assert exc.value.status_code == 500


def test_get_user_id_never_logs_the_presented_key(keys, litellm_api, caplog):
    bad = _new_key("majiks")
    caplog.set_level("DEBUG")
    with pytest.raises(HTTPException):
        _run(litellm_api.get_user_id(_request(), authorization=f"Bearer {bad}"))
    _run(litellm_api.get_user_id(_request({"X-User-ID": "u1"}), authorization=f"Bearer {keys['majiks']}"))
    text = caplog.text
    for secret in (bad, keys["majiks"]):
        assert secret[:12] not in text and secret[-12:] not in text


# ---------------------------------------------------------------- credit middleware

@pytest.fixture
def middleware():
    try:
        from credit_deduction_middleware import CreditDeductionMiddleware
    except Exception as exc:  # pragma: no cover - environment dependent
        pytest.skip(f"credit_deduction_middleware is not importable here: {exc}")

    async def _app(scope, receive, send):  # pragma: no cover - never called
        return None

    return CreditDeductionMiddleware(_app)


def test_credit_middleware_service_key_paths(keys, middleware):
    org = _run(middleware._get_user_from_session(_request({"Authorization": f"Bearer {keys['colonel']}"})))
    assert org["user_id"] == f"org_{service_keys.SERVICE_ORG_IDS['colonel-service']}"
    assert org["is_service_account"] is True and org["subscription_tier"] == "internal"
    assert org["_app"] == "colonel-service"

    user = _run(middleware._get_user_from_session(
        _request({"Authorization": f"Bearer {keys['majiks']}", "X-User-ID": "user-xyz"})))
    assert user["user_id"] == "user-xyz" and user["_app"] == "majiks-service"
    assert "is_service_account" not in user

    # X-User-ID from a service that may not act as a user, or an unknown key: no billable identity.
    assert _run(middleware._get_user_from_session(
        _request({"Authorization": f"Bearer {keys['colonel']}", "X-User-ID": "user-xyz"}))) is None
    assert _run(middleware._get_user_from_session(
        _request({"Authorization": f"Bearer {_new_key('majiks')}", "X-User-ID": "user-xyz"}))) is None


# ---------------------------------------------------------------- A2A fails closed

@pytest.fixture
def a2a():
    try:
        from colonel import a2a_server
    except Exception as exc:  # pragma: no cover - environment dependent
        pytest.skip(f"colonel.a2a_server is not importable here: {exc}")
    return a2a_server


def test_a2a_fails_closed_without_a_secret(a2a, monkeypatch):
    monkeypatch.setattr(a2a, "A2A_SHARED_SECRET", "")
    monkeypatch.setattr(a2a, "BRIGADE_SERVICE_KEY", "")
    assert a2a._validate_a2a_auth(_request()) is False
    assert a2a._validate_a2a_auth(_request({"Authorization": "Bearer anything"})) is False
    assert a2a._validate_a2a_auth(_request({"X-Service-Key": "anything"})) is False


def test_a2a_accepts_only_the_configured_secret(a2a, monkeypatch):
    secret = secrets.token_urlsafe(32)
    monkeypatch.setattr(a2a, "A2A_SHARED_SECRET", secret)
    monkeypatch.setattr(a2a, "BRIGADE_SERVICE_KEY", "")
    assert a2a._validate_a2a_auth(_request({"Authorization": f"Bearer {secret}"})) is True
    assert a2a._validate_a2a_auth(_request({"X-Service-Key": secret})) is True
    assert a2a._validate_a2a_auth(_request({"Authorization": f"Bearer {secret}x"})) is False
    assert a2a._validate_a2a_auth(_request({"Authorization": "Bearer "})) is False
    assert a2a._validate_a2a_auth(_request()) is False
    # BRIGADE_SERVICE_KEY is the fallback secret when A2A_SHARED_SECRET is unset.
    monkeypatch.setattr(a2a, "A2A_SHARED_SECRET", "")
    monkeypatch.setattr(a2a, "BRIGADE_SERVICE_KEY", secret)
    assert a2a._validate_a2a_auth(_request({"X-Service-Key": secret})) is True


# ---------------------------------------------------------------- outbound Colonel key

def test_colonel_service_key_has_no_default(monkeypatch):
    try:
        from colonel import websocket_gateway
    except Exception as exc:  # pragma: no cover - environment dependent
        pytest.skip(f"colonel.websocket_gateway is not importable here: {exc}")
    monkeypatch.delenv("COLONEL_SERVICE_KEY", raising=False)
    assert websocket_gateway._colonel_service_key() == ""
    key = _new_key("colonel")
    monkeypatch.setenv("COLONEL_SERVICE_KEY", key)
    assert websocket_gateway._colonel_service_key() == key


# ---------------------------------------------------------------- DB credentials without source defaults

_IMPORT_PROBE = r"""
import asyncio, sys
sys.path.insert(0, sys.argv[1])
import keycloak_integration as ki
assert ki.KEYCLOAK_DB_PASSWORD == "", "no source default expected"
try:
    ki._require_keycloak_db_password()
    raise SystemExit("expected RuntimeError")
except RuntimeError:
    pass
try:
    asyncio.run(ki.get_all_users_from_db())
    raise SystemExit("expected RuntimeError from the DB fallback")
except RuntimeError:
    pass
import user_analytics as ua
assert ua.KEYCLOAK_DB_URL == "" and ua.keycloak_engine is None and ua.KeycloakSessionLocal is None
from fastapi import HTTPException
try:
    next(ua.get_keycloak_db())
    raise SystemExit("expected 503")
except HTTPException as e:
    assert e.status_code == 503
print("OK")
"""


def test_db_credentials_unset_disable_features_without_crashing():
    env = {k: v for k, v in os.environ.items()
           if k not in ("KEYCLOAK_DB_PASSWORD", "KEYCLOAK_DATABASE_URL")}
    try:
        import asyncpg  # noqa: F401
        import sqlalchemy  # noqa: F401
    except Exception as exc:  # pragma: no cover - environment dependent
        pytest.skip(f"DB client libraries not installed here: {exc}")
    r = subprocess.run([sys.executable, "-c", _IMPORT_PROBE, BACKEND_DIR], env=env,
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0 and r.stdout.strip().endswith("OK"), (r.stdout[-400:], r.stderr[-800:])


def test_db_credentials_from_env_are_used():
    env = dict(os.environ)
    env["KEYCLOAK_DB_PASSWORD"] = secrets.token_urlsafe(16)
    probe = ("import sys; sys.path.insert(0, sys.argv[1]); import keycloak_integration as ki; "
             "import os; assert ki._require_keycloak_db_password() == os.environ['KEYCLOAK_DB_PASSWORD']; print('OK')")
    try:
        import asyncpg  # noqa: F401
    except Exception as exc:  # pragma: no cover - environment dependent
        pytest.skip(f"asyncpg not installed here: {exc}")
    r = subprocess.run([sys.executable, "-c", probe, BACKEND_DIR], env=env, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0 and r.stdout.strip().endswith("OK"), r.stderr[-800:]
