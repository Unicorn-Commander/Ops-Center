"""Build the home-state document for one person in one organization.

1. In process, in parallel: the entitled app cards (which apps this org has)
   and the ``org_app_workspaces`` rows for the org.
2. In parallel: one adapter per app, each under the per-app limit
   (``HOME_APP_TIMEOUT_SECONDS``, about 2.5 s), plus the visit cursor and, for
   org owners and admins, the org's AI usage. Everything left when the total
   budget (``HOME_TOTAL_BUDGET_SECONDS``) runs out is marked unavailable with
   reason ``timeout``; one slow or failing app never holds the rest.
3. Modules are assembled, the status line is computed, and the whole document
   goes through ``safety.guard_document`` before it is returned.

Apps the org is not entitled to are not called. When the person's token has
already expired no app is called and every app module says ``reauth``.
Nothing here raises for an upstream failure: every failure becomes a module
state.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Mapping, Optional, Set

from . import SCHEMA
from . import settings
from .adapters import ADAPTERS
from .adapters import ops_center
from .adapters.base import (
    EMPTY,
    ERROR,
    NOT_ENTITLED,
    NOT_SET_UP,
    OK,
    REAUTH,
    TIMEOUT,
    UNAVAILABLE,
    AdapterEnv,
    AppSnapshot,
    Part,
    iso,
)
from .context import HomeContext, HomeProviders, token_expired
from .mapping import workspace_candidates
from .modules import (
    build_apps,
    build_money,
    build_needs_you,
    build_recent_meetings,
    build_since_last_visit,
    build_status_line,
    build_today,
    build_usage,
    build_watched_topics,
)
from .safety import guard_document

logger = logging.getLogger("home.aggregator")


async def _workspace_rows(providers: HomeProviders, timeout: float) -> Dict[str, str]:
    try:
        rows = await asyncio.wait_for(providers.workspace_rows(), timeout)
    except Exception as exc:  # noqa: BLE001 - the org id candidate still applies
        logger.warning("home state: workspace rows unavailable (%s)", type(exc).__name__)
        return {}
    return dict(rows or {})


def _launch_urls(cards: Optional[List[Dict[str, Any]]]) -> Dict[str, str]:
    urls: Dict[str, str] = {}
    for card in cards or []:
        slug, launch = card.get("slug"), card.get("launch_url")
        if isinstance(slug, str) and isinstance(launch, str):
            urls[slug] = launch
    return urls


def _plain_snapshot(app: str, status: str, web_base: Optional[str], **kwargs: Any) -> AppSnapshot:
    return AppSnapshot(
        app=app, label=settings.APPS[app].label, status=status, as_of=iso(), web_base=web_base, **kwargs
    )


async def _run_app(
    app: str,
    ctx: HomeContext,
    client: Any,
    rows: Mapping[str, str],
    web_base: Optional[str],
    entitled: Optional[Set[str]],
    token_dead: bool,
    per_app: float,
) -> AppSnapshot:
    spec = settings.APPS[app]
    if entitled is not None and spec.catalog_slugs and not entitled.intersection(spec.catalog_slugs):
        return _plain_snapshot(
            app, NOT_ENTITLED, web_base, note=f"This organization does not have {spec.label}."
        )
    api_base = settings.api_base_url(app, ctx.ring)
    if not api_base:
        return _plain_snapshot(
            app, NOT_SET_UP, web_base, note=f"{spec.label} is not connected to the home on this ring yet."
        )
    if token_dead:
        return _plain_snapshot(app, UNAVAILABLE, web_base, reason=REAUTH, note="Sign in again to refresh.")

    env = AdapterEnv(
        ctx=ctx,
        client=client,
        app=app,
        label=spec.label,
        api_base=api_base,
        web_base=web_base,
        candidates=workspace_candidates(ctx.org_id, app, rows),
        timeout=per_app,
        want_money=ctx.is_manager,
    )
    loop = asyncio.get_running_loop()
    started = loop.time()
    try:
        result = await asyncio.wait_for(ADAPTERS[app](env), timeout=per_app)
    except asyncio.TimeoutError:
        result = _plain_snapshot(app, UNAVAILABLE, web_base, reason=TIMEOUT)
    except Exception as exc:  # noqa: BLE001 - an adapter bug is a module state, never a 500
        logger.warning("home state: %s adapter failed (%s)", app, type(exc).__name__)
        result = _plain_snapshot(app, UNAVAILABLE, web_base, reason=ERROR)
    logger.info(
        "home state: %s %s%s in %d ms",
        app,
        result.status,
        f"/{result.reason}" if result.reason else "",
        int((loop.time() - started) * 1000),
    )
    return result


async def build_home_state(ctx: HomeContext, providers: HomeProviders) -> Dict[str, Any]:
    per_app = settings.app_timeout_seconds()
    budget = settings.total_budget_seconds()
    loop = asyncio.get_running_loop()
    deadline = loop.time() + budget

    # Phase 1: which apps the org has, and the explicit workspace links.
    first_limit = min(per_app, budget)
    apps_part, rows = await asyncio.gather(
        ops_center.apps_part(providers, ctx, first_limit),
        _workspace_rows(providers, first_limit),
    )
    cards = apps_part.data if apps_part.status in (OK, EMPTY) else None
    entitled = {str(card.get("slug")) for card in cards} if cards is not None else None
    launch_urls = _launch_urls(cards)
    web_bases = {
        app: settings.web_base_url(
            app,
            ctx.ring,
            next((launch_urls[s] for s in spec.catalog_slugs if s in launch_urls), None),
        )
        for app, spec in settings.APPS.items()
    }
    token_dead = token_expired(ctx.access_token, ctx.now)

    # Phase 2: every app at once, under the per-app limit and the total budget.
    remaining = max(0.05, deadline - loop.time())
    step_limit = min(per_app, remaining)
    client = providers.client_factory(step_limit)
    try:
        app_tasks = {
            app: asyncio.ensure_future(
                _run_app(app, ctx, client, rows, web_bases[app], entitled, token_dead, step_limit)
            )
            for app in settings.APPS
        }
        cursor_task = asyncio.ensure_future(ops_center.cursor_part(providers, ctx, step_limit))
        usage_task = (
            asyncio.ensure_future(ops_center.usage_part(providers, ctx, step_limit))
            if ctx.is_manager
            else None
        )
        tasks = list(app_tasks.values()) + [cursor_task] + ([usage_task] if usage_task else [])
        _, pending = await asyncio.wait(tasks, timeout=remaining)
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
    finally:
        await client.aclose()

    def result_of(task: "asyncio.Future[Any]") -> Any:
        if task.cancelled() or not task.done() or task.exception() is not None:
            return None
        return task.result()

    snaps: Dict[str, AppSnapshot] = {}
    for app, task in app_tasks.items():
        snaps[app] = result_of(task) or _plain_snapshot(app, UNAVAILABLE, web_bases[app], reason=TIMEOUT)
    cursor_part = result_of(cursor_task) or ops_center_timeout_part("cursor", ctx)
    usage_part = (result_of(usage_task) or ops_center_timeout_part("usage", ctx)) if usage_task else None

    # The home actions are offered on items only when HOME_ACTIONS_ENABLED is
    # on; off, the document is exactly what it was before they existed.
    offer = settings.home_actions_enabled()
    modules: List[Dict[str, Any]] = [
        build_needs_you(ctx, snaps, offer=offer),
        build_today(ctx, snaps, offer=offer),
        build_since_last_visit(ctx, snaps, cursor_part),
        build_apps(ctx, snaps, apps_part),
        build_recent_meetings(ctx, snaps),
        build_watched_topics(ctx, snaps),
    ]
    if ctx.is_manager:
        modules.append(build_money(ctx, snaps))
        if usage_part is not None:
            modules.append(build_usage(ctx, usage_part))

    generated_at = iso()
    document: Dict[str, Any] = {
        "schema": SCHEMA,
        "generated_at": generated_at,
        "person": {
            "id": ctx.person_id,
            "display_name": ctx.display_name,
            "role": ctx.public_role,
        },
        "organization": {"id": ctx.org_id, "name": ctx.org_name, "ring": ctx.ring},
        "timezone": ctx.tz_name,
        "status_line": build_status_line(modules, generated_at),
        "modules": modules,
        "links": {
            "self": "/api/v1/home/state",
            "markdown": "/api/v1/home/state (Accept: text/markdown)",
        },
    }
    guarded, _ = guard_document(document, ctx.ring)
    return guarded


def ops_center_timeout_part(name: str, ctx: HomeContext) -> Part:
    route = (
        ops_center.cursor_route(ctx.org_id) if name == "cursor" else ops_center.usage_route(ctx.org_id)
    )
    screen = (
        f"{ctx.ops_center_web}/dashboard" if name == "cursor"
        else f"{ctx.ops_center_web}/admin/subscription/usage"
    )
    return Part(name, UNAVAILABLE, route=route, screen=screen, reason=TIMEOUT, as_of=iso())
