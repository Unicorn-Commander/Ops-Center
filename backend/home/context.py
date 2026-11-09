"""Inputs to one home-state build: who is asking, for which org, and the
in-process sources Ops-Center already owns.

``HomeContext`` carries the person's access token. It is excluded from the
dataclass ``repr`` so a stray log line or traceback never prints it.
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone, tzinfo
from typing import Any, Awaitable, Callable, Dict, List, Mapping, Optional

import httpx

# Org roles that see the money and usage modules (DESIGN section b: "Org manager
# (owner or org admin)"). billing_admin and member do not.
MANAGER_ROLES = frozenset({"owner", "admin"})


@dataclass
class HomeContext:
    person_id: str
    display_name: str
    org_id: str
    org_name: Optional[str]
    org_role: Optional[str]
    ring: str
    tz: tzinfo
    tz_name: str
    now: datetime
    ops_center_web: str
    email: Optional[str] = None
    access_token: Optional[str] = field(default=None, repr=False)

    @property
    def is_manager(self) -> bool:
        return (self.org_role or "").strip().lower() in MANAGER_ROLES

    @property
    def public_role(self) -> Optional[str]:
        """The org role in the document's vocabulary (section g uses org_admin)."""

        role = (self.org_role or "").strip().lower()
        if not role:
            return None
        return "org_admin" if role == "admin" else role


AppsProvider = Callable[[], Awaitable[List[Dict[str, Any]]]]
CursorProvider = Callable[[], Awaitable[Optional[str]]]
UsageProvider = Callable[[int], Awaitable[Dict[str, Any]]]
PoolProvider = Callable[[], Awaitable[Optional[Dict[str, Any]]]]
WorkspaceRowsProvider = Callable[[], Awaitable[Mapping[str, str]]]
ClientFactory = Callable[[float], httpx.AsyncClient]


def default_client_factory(timeout: float) -> httpx.AsyncClient:
    """One short-lived client per build. Redirects are never followed: an API
    that redirects is sending us to a sign-in page, which is an error here."""

    return httpx.AsyncClient(
        timeout=httpx.Timeout(timeout),
        follow_redirects=False,
        headers={"User-Agent": "ops-center-home/1"},
    )


@dataclass
class HomeProviders:
    """In-process sources (entitled app cards, the visit cursor, org usage, the
    workspace mapping rows) and the HTTP client factory for the app calls."""

    apps: AppsProvider
    cursor: CursorProvider
    usage: UsageProvider
    pool: PoolProvider
    workspace_rows: WorkspaceRowsProvider
    client_factory: ClientFactory = default_client_factory


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def token_expired(token: Optional[str], now: datetime, skew_seconds: int = 10) -> bool:
    """True when the token is missing or its ``exp`` claim has passed.

    The payload is decoded without verifying the signature: this only decides
    whether calling the apps is worth it. Each app verifies the token itself.
    An opaque token (not a JWT) is treated as not expired.
    """

    if not token:
        return True
    parts = token.split(".")
    if len(parts) != 3:
        return False
    payload = parts[1] + "=" * (-len(parts[1]) % 4)
    try:
        claims = json.loads(base64.urlsafe_b64decode(payload.encode("ascii")))
    except (ValueError, UnicodeError):
        return False
    exp = claims.get("exp") if isinstance(claims, dict) else None
    if not isinstance(exp, (int, float)):
        return False
    return exp <= now.timestamp() + skew_seconds
