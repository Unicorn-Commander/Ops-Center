"""Keep the person's access token usable for the home: refresh it from the
Ops-Center session before it is forwarded to the apps.

At sign-in Ops-Center keeps the Keycloak access token in the server-side
session (Redis, ``redis_session.py``, two hours). The token itself lives about
15 minutes. Both sign-in paths in ``server.py`` (``direct_login`` and
``oauth_callback``) therefore also keep, through ``login_token_fields``:

* ``refresh_token``, from the token response;
* ``access_token_expires_at`` (epoch seconds), from ``expires_in``, or else the
  access token's ``exp`` claim;
* ``refresh_token_expires_at``, from ``refresh_expires_in``, or else the
  refresh token's ``exp`` claim (Keycloak sends 0 for a token without one);
* ``login_method``, the path that signed the person in, so a refresh goes to
  the Keycloak URL that path uses.

``usable_access_token`` returns the stored token while it has more than 60 s
left. Otherwise it refreshes it at Keycloak's token endpoint
(``grant_type=refresh_token``) with the client id, client secret, realm and
Keycloak URL of the sign-in path (``token_endpoint``), writes the new tokens and
expiries back into the same Redis session without changing that session's own
expiry, and returns the new token. Any failure returns None, which the home
already reports as "Sign in again".

One refresh at a time per session, across workers: a Redis lock
(``SET NX PX``, a little longer than the refresh call may take, under a key
derived from a hash of the session id). The holder re-reads the session under
the lock, refreshes, writes, then deletes the lock only if it is still its own.
A request that finds the lock taken never refreshes: it waits, within the same
time limit, for the holder's token to appear in the session. Two parallel
requests therefore never both spend one refresh token, which matters because
Keycloak may rotate it.

Nothing here logs a token, the client secret, a session id or a response body.
A refused refresh logs the HTTP status and, when it is one of the standard OAuth
error codes, that code.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import math
import os
import secrets
import time
from typing import Any, Dict, Mapping, Optional, Type

from .context import ClientFactory, default_client_factory

logger = logging.getLogger(__name__)

# Mirrors of server.py's own sign-in settings (the home never imports server.py).
OAUTH_CLIENT_ID = "ops-center"  # server.py:359, hard-coded there as well
CLIENT_SECRET_ENV = "OPS_CENTER_OAUTH_CLIENT_SECRET"  # server.py:360
LOGIN_DIRECT = "direct_login"  # POST /auth/direct-login, the password grant
LOGIN_SSO = "oauth_callback"  # GET /auth/callback, the authorization code grant

REFRESH_MARGIN_SECONDS = 60
LOCK_PREFIX = "home:token-refresh:"
LOCK_EXTRA_SECONDS = 2.0
POLL_SECONDS = 0.05
WRITE_ATTEMPTS = 3
OAUTH_ERRORS = frozenset(
    {
        "invalid_request",
        "invalid_client",
        "invalid_grant",
        "unauthorized_client",
        "unsupported_grant_type",
        "invalid_scope",
    }
)

# The Keycloak call is an ordinary home call: no redirects, its own short client.
keycloak_client_factory: ClientFactory = default_client_factory


# --------------------------------------------------------------------------- #
# Expiries
# --------------------------------------------------------------------------- #


def _positive_number(value: Any) -> Optional[float]:
    if isinstance(value, str) and value.strip().isdigit():
        value = int(value.strip())
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(value) or value <= 0:
        return None
    return float(value)


def _jwt_exp(token: Any) -> Optional[float]:
    """The ``exp`` claim, read without verifying the signature: it only decides
    when to refresh. Keycloak and every app still verify the token itself."""

    if not isinstance(token, str):
        return None
    parts = token.split(".")
    if len(parts) != 3:
        return None
    payload = parts[1] + "=" * (-len(parts[1]) % 4)
    try:
        claims = json.loads(base64.urlsafe_b64decode(payload.encode("ascii")))
    except (ValueError, UnicodeError):
        return None
    return _positive_number(claims.get("exp")) if isinstance(claims, dict) else None


def _expiry(now: float, lifetime: Any, token: Any) -> Optional[float]:
    seconds = _positive_number(lifetime)
    if seconds is not None:
        return now + seconds
    return _jwt_exp(token)


def access_expires_at(session: Mapping[str, Any]) -> Optional[float]:
    stored = _positive_number(session.get("access_token_expires_at"))
    return stored if stored is not None else _jwt_exp(session.get("access_token"))


def needs_refresh(session: Mapping[str, Any], now: float) -> bool:
    """True when the stored access token has ``REFRESH_MARGIN_SECONDS`` or less
    left. A token whose expiry cannot be told (no stored expiry, not a JWT) is
    used as it is, as before."""

    expires_at = access_expires_at(session)
    return expires_at is not None and expires_at - now <= REFRESH_MARGIN_SECONDS


def refresh_expired(session: Mapping[str, Any], now: float) -> bool:
    stored = _positive_number(session.get("refresh_token_expires_at"))
    expires_at = stored if stored is not None else _jwt_exp(session.get("refresh_token"))
    return expires_at is not None and expires_at <= now


def login_token_fields(tokens: Any, login_method: str, now: Optional[float] = None) -> Dict[str, Any]:
    """What both sign-in paths add to the new session, from Keycloak's token
    response. Never raises: a response this cannot read stores no refresh
    token, and the home then asks for a new sign-in when the access token runs
    out, as it did before."""

    fields: Dict[str, Any] = {
        "refresh_token": None,
        "access_token_expires_at": None,
        "refresh_token_expires_at": None,
        "login_method": login_method,
    }
    try:
        if not isinstance(tokens, Mapping):
            return fields
        stamp = time.time() if now is None else now
        fields["access_token_expires_at"] = _expiry(stamp, tokens.get("expires_in"), tokens.get("access_token"))
        refresh = tokens.get("refresh_token")
        if isinstance(refresh, str) and refresh:
            fields["refresh_token"] = refresh
            fields["refresh_token_expires_at"] = _expiry(stamp, tokens.get("refresh_expires_in"), refresh)
    except Exception:  # noqa: BLE001 - sign-in must never fail because of the home
        fields.update(refresh_token=None, access_token_expires_at=None, refresh_token_expires_at=None)
    return fields


def _refreshed_fields(tokens: Mapping[str, Any], now: float) -> Dict[str, Any]:
    access = tokens["access_token"]
    fields: Dict[str, Any] = {
        "access_token": access,
        "access_token_expires_at": _expiry(now, tokens.get("expires_in"), access),
    }
    refresh = tokens.get("refresh_token")
    if isinstance(refresh, str) and refresh:  # otherwise the old one stays valid and stays put
        fields["refresh_token"] = refresh
        fields["refresh_token_expires_at"] = _expiry(now, tokens.get("refresh_expires_in"), refresh)
    return fields


# --------------------------------------------------------------------------- #
# Where a refresh goes
# --------------------------------------------------------------------------- #


def token_endpoint(login_method: Any, request_url: str = "") -> Optional[str]:
    """Keycloak's token endpoint for the path that signed the person in, built
    from the same settings and defaults that path uses, so the refresh token
    goes back to the URL that issued it. None for a session from neither path.

    * ``oauth_callback`` (server.py:6298-6303): ``KEYCLOAK_URL``, the internal
      URL, and ``KEYCLOAK_REALM`` (default uchub).
    * ``direct_login`` (server.py:6030-6040): the yoda host when the request is
      on it, else ``KEYCLOAK_EXTERNAL_URL`` or ``https://auth.<EXTERNAL_HOST>``,
      and ``KEYCLOAK_REALM`` (default master).
    """

    if login_method == LOGIN_SSO:
        base = os.getenv("KEYCLOAK_URL", "http://centerdeep-keycloak:8080")
        realm = os.getenv("KEYCLOAK_REALM", "uchub")
    elif login_method == LOGIN_DIRECT:
        if "yoda.unicorncommander.ai" in (request_url or ""):
            base = "https://auth.yoda.unicorncommander.ai"
        else:
            external_host = os.environ.get("EXTERNAL_HOST", "192.168.1.135")
            base = os.getenv("KEYCLOAK_EXTERNAL_URL", f"https://auth.{external_host}")
        realm = os.getenv("KEYCLOAK_REALM", "master")
    else:
        return None
    if not base.startswith(("https://", "http://")) or not realm:
        return None
    return f"{base}/realms/{realm}/protocol/openid-connect/token"


# --------------------------------------------------------------------------- #
# The session in Redis
# --------------------------------------------------------------------------- #


class _NoWatchError(Exception):
    """Stands in for redis-py's WatchError where redis-py is not installed."""


