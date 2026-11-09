"""Settings for the home aggregator: the flag, timeouts, the ring and app hosts.

Every value is read from the environment by NAME when it is needed (never
captured at import), so an operator can change one setting per ring and the
tests can set them per case.

App hosts. Each app has two settings:

* ``HOME_<APP>_API_URL``: where Ops-Center calls the app, server to server.
  It may be an internal address because it is never written into a response.
  Default: the scheme and host of that app's MCP door in the ring's committed
  index, ``backend/config/mcps-index.json`` (internal ring) or
  ``backend/config/mcps-index.unicorncommander.json`` (customer ring), the same
  files ``/.well-known/mcps.json`` serves (``colonel/a2a_server.py:298-308``).
  Accounting-Ops and Center Deep Research have no default: Accounting-Ops'
  public host sends ``/api/*`` to its Next.js tier, which only accepts a
  browser session (Accounting-Ops ``docker-compose.yml:147-158``), and Center
  Deep Research is not in either index.
* ``HOME_<APP>_WEB_URL``: the public host of the app's screens, used for every
  ``source`` and item link. Default: the entitled app card's ``launch_url``
  (the catalog's ring-specific source of truth, ``my_apps_api.py:50-55``), then
  the index entry. A web URL is only ever used after it passes the public,
  on-ring check in ``home.safety``.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlparse

from .safety import public_origin

CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"
INTERNAL_INDEX_PATH = CONFIG_DIR / "mcps-index.json"
CUSTOMER_INDEX_PATH = CONFIG_DIR / "mcps-index.unicorncommander.json"

RING_CUSTOMER = "customer"
RING_INTERNAL = "internal"
RINGS = (RING_CUSTOMER, RING_INTERNAL)
# The public parent domain of each ring. The customer suffix is the one
# colonel/a2a_server.py:68 already uses to pick the customer index.
RING_SUFFIX = {
    RING_CUSTOMER: "unicorncommander.ai",
    RING_INTERNAL: "magicunicorn.dev",
}

_TRUE = {"1", "true", "yes", "on"}

DEFAULT_APP_TIMEOUT_SECONDS = 2.5
DEFAULT_TOTAL_BUDGET_SECONDS = 4.0


def _env(name: str) -> str:
    return (os.getenv(name) or "").strip()


def home_state_enabled() -> bool:
    """``HOME_STATE_ENABLED`` (default false). Off means the route answers 404."""

    return _env("HOME_STATE_ENABLED").lower() in _TRUE


def _float_env(name: str, default: float, low: float, high: float) -> float:
    raw = _env(name)
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return min(max(value, low), high)


def app_timeout_seconds() -> float:
    """Per-app time limit (``HOME_APP_TIMEOUT_SECONDS``, default 2.5 s)."""

    return _float_env("HOME_APP_TIMEOUT_SECONDS", DEFAULT_APP_TIMEOUT_SECONDS, 0.05, 15.0)


def total_budget_seconds() -> float:
    """Whole-document time budget (``HOME_TOTAL_BUDGET_SECONDS``, default 4 s)."""

    return _float_env("HOME_TOTAL_BUDGET_SECONDS", DEFAULT_TOTAL_BUDGET_SECONDS, 0.1, 30.0)


def default_timezone() -> str:
    """Zone used for "today" when the page does not send one (default UTC)."""

    return _env("HOME_DEFAULT_TIMEZONE") or "UTC"


def ring_for_host(host: str) -> str:
    """Same rule as ``/.well-known/mcps.json`` (``colonel/a2a_server.py:306``)."""

    host = (host or "").split(":")[0].strip().lower().rstrip(".")
    suffix = RING_SUFFIX[RING_CUSTOMER]
    if host == suffix or host.endswith("." + suffix):
        return RING_CUSTOMER
    return RING_INTERNAL


def resolve_ring(request_host: str) -> str:
    """``HOME_RING`` when set to a known ring, otherwise derived from the host."""

    explicit = _env("HOME_RING").lower()
    if explicit in RINGS:
        return explicit
    return ring_for_host(request_host)


@dataclass(frozen=True)
class AppSpec:
    key: str
    label: str
    env_prefix: str
    # Entry name in the ring's MCP index, or None when the app is not listed.
    index_name: Optional[str]
    # my-apps catalog slugs that entitle the app. Empty means the app has no
    # catalog row on Ops-Center main, so it is not entitlement-gated here.
    catalog_slugs: Tuple[str, ...]
    # Whether the public host in the index also serves the REST routes the
    # adapter calls with a Bearer token.
    api_from_index: bool


APPS: Dict[str, AppSpec] = {
    "project-ops": AppSpec(
        "project-ops", "Project-Ops", "HOME_PROJECT_OPS", "project-ops", ("project-ops",), True
    ),
    "meeting-ops": AppSpec(
        "meeting-ops", "Meeting-Ops", "HOME_MEETING_OPS", "meeting-ops", ("meeting-ops",), True
    ),
    "email-ops": AppSpec(
        "email-ops", "Email-Ops", "HOME_EMAIL_OPS", "email-ops", ("email-ops",), True
    ),
    "accounting-ops": AppSpec(
        "accounting-ops",
        "Accounting-Ops",
        "HOME_ACCOUNTING_OPS",
        "accounting-ops",
        ("accounting-ops",),
        False,
    ),
    "customer-ops": AppSpec(
        "customer-ops", "Customer-Ops", "HOME_CUSTOMER_OPS", "customer-ops", ("customer-ops",), True
    ),
    "center-deep": AppSpec(
        "center-deep", "Center Deep Research", "HOME_CENTER_DEEP", None, (), False
    ),
}


@lru_cache(maxsize=4)
def _load_index(path: str) -> Dict[str, Any]:
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def index_entry(ring: str, name: Optional[str]) -> Optional[Dict[str, Any]]:
    """The ring's MCP index entry for ``name``, or None."""

    if not name:
        return None
    path = CUSTOMER_INDEX_PATH if ring == RING_CUSTOMER else INTERNAL_INDEX_PATH
    for entry in _load_index(str(path)).get("mcps", []) or []:
        if isinstance(entry, dict) and entry.get("name") == name:
            return entry
    return None


