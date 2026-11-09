"""Signed-in home: ``GET /api/v1/home/state`` and
``POST /api/v1/home/actions/{source}/{item_id}/{action}``.

The state route returns the home-state document (User Home design, section g)
for the signed-in person in their CURRENT organization, as JSON (default) or,
with ``Accept: text/markdown``, as markdown with the same modules and items.

* Off unless ``HOME_STATE_ENABLED`` is true; when off the route answers 404,
  exactly like a route that does not exist.
* Read only. It never writes to any app.
* The person's own Keycloak access token from the Ops-Center session
  (``server.py:6123-6126,6414-6417``) is forwarded to each app as ``Authorization:
  Bearer``, so every app applies the person's own role and scope. When it has
  60 s or less left it is first refreshed with the refresh token kept in the
  same session (``home.session_tokens``); when that fails the home says "Sign in
  again" as before. The token is never logged and never returned.
* The current organization is resolved the same way the entitled app cards
  resolve it (``my_apps_api.get_user_org_from_session``: the
  ``current_org_id`` cookie or the session org, membership-checked).

The action route (``home.actions``) forwards one approve, reject, accept or done
to the app that owns the item, with the same token, organization and hosts, and
returns a receipt. It is off (404) unless ``HOME_ACTIONS_ENABLED`` is true,
independent of ``HOME_STATE_ENABLED``. It is cookie-authenticated and
state-changing, so the CSRF middleware checks it like every other browser POST:
it is on no exemption list (``server.py:785-849``).

The heavy lifting lives in the ``home`` package, which imports nothing from
``server.py``. This module only binds the request to it.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse, PlainTextResponse

from home import actions as home_actions
from home import session_tokens
from home import settings
from home.aggregator import build_home_state
from home.context import HomeContext, HomeProviders, utc_now
from home.mapping import load_workspace_rows
from home.markdown import render_markdown

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/home", tags=["home"])

ROLE_SQL = """
    SELECT om.role
    FROM organization_members om
    LEFT JOIN users u ON u.id::text = om.user_id
    WHERE (om.user_id = $1 OR u.zitadel_id = $1)
      AND om.org_id::text = $2
    LIMIT 1