def _redis_watch_error() -> Type[BaseException]:
    try:
        from redis.exceptions import WatchError
    except Exception:  # noqa: BLE001
        return _NoWatchError
    return WatchError


class RedisSessionStore:
    """The Ops-Center session exactly as ``redis_session.RedisSessionManager``
    keeps it (``<prefix><session id>`` holding JSON, with a TTL), plus the
    refresh lock. Uses the manager's own client: the manager has no lock and no
    write that keeps the TTL."""

    def __init__(self, client: Any, key_prefix: str, watch_error: Optional[Type[BaseException]] = None):
        self.client = client
        self.key_prefix = key_prefix
        self.watch_error = watch_error or _redis_watch_error()

    def _key(self, session_id: str) -> str:
        return f"{self.key_prefix}{session_id}"

    @staticmethod
    def lock_key(session_id: str) -> str:
        # Outside the session prefix (never counted or listed as a session),
        # and the session id itself never appears in a key name.
        return LOCK_PREFIX + hashlib.sha256(session_id.encode("utf-8")).hexdigest()

    def read(self, session_id: str) -> Optional[Dict[str, Any]]:
        raw = self.client.get(self._key(session_id))
        if raw is None:
            return None
        data = json.loads(raw)
        return data if isinstance(data, dict) else None

    def acquire(self, session_id: str, owner: str, ttl_ms: int) -> bool:
        return bool(self.client.set(self.lock_key(session_id), owner, nx=True, px=ttl_ms))

    def locked(self, session_id: str) -> bool:
        return self.client.get(self.lock_key(session_id)) is not None

    def release(self, session_id: str, owner: str) -> None:
        """Delete the lock only while it is still ``owner``'s."""

        key = self.lock_key(session_id)
        with self.client.pipeline() as pipe:
            try:
                pipe.watch(key)
                if pipe.get(key) != owner:
                    return
                pipe.multi()
                pipe.delete(key)
                pipe.execute()
            except self.watch_error:
                return  # it changed hands meanwhile: not ours to delete

    def merge(self, session_id: str, fields: Mapping[str, Any]) -> bool:
        """Write ``fields`` into the session and keep its remaining TTL. A
        write that lands between the read and the write (an org switch) makes
        this read again rather than undo it. False when the session is gone,
        for example signed out meanwhile: it is never brought back."""

        key = self._key(session_id)
        for _ in range(WRITE_ATTEMPTS):
            with self.client.pipeline() as pipe:
                try:
                    pipe.watch(key)
                    raw = pipe.get(key)
                    ttl_ms = pipe.pttl(key)
                    if raw is None or ttl_ms == -2 or ttl_ms == 0:
                        return False
                    data = json.loads(raw)
                    if not isinstance(data, dict):
                        return False
                    data.update(fields)
                    pipe.multi()
                    if ttl_ms > 0:
                        pipe.set(key, json.dumps(data), px=ttl_ms)
                    else:  # -1: the session has no expiry, and keeps none
                        pipe.set(key, json.dumps(data))
                    pipe.execute()
                    return True
                except self.watch_error:
                    continue
        return False


