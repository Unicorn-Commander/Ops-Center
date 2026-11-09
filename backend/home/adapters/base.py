"""Shared pieces for the per-app adapters.

An adapter makes the few GET calls its app needs with the person's own token
and returns an ``AppSnapshot``: one overall status for the app plus named
``Part`` results (one per route), each with its own status, so a failure in one
route never hides the others. Adapters never write, never follow redirects and
never put a response body or a token into a log line or an exception.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Dict, Iterable, List, Mapping, Optional
from urllib.parse import quote

import httpx

from ..context import HomeContext
from ..mapping import WorkspaceCandidate
from ..safety import join_url

logger = logging.getLogger("home.adapters")

OK = "ok"
EMPTY = "empty"
NOT_SET_UP = "not_set_up"
NOT_ENTITLED = "not_entitled"
UNAVAILABLE = "unavailable"
STATUSES = (OK, EMPTY, NOT_SET_UP, NOT_ENTITLED, UNAVAILABLE)

REAUTH = "reauth"
TIMEOUT = "timeout"
ERROR = "error"
REASONS = (REAUTH, TIMEOUT, ERROR)


class UpstreamError(Exception):
    """A call to an app failed. ``reason`` is one of REASONS; no body is kept."""

    def __init__(self, reason: str, status_code: Optional[int] = None):
        super().__init__(reason if status_code is None else f"{reason} ({status_code})")
        self.reason = reason
        self.status_code = status_code


class Reauth(UpstreamError):
    def __init__(self, status_code: Optional[int] = 401):
        super().__init__(REAUTH, status_code)


class Forbidden(UpstreamError):
    def __init__(self, status_code: int = 403):
        super().__init__(ERROR, status_code)


class NotFound(UpstreamError):
    def __init__(self, status_code: int = 404):
        super().__init__(ERROR, status_code)


class Rejected(UpstreamError):
    """400 or 422: the app refused the request shape (for example a workspace id
    that is not a UUID)."""

    def __init__(self, status_code: int):
        super().__init__(ERROR, status_code)


@dataclass
class Part:
    name: str
    status: str
    route: Optional[str] = None
    screen: Optional[str] = None
    data: Any = None
    reason: Optional[str] = None
    note: Optional[str] = None
    as_of: Optional[str] = None


@dataclass
class AppSnapshot:
    app: str
    label: str
    status: str
    as_of: str
    reason: Optional[str] = None
    workspace: Optional[str] = None
    workspace_origin: Optional[str] = None
    web_base: Optional[str] = None
    note: Optional[str] = None
    role: Optional[str] = None
    parts: Dict[str, Part] = field(default_factory=dict)

    def part(self, name: str) -> Part:
        """The named part, or a stand-in that carries the app's own status."""

        found = self.parts.get(name)
        if found is not None:
            return found
        return Part(
            name=name,
            status=self.status if self.status != OK else UNAVAILABLE,
            reason=self.reason if self.status != OK else ERROR,
            note=self.note,
            as_of=self.as_of,
        )


@dataclass
class AdapterEnv:
    ctx: HomeContext
    client: httpx.AsyncClient
    app: str
    label: str
    api_base: Optional[str]
    web_base: Optional[str]
    candidates: List[WorkspaceCandidate]
    timeout: float
    want_money: bool = False

    def screen(self, path: str) -> Optional[str]:
        return join_url(self.web_base, path)


def iso(value: Optional[datetime] = None) -> str:
    moment = value or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_iso(value: Any) -> Optional[datetime]:
    """Parse the ISO forms the apps emit (``Z``, offsets, milliseconds, date only)."""

    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=timezone.utc)
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    if len(text) == 10:
        text += "T00:00:00+00:00"
    # Python 3.10 accepts only 3- or 6-digit fractions; normalise others.
    if "." in text:
        head, _, rest = text.partition(".")
        digits = ""
        while rest and rest[0].isdigit():
            digits, rest = digits + rest[0], rest[1:]
        digits = (digits + "000000")[:6]
        text = f"{head}.{digits}{rest}"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def text(value: Any, origin: str) -> Optional[Dict[str, str]]:
    """A labelled text field (DESIGN section g provenance: system or third_party)."""

    if value is None:
        return None
    cleaned = " ".join(str(value).split())
    if not cleaned:
        return None
    if len(cleaned) > 280:
        cleaned = cleaned[:277].rstrip() + "..."
    return {"text": cleaned, "origin": origin}