"""

RESPONSE_HEADERS = {"Cache-Control": "no-store", "Vary": "Accept, Cookie"}
ACTION_HEADERS = {"Cache-Control": "no-store"}


def _request_host(request: Request) -> str:
    """The public host the browser used (same rule as colonel/a2a_server.py:80-83)."""

    forwarded = request.headers.get("x-forwarded-host") or ""
    host = forwarded.split(",")[0].strip() or request.headers.get("host") or (request.url.hostname or "")
    return host.split(":")[0].strip().lower()


def resolve_timezone(name: Optional[str]) -> Tuple[Any, str]:
    for candidate in (name, settings.default_timezone(), "UTC"):
        if not candidate:
            continue
        try:
            return ZoneInfo(candidate), candidate
        except (ZoneInfoNotFoundError, ValueError):
            continue
    return timezone.utc, "UTC"


def wants_markdown(accept: Optional[str]) -> bool:
    """Markdown only when the client names it and does not prefer JSON."""

    markdown_q: Optional[float] = None
    json_q: Optional[float] = None
    for part in (accept or "").split(","):
        pieces = [piece.strip() for piece in part.split(";")]
        media = pieces[0].lower()
        quality = 1.0
        for param in pieces[1:]:
            if param.lower().startswith("q="):
                try:
                    quality = float(param[2:])
                except ValueError:
                    quality = 0.0
        if media == "text/markdown":
            markdown_q = max(markdown_q or 0.0, quality)
        elif media == "application/json":
            json_q = max(json_q or 0.0, quality)
    if not markdown_q:
        return False
    return json_q is None or markdown_q > json_q


async def require_home_enabled() -> None:
    if not settings.home_state_enabled():
        raise HTTPException(status_code=404, detail="Not Found")


async def require_actions_enabled() -> None:
    if not settings.home_actions_enabled():
        raise HTTPException(status_code=404, detail="Not Found")


async def _org_role(subject: str, org_id: str) -> Optional[str]:
    from my_apps_api import get_db_connection

    try:
        conn = await get_db_connection()
    except Exception as exc:  # noqa: BLE001 - an unknown role sees the member view
        logger.warning("home state: role lookup unavailable (%s)", type(exc).__name__)
        return None
    try:
        row = await conn.fetchrow(ROLE_SQL, str(subject), str(org_id))
    except Exception as exc:  # noqa: BLE001
        logger.warning("home state: role lookup failed (%s)", type(exc).__name__)
        return None
    finally:
        await conn.close()
    return str(row["role"]) if row and row["role"] else None


async def get_home_context(
    request: Request,
    tz: Optional[str] = Query(default=None, max_length=64, description="IANA zone for 'today'"),
) -> HomeContext:
    from my_apps_api import _session_data_from_request, _session_subject, get_user_org_from_session

    session = _session_data_from_request(request) or {}
    user = session.get("user") or {}
    subject = _session_subject(session) if session else None
    if not user or not subject:
        raise HTTPException(status_code=401, detail="Sign in to see your home.")

    org_id = await get_user_org_from_session(request)
    if not org_id:
        if getattr(getattr(request, "state", None), "current_org_invalid", False):
            raise HTTPException(status_code=403, detail="The selected organization is not available to you.")
        raise HTTPException(status_code=409, detail="Choose an organization to see its home.")

    host = _request_host(request)
    ring = settings.resolve_ring(host)
    zone, zone_name = resolve_timezone(tz)
    display_name = (
        user.get("name")
        or user.get("preferred_username")
        or user.get("username")
        or user.get("email")
        or "you"
    )
    now = utc_now()
    return HomeContext(
        person_id=str(subject),
        display_name=str(display_name),
        org_id=str(org_id),
        org_name=getattr(getattr(request, "state", None), "current_org_name", None)
        or session.get("org_name"),
        org_role=await _org_role(str(subject), str(org_id)),
        ring=ring,
        tz=zone,
        tz_name=zone_name,
        now=now,
        ops_center_web=settings.ops_center_web_base(ring, host),
        email=user.get("email"),
        access_token=await _access_token(request, session, now),
    )


async def _access_token(request: Request, session: Dict[str, Any], now: datetime) -> Optional[str]:
    """The session's access token, refreshed first when it has 60 s or less
    left. The Keycloak call, and any wait for a refresh another request is
    making, take at most the per-app limit (``HOME_APP_TIMEOUT_SECONDS``)."""

    return await session_tokens.usable_access_token(
        request.cookies.get("session_token"),
        session,
        now=now.timestamp(),
        timeout=settings.app_timeout_seconds(),
        request_url=str(request.url),
    )


def _dump(value: Any) -> Dict[str, Any]:
    if value is None:
        return {}
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if hasattr(value, "dict"):
        return value.dict()
    return dict(value)


async def get_home_providers(
    request: Request, ctx: HomeContext = Depends(get_home_context)
) -> HomeProviders:
    """Bind the in-process Ops-Center sources to this request."""

    async def apps():
        import my_apps_api

        tier = await my_apps_api.get_current_user_tier(request)
        return await my_apps_api.get_my_apps(request, user_tier=tier)

    async def cursor():
        import org_api

        result = await org_api.get_dashboard_cursor(ctx.org_id, request)
        return (result or {}).get("last_seen_at")

    async def usage(days: int):
        import org_billing_api

        return _dump(
            await org_billing_api.get_organization_credit_usage(ctx.org_id, days=days, request=request)
        )

    async def pool():
        import org_billing_api

        try:
            return _dump(await org_billing_api.get_organization_credit_pool(ctx.org_id, request))
        except HTTPException as exc:
            if exc.status_code == 404:
                return None
            raise

    async def workspace_rows():
        from my_apps_api import get_db_connection

        conn = await get_db_connection()
        try:
            return await load_workspace_rows(conn, ctx.org_id)
        finally:
            await conn.close()

    return HomeProviders(apps=apps, cursor=cursor, usage=usage, pool=pool, workspace_rows=workspace_rows)


@router.get("/state", dependencies=[Depends(require_home_enabled)])
async def get_home_state(
    request: Request,
    ctx: HomeContext = Depends(get_home_context),
    providers: HomeProviders = Depends(get_home_providers),
):
    """The home for the signed-in person in their current organization."""

    document = await build_home_state(ctx, providers)
    if wants_markdown(request.headers.get("accept")):
        return PlainTextResponse(
            render_markdown(document),
            media_type="text/markdown; charset=utf-8",
            headers=RESPONSE_HEADERS,
        )
    return JSONResponse(document, headers=RESPONSE_HEADERS)


async def get_action_providers(
    ctx: HomeContext = Depends(get_home_context),
) -> home_actions.ActionProviders:
    """Bind the receipt table and the org's workspace links to this request."""

    from my_apps_api import get_db_connection

    async def workspace_rows():
        conn = await get_db_connection()
        try:
            return await load_workspace_rows(conn, ctx.org_id)
        finally:
            await conn.close()

    return home_actions.ActionProviders(
        store=home_actions.PgReceiptStore(get_db_connection), workspace_rows=workspace_rows
    )


@router.post("/actions/{source}/{item_id}/{action}", dependencies=[Depends(require_actions_enabled)])
async def post_home_action(
    source: str,
    item_id: str,
    action: str,
    ctx: HomeContext = Depends(get_home_context),
    providers: home_actions.ActionProviders = Depends(get_action_providers),
    idempotency_key: Optional[str] = Header(default=None),
):
    """Approve, reject, accept or mark done one home item in the app that owns
    it, once per ``Idempotency-Key``, and return the receipt."""

    try:
        reply = await home_actions.run_action(ctx, providers, source, item_id, action, idempotency_key)
    except Exception as exc:  # noqa: BLE001 - the person gets a problem document, never a 500
        logger.warning("home action: request failed (%s)", type(exc).__name__)
        reply = home_actions.unexpected_problem()
    return JSONResponse(
        reply.body,
        status_code=reply.status_code,
        media_type="application/problem+json" if reply.problem else "application/json",
        headers={**ACTION_HEADERS, **reply.headers},
    )