def default_store() -> Optional[RedisSessionStore]:
    """The store behind Ops-Center's own session manager, or None."""

    try:
        from redis_session import redis_session_manager
    except Exception:  # noqa: BLE001
        return None
    client = getattr(redis_session_manager, "_client", None)
    prefix = getattr(redis_session_manager, "key_prefix", None)
    if client is None or not isinstance(prefix, str):
        return None
    return RedisSessionStore(client, prefix)


# --------------------------------------------------------------------------- #
# The refresh
# --------------------------------------------------------------------------- #


def _oauth_error(response: Any) -> str:
    try:
        body = response.json()
    except Exception:  # noqa: BLE001
        return ""
    code = body.get("error") if isinstance(body, dict) else None
    return f", {code}" if isinstance(code, str) and code in OAUTH_ERRORS else ""


async def _refresh_grant(
    endpoint: str, refresh_token: str, secret: str, timeout: float, client_factory: ClientFactory
) -> Optional[Dict[str, Any]]:
    form = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": OAUTH_CLIENT_ID,
        "client_secret": secret,
    }
    client = client_factory(timeout)
    try:
        response = await asyncio.wait_for(
            client.post(endpoint, data=form, headers={"Accept": "application/json"}), timeout
        )
    except asyncio.TimeoutError:
        logger.warning("home session: token refresh timed out after %.1f s", timeout)
        return None
    except Exception as exc:  # noqa: BLE001
        logger.warning("home session: token refresh could not reach Keycloak (%s)", type(exc).__name__)
        return None
    finally:
        await client.aclose()
    if response.status_code != 200:
        logger.warning(
            "home session: Keycloak refused the token refresh (HTTP %s%s)",
            response.status_code,
            _oauth_error(response),
        )
        return None
    try:
        body = response.json()
    except ValueError:
        logger.warning("home session: Keycloak's refresh answer was not JSON")
        return None
    access = body.get("access_token") if isinstance(body, dict) else None
    if not isinstance(access, str) or not access:
        logger.warning("home session: Keycloak's refresh answer had no access token")
        return None
    return body


