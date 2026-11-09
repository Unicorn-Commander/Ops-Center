"""The fields both sign-in paths keep so the home can refresh the person's
access token from the Ops-Center session.

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

Nothing reads them yet: the home's refresh comes in the next change.
"""

from __future__ import annotations

import base64
import json
import math
import time
from typing import Any, Dict, Mapping, Optional

LOGIN_DIRECT = "direct_login"  # POST /auth/direct-login, the password grant
LOGIN_SSO = "oauth_callback"  # GET /auth/callback, the authorization code grant


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
