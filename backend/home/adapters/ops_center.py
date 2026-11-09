"""Ops-Center's own sources, called in process (never an HTTP self-call).

* Entitled app cards: ``my_apps_api.get_my_apps`` (``backend/my_apps_api.py:703-848``),
  the function behind ``GET /api/v1/my-apps/authorized``. It checks the
  selected org's entitlements and returns each card's ``launch_url`` and its
  Connect your AI ``companion`` block (``my_apps_api.py:86-97,229-258``).
* Visit cursor: ``org_api.get_dashboard_cursor`` (``backend/org_api.py:1619-1660``),
  ``{org_id, last_seen_at, server_now}`` from ``organization_audit_log``. The
  home only reads it; the page moves it forward after it renders, as today.
* Org AI usage: ``org_billing_api.get_organization_credit_usage``
  (``backend/org_billing_api.py:760-859``): ``total_credits_used, user_count,
  service_breakdown, top_users, date_range_start, date_range_end`` over a
  rolling window of N days; and ``get_organization_credit_pool``
  (``:475-534``) for the pool, which answers 404 when the org has none.

This module only shapes those results. ``home_api.py`` binds the real
functions; the tests bind fakes.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Dict, Optional, Tuple

from ..context import HomeContext, HomeProviders
from .base import EMPTY, ERROR, OK, TIMEOUT, UNAVAILABLE, Part, iso

logger = logging.getLogger("home.adapters")

APPS_ROUTE = "/api/v1/my-apps/authorized"


def cursor_route(org_id: str) -> str:
    return f"/api/v1/org/{org_id}/dashboard-cursor"


def usage_route(org_id: str) -> str:
    return f"/api/v1/org-billing/credits/{org_id}/usage?days=30"


async def _run(awaitable: Awaitable[Any], timeout: float) -> Tuple[bool, Any]:
    try:
        return True, await asyncio.wait_for(awaitable, timeout)
    except asyncio.TimeoutError:
        return False, TIMEOUT
    except Exception as exc:  # noqa: BLE001 - an in-process failure is a module state, never a 500
        logger.warning("home state: in-process source failed (%s)", type(exc).__name__)
        return False, ERROR


async def apps_part(providers: HomeProviders, ctx: HomeContext, timeout: float) -> Part:
    screen = f"{ctx.ops_center_web}/dashboard"
    ok, value = await _run(providers.apps(), timeout)
    if not ok:
        return Part("apps", UNAVAILABLE, route=APPS_ROUTE, screen=screen, reason=value, as_of=iso())
    cards = [card for card in value or [] if isinstance(card, dict)]
    return Part("apps", OK if cards else EMPTY, route=APPS_ROUTE, screen=screen, data=cards, as_of=iso())


async def cursor_part(providers: HomeProviders, ctx: HomeContext, timeout: float) -> Part:
    screen = f"{ctx.ops_center_web}/dashboard"
    route = cursor_route(ctx.org_id)
    ok, value = await _run(providers.cursor(), timeout)
    if not ok:
        return Part("cursor", UNAVAILABLE, route=route, screen=screen, reason=value, as_of=iso())
    return Part("cursor", OK if value else EMPTY, route=route, screen=screen, data=value, as_of=iso())


def _as_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


async def usage_part(providers: HomeProviders, ctx: HomeContext, timeout: float) -> Part:
    # The org-wide figure has no member-facing screen yet (the usage attribution
    # page is commented out in src/App.jsx:685-688), so the link opens the
    # nearest one, "Usage & Limits" (src/config/routes.js:184-189).
    screen = f"{ctx.ops_center_web}/admin/subscription/usage"
    route = usage_route(ctx.org_id)
    results = await asyncio.gather(
        _run(providers.usage(30), timeout),
        _run(providers.usage(1), timeout),
        _run(providers.pool(), timeout),
    )
    (ok_month, month), (ok_day, day), (ok_pool, pool) = results
    if not ok_month:
        return Part("usage", UNAVAILABLE, route=route, screen=screen, reason=month, as_of=iso())
    month = month if isinstance(month, dict) else {}
    day = day if ok_day and isinstance(day, dict) else None
    breakdown = month.get("service_breakdown") if isinstance(month.get("service_breakdown"), dict) else {}
    services = sorted(
        ({"service": str(name), "credits": _as_int(credits)} for name, credits in breakdown.items()),
        key=lambda row: row["credits"],
        reverse=True,
    )[:5]
    pool_view: Optional[Dict[str, int]] = None
    if ok_pool and isinstance(pool, dict):
        pool_view = {
            "total": _as_int(pool.get("total_credits")),
            "used": _as_int(pool.get("used_credits")),
            "available": _as_int(pool.get("available_credits")),
        }
    data = {
        "last_30_days": _as_int(month.get("total_credits_used")),
        "last_24_hours": _as_int(day.get("total_credits_used")) if day is not None else None,
        "people_using_ai_30_days": _as_int(month.get("user_count")),
        "services": services,
        "pool": pool_view,
    }
    status = OK if data["last_30_days"] or pool_view else EMPTY
    return Part("usage", status, route=route, screen=screen, data=data, as_of=iso())