def _fresh_token(session: Optional[Mapping[str, Any]], now: float) -> Optional[str]:
    if not session:
        return None
    token = session.get("access_token")
    if isinstance(token, str) and token and not needs_refresh(session, now):
        return token
    return None


async def _wait_for_holder(store: RedisSessionStore, session_id: str, now: float, timeout: float) -> Optional[str]:
    """Another request holds the lock: wait for its token rather than spend the
    refresh token a second time."""

    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while True:
        held = store.locked(session_id)  # the lock first, so a read after the
        current = store.read(session_id)  # release sees the holder's write
        if current is None:
            return None
        token = _fresh_token(current, now)
        if token:
            return token
        if not held or loop.time() >= deadline:
            return None  # the holder failed, or is still at it: sign in again this time
        await asyncio.sleep(POLL_SECONDS)


async def _refresh_once(
    store: RedisSessionStore,
    session_id: str,
    endpoint: str,
    secret: str,
    now: float,
    timeout: float,
    client_factory: ClientFactory,
) -> Optional[str]:
    owner = secrets.token_hex(16)
    if not store.acquire(session_id, owner, int((timeout + LOCK_EXTRA_SECONDS) * 1000)):
        return await _wait_for_holder(store, session_id, now, timeout)
    try:
        current = store.read(session_id)
        if current is None:
            return None  # signed out meanwhile
        token = _fresh_token(current, now)
        if token:
            return token  # refreshed by another request a moment ago
        refresh_token = current.get("refresh_token")
        if not isinstance(refresh_token, str) or not refresh_token or refresh_expired(current, now):
            return None
        tokens = await _refresh_grant(endpoint, refresh_token, secret, timeout, client_factory)
        if tokens is None:
            return None
        fields = _refreshed_fields(tokens, now)
        if not store.merge(session_id, fields):
            logger.warning("home session: the refreshed token was not stored (the session is gone or busy)")
            return None
        logger.info("home session: access token refreshed")
        return fields["access_token"]
    finally:
        try:
            store.release(session_id, owner)
        except Exception as exc:  # noqa: BLE001 - the lock expires on its own
            logger.warning("home session: refresh lock release failed (%s)", type(exc).__name__)


async def usable_access_token(
    session_id: Optional[str],
    session: Mapping[str, Any],
    *,
    now: float,
    timeout: float,
    request_url: str = "",
    store: Optional[RedisSessionStore] = None,
    client_factory: Optional[ClientFactory] = None,
) -> Optional[str]:
    """An access token with more than 60 s left for this session, refreshed
    first if need be, or None (the home then says "Sign in again").

    ``session`` is the session as the request already read it, so a token that
    is still fresh costs no Redis call. ``timeout`` bounds the Keycloak call
    and any wait for a refresh another request is making.
    """

    token = session.get("access_token") if isinstance(session, Mapping) else None
    if not isinstance(token, str) or not token:
        return None
    if not needs_refresh(session, now):
        return token
    if not session_id or not session.get("refresh_token") or refresh_expired(session, now):
        return None
    endpoint = token_endpoint(session.get("login_method"), request_url)
    secret = os.environ.get(CLIENT_SECRET_ENV) or ""
    if not endpoint or not secret:
        return None
    try:
        store = store or default_store()
        if store is None:
            return None
        return await _refresh_once(
            store, session_id, endpoint, secret, now, timeout, client_factory or keycloak_client_factory
        )
    except Exception as exc:  # noqa: BLE001 - a refresh problem is "Sign in again", never a 500
        logger.warning("home session: token refresh failed (%s)", type(exc).__name__)
        return None