def short(value: Any, limit: int = 160) -> Optional[str]:
    if value is None:
        return None
    cleaned = " ".join(str(value).split())
    if not cleaned:
        return None
    return cleaned if len(cleaned) <= limit else cleaned[: limit - 3].rstrip() + "..."


def path_segment(value: Any) -> str:
    return quote(str(value), safe="")


async def get_json(
    env: AdapterEnv,
    path: str,
    *,
    params: Optional[Mapping[str, Any]] = None,
    headers: Optional[Mapping[str, str]] = None,
) -> Any:
    """GET ``path`` on the app with the person's own Bearer token.

    401 raises ``Reauth``; 403, 404, 400 and 422 raise their own types so the
    adapter can decide; any other non-2xx, a redirect, a transport failure or a
    body that is not JSON raises ``UpstreamError``. Bodies are never kept.
    """

    if not env.api_base:
        raise UpstreamError(ERROR)
    url = env.api_base.rstrip("/") + path
    request_headers = {
        "Authorization": f"Bearer {env.ctx.access_token or ''}",
        "Accept": "application/json",
    }
    if headers:
        request_headers.update(headers)
    try:
        response = await env.client.get(
            url, params=dict(params or {}), headers=request_headers, timeout=env.timeout
        )
    except httpx.TimeoutException:
        logger.info("home state: %s %s timed out", env.app, path.split("?")[0])
        raise UpstreamError(TIMEOUT) from None
    except httpx.HTTPError as exc:
        logger.info("home state: %s %s failed (%s)", env.app, path.split("?")[0], type(exc).__name__)
        raise UpstreamError(ERROR) from None

    status = response.status_code
    if status == 401:
        raise Reauth()
    if status == 403:
        raise Forbidden()
    if status == 404:
        raise NotFound()
    if status in (400, 422):
        raise Rejected(status)
    if status < 200 or status >= 300:
        logger.info("home state: %s %s answered %s", env.app, path.split("?")[0], status)
        raise UpstreamError(ERROR, status)
    try:
        return response.json()
    except ValueError:
        raise UpstreamError(ERROR, status) from None


def snapshot(env: AdapterEnv, status: str, **kwargs: Any) -> AppSnapshot:
    return AppSnapshot(
        app=env.app,
        label=env.label,
        status=status,
        as_of=kwargs.pop("as_of", None) or iso(),
        web_base=env.web_base,
        **kwargs,
    )


def failed_snapshot(env: AdapterEnv, exc: BaseException) -> AppSnapshot:
    """The snapshot for an app whose calls failed as a whole."""

    if isinstance(exc, Reauth):
        return snapshot(env, UNAVAILABLE, reason=REAUTH, note="Sign in again to refresh.")
    if isinstance(exc, UpstreamError):
        return snapshot(env, UNAVAILABLE, reason=exc.reason)
    return snapshot(env, UNAVAILABLE, reason=ERROR)


def not_set_up_snapshot(env: AdapterEnv, note: str) -> AppSnapshot:
    return snapshot(env, NOT_SET_UP, note=note)


def link_note(label: str) -> str:
    return f"No {label} workspace is linked to this organization for you yet."


def part_from_error(name: str, exc: BaseException, route: Optional[str], screen: Optional[str]) -> Part:
    """A part whose one call failed. ``Reauth`` is re-raised by the callers."""

    if isinstance(exc, Forbidden):
        return Part(
            name, NOT_ENTITLED, route=route, screen=screen, as_of=iso(),
            note="Your role in this app does not include this view.",
        )
    reason = exc.reason if isinstance(exc, UpstreamError) else ERROR
    return Part(name, UNAVAILABLE, route=route, screen=screen, reason=reason, as_of=iso())


def raise_if_reauth(results: Iterable[Any]) -> None:
    for result in results:
        if isinstance(result, Reauth):
            raise result


def member_ids(rows: Iterable[Mapping[str, Any]], *keys: str) -> List[str]:
    ids: List[str] = []
    for row in rows or []:
        if not isinstance(row, Mapping):
            continue
        for key in keys:
            value = row.get(key)
            if value is not None and str(value).strip():
                ids.append(str(value).strip())
    return ids