def _server_origin(value: str) -> Optional[str]:
    """Scheme, host and optional path prefix of a server-side base URL."""

    parsed = urlparse(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return None
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        return None
    path = parsed.path.rstrip("/")
    return f"{parsed.scheme}://{parsed.netloc}{path}"


def api_base_url(app: str, ring: str) -> Optional[str]:
    """Where Ops-Center calls ``app`` server to server, or None when unset."""

    spec = APPS[app]
    explicit = _env(f"{spec.env_prefix}_API_URL")
    if explicit:
        return _server_origin(explicit)
    if not spec.api_from_index:
        return None
    entry = index_entry(ring, spec.index_name)
    endpoint = (entry or {}).get("mcp_endpoint")
    if not isinstance(endpoint, str):
        return None
    parsed = urlparse(endpoint)
    if parsed.scheme != "https" or not parsed.hostname:
        return None
    return f"https://{parsed.netloc}"


def _screen_host_from_api(url: str) -> str:
    """The index lists API doors. Where an app serves its API on an ``api.``
    host, its screens live on the same name without that label (Project-Ops
    ``FRONTEND_URL`` default ``projectops.unicorncommander.ai``,
    ``backend/src/auth/auth.controller.ts:84-87``; Customer-Ops
    ``deploy/docker-compose.prod.yml:206,266``)."""

    parsed = urlparse(url)
    host = parsed.hostname or ""
    if host.startswith("api.") and host.count(".") >= 2:
        return f"{parsed.scheme}://{host[4:]}"
    return url


def web_base_url(app: str, ring: str, catalog_launch_url: Optional[str] = None) -> Optional[str]:
    """Public origin of ``app``'s screens on ``ring``, or None when none is safe.

    Order: ``HOME_<APP>_WEB_URL``, the entitled card's ``launch_url``, the
    index ``manifest_url``, then the index MCP door (without an ``api.`` label).
    """

    spec = APPS[app]
    candidates = [_env(f"{spec.env_prefix}_WEB_URL"), catalog_launch_url or ""]
    entry = index_entry(ring, spec.index_name) or {}
    if isinstance(entry.get("manifest_url"), str):
        candidates.append(entry["manifest_url"])
    if isinstance(entry.get("mcp_endpoint"), str):
        candidates.append(_screen_host_from_api(entry["mcp_endpoint"]))
    for candidate in candidates:
        origin = public_origin(candidate, ring) if candidate else None
        if origin:
            return origin
    return None


def ops_center_web_base(ring: str, request_host: str) -> str:
    """Public origin of Ops-Center itself, for links to its own screens.

    ``HOME_OPS_CENTER_WEB_URL`` wins; otherwise the host the person's browser
    used, when it is a public on-ring host; otherwise the ring's parent domain.
    """

    host = (request_host or "").strip()
    for candidate in (_env("HOME_OPS_CENTER_WEB_URL"), f"https://{host}" if host else ""):
        origin = public_origin(candidate, ring) if candidate else None
        if origin:
            return origin
    return f"https://{RING_SUFFIX[ring]}"
