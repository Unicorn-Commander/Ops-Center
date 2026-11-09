"""Both sign-in paths keep the refresh token and expiries (``home.session_tokens``).

server.py is never imported: its two session-writing spots are read with
``ast`` and the dict each one builds is evaluated with fictional inputs. Every
token is an unsigned, token-shaped string with fictional claims; Rivergreen
Coffee Co. and its people are fictional.
"""

from __future__ import annotations

import ast
import base64
import json
from types import SimpleNamespace
from typing import Any, Dict, Tuple

import pytest

from home import session_tokens
from homekit import BACKEND, NOW, ORG_ID, PERSON_SUB

SERVER = BACKEND / "server.py"
NOW_TS = NOW.timestamp()


def jwt(kind: str, seconds_left: float, n: int = 1) -> str:
    """Token-shaped, unsigned, fictional: never a credential."""

    def part(data: Dict[str, Any]) -> str:
        return base64.urlsafe_b64encode(json.dumps(data).encode()).decode().rstrip("=")

    claims = {"sub": PERSON_SUB, "exp": int(NOW_TS + seconds_left), "typ": kind, "jti": f"rivergreen-{kind}-{n}"}
    return ".".join([part({"alg": "none"}), part(claims), f"unsigned-{kind}-{n}"])


OLD_ACCESS = jwt("access", 30)
OLD_REFRESH = jwt("refresh", 1500)


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
