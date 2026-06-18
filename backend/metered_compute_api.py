"""
Metered Compute API — Lago billing for non-LLM local models
============================================================

Closes the metering gap: today only the Qwen LLMs emit Lago events (via the
litellm success_callback). The other local compute — embeddings, reranking,
STT, TTS — runs unbilled. This router meters all four through the EXISTING
federation metering rail (`FederationMeter.record_usage` →
`_report_to_lago`, keyed `external_subscription_id = org_id`, with the
`gateway_metered` double-bill guard), each with its own unit-based billable
metric:

    embeddings  → metric `embeddings_tokens`     (unit: tokens)
    reranking   → metric `rerank_searches`       (unit: searches)
    STT         → metric `stt_audio_seconds`     (unit: audio_seconds)
    TTS         → metric `tts_characters`        (unit: characters)

Two entry styles:
  - Proxy (small payloads): POST /api/v1/metered/embeddings, /rerank — an
    authenticated app calls these, we forward to the Infinity server, count
    the units from the response, and meter. Transparent once a client
    repoints at it.
  - Report bridge (no payload transit): POST /api/v1/metered/report — a
    service (e.g. the STT/TTS voice plane on another box) reports unit counts
    with a service key. Audio/text never transits ops-center.

Exempt tiers (free / on-device / vip / internal — see CREDIT_EXEMPT_TIERS)
are not metered. Collect-don't-gate: we meter usage but never block the call.

Register the Lago billable metrics once with
`scripts/register_metering_metrics.py`.

Created: 2026-06-18
"""

import logging
import os
import time
import uuid
from typing import Any, Dict, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from auth_dependencies import require_authenticated_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/metered", tags=["Metered Compute"])

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

INFINITY_EMBEDDINGS_URL = os.getenv("INFINITY_EMBEDDINGS_URL", "http://unicorn-embeddings:8082")
INFINITY_RERANK_URL = os.getenv("INFINITY_RERANK_URL", "http://unicorn-reranker:8083")
INFINITY_SERVICE_KEY = os.getenv("INFINITY_SERVICE_KEY", "")

# Service-to-service key for the /report bridge. Reuse the federation key by
# default so the voice plane can authenticate without a new secret.
METERING_SERVICE_KEY = os.getenv("METERING_SERVICE_KEY", "") or os.getenv("FEDERATION_KEY", "")

LAGO_API_URL = os.getenv("LAGO_API_URL", "http://unicorn-lago-api:3000")

BILLING_ENABLED = os.getenv("BILLING_ENABLED", "true").lower() == "true"
CREDIT_EXEMPT_TIERS = set(
    t.strip()
    for t in os.getenv(
        "CREDIT_EXEMPT_TIERS",
        "free,vip_founder,vip,founder,founder_friend,admin,unlimited,internal",
    ).split(",")
    if t.strip()
)

_LOCAL_NODE_ID = os.getenv("FEDERATION_NODE_ID", "ops-center")

# service_type -> (metric_code, unit_name, cost_per_unit_usd)
# Cost basis from the scoping handoff (2026-06-17). The Lago plan charge is
# the source of truth for price; cost_usd here feeds cost dashboards only.
_METRICS: Dict[str, Dict[str, Any]] = {
    "embeddings": {"metric": "embeddings_tokens", "unit": "tokens", "cost_per_unit": 0.02 / 1_000_000},
    "rerank":     {"metric": "rerank_searches",   "unit": "searches", "cost_per_unit": 0.75 / 1_000_000},
    "stt":        {"metric": "stt_audio_seconds", "unit": "audio_seconds", "cost_per_unit": 0.004 / 60.0},
    "tts":        {"metric": "tts_characters",    "unit": "characters", "cost_per_unit": 15.0 / 1_000_000},
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_exempt(tier: Optional[str]) -> bool:
    if not BILLING_ENABLED:
        return True
    if "*" in CREDIT_EXEMPT_TIERS:
        return True
    return (tier or "unknown") in CREDIT_EXEMPT_TIERS


async def _get_meter():
    """Build a FederationMeter configured with the live Lago credentials."""
    from database.connection import get_db_pool
    from federation.metering import FederationMeter
    try:
        from get_credential import get_credential
        lago_key = get_credential("LAGO_API_KEY", "")
    except Exception:
        lago_key = os.getenv("LAGO_API_KEY", "")
    try:
        pool = await get_db_pool()
    except Exception:
        pool = None
    return FederationMeter(pool, lago_url=LAGO_API_URL, lago_api_key=lago_key)


async def _resolve_org(user_id: str) -> tuple[Optional[str], Optional[str]]:
    """Resolve (org_id, plan_tier) for a user via their active org membership."""
    from database.connection import get_db_pool
    try:
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT o.id::text AS org_id, o.plan_tier
                FROM organizations o
                JOIN organization_members om ON om.org_id = o.id
                WHERE om.user_id = $1 AND COALESCE(o.status, 'active') = 'active'
                ORDER BY (o.plan_tier IS NOT NULL) DESC
                LIMIT 1
                """,
                user_id,
            )
            if row:
                return row["org_id"], row["plan_tier"]
    except Exception as exc:
        logger.warning("[metered] org resolution failed for %s: %s", user_id, exc)
    return None, None


async def _tier_for_org(org_id: str) -> Optional[str]:
    from database.connection import get_db_pool
    try:
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT plan_tier FROM organizations WHERE id = $1", org_id)
            if row:
                return row["plan_tier"]
    except Exception as exc:
        logger.warning("[metered] tier lookup failed for org %s: %s", org_id, exc)
    return None


async def _meter(service_type: str, org_id: str, quantity: float, metadata: Dict[str, Any]) -> Optional[str]:
    """Emit one Lago billable event for a non-LLM compute unit. Returns event_id."""
    spec = _METRICS[service_type]
    cost = float(quantity) * spec["cost_per_unit"]
    meter = await _get_meter()
    result = await meter.record_usage({
        "source_node_id": _LOCAL_NODE_ID,
        "target_node_id": _LOCAL_NODE_ID,
        "service_type": service_type,
        "event_type": "inference",
        "org_id": org_id,
        "cost_usd": cost,
        "gateway_metered": False,
        "billing_metric": spec["metric"],
        "billing_quantity": quantity,
        "billing_unit": spec["unit"],
        "metadata": metadata,
    })
    return result.get("event_id")


def _estimate_tokens(payload: Dict[str, Any]) -> int:
    """Fallback token estimate (~4 chars/token) when the upstream omits usage."""
    inp = payload.get("input", payload.get("inputs", ""))
    items = inp if isinstance(inp, list) else [inp]
    chars = sum(len(str(x)) for x in items)
    return max(1, chars // 4)


# ---------------------------------------------------------------------------
# Proxy routes — embeddings & reranking (small payloads, ops-center → Infinity)
# ---------------------------------------------------------------------------

async def _proxy_and_meter(
    request: Request, service_type: str, upstream_base: str, path: str,
    user: Dict[str, Any],
) -> JSONResponse:
    body = await request.json()
    user_id = user.get("user_id") or user.get("sub") or "unknown"
    org_id, tier = await _resolve_org(user_id)
    request_id = str(uuid.uuid4())

    headers = {"X-Request-ID": request_id}
    if INFINITY_SERVICE_KEY:
        headers["Authorization"] = f"Bearer {INFINITY_SERVICE_KEY}"

    start = time.time()
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(120.0)) as client:
            resp = await client.post(f"{upstream_base}{path}", headers=headers, json=body)
    except httpx.TimeoutException:
        return JSONResponse(status_code=504, content={"error": "Gateway Timeout", "detail": f"{service_type} service did not respond in time."})
    except httpx.ConnectError:
        return JSONResponse(status_code=503, content={"error": "Service Unavailable", "detail": f"{service_type} service is not reachable."})
    except Exception as exc:
        return JSONResponse(status_code=502, content={"error": "Bad Gateway", "detail": str(exc)})
    elapsed = round(time.time() - start, 3)

    data = None
    try:
        data = resp.json()
    except Exception:
        data = None

    # Meter only successful responses for non-exempt orgs.
    if resp.status_code in (200, 201) and org_id and not _is_exempt(tier):
        try:
            if service_type == "embeddings":
                usage = (data or {}).get("usage") or {}
                qty = usage.get("total_tokens") or usage.get("prompt_tokens") or _estimate_tokens(body)
            else:  # rerank — one search per request
                qty = 1
            await _meter(service_type, org_id, qty, {
                "request_id": request_id, "elapsed_seconds": elapsed,
                "model": body.get("model", ""), "user_id": user_id,
                "documents": len(body.get("documents", [])) if service_type == "rerank" else None,
            })
        except Exception as exc:
            logger.warning("[metered] %s metering failed (request served): %s", service_type, exc)
    elif org_id and _is_exempt(tier):
        logger.debug("[metered] exempt tier '%s' (org=%s) — %s not metered", tier, org_id, service_type)

    return JSONResponse(status_code=resp.status_code, content=data if data is not None else {"raw": resp.text[:500]})


@router.post("/embeddings")
async def metered_embeddings(request: Request, user: Dict = Depends(require_authenticated_user)):
    """Proxy an OpenAI-style embeddings request to the Infinity server and meter tokens."""
    return await _proxy_and_meter(request, "embeddings", INFINITY_EMBEDDINGS_URL, "/embeddings", user)


@router.post("/rerank")
async def metered_rerank(request: Request, user: Dict = Depends(require_authenticated_user)):
    """Proxy a rerank request to the Infinity reranker and meter one search."""
    return await _proxy_and_meter(request, "rerank", INFINITY_RERANK_URL, "/rerank", user)


# ---------------------------------------------------------------------------
# Report bridge — STT / TTS (and any service) report unit counts
# ---------------------------------------------------------------------------

class MeterReport(BaseModel):
    service_type: str            # "stt" | "tts" | "embeddings" | "rerank"
    quantity: float              # audio_seconds | characters | tokens | searches
    org_id: Optional[str] = None
    user_id: Optional[str] = None
    model: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


@router.post("/report")
async def report_usage(report: MeterReport, request: Request):
    """
    Service-to-service usage report for compute that doesn't transit ops-center
    (e.g. STT/TTS on the voice box). Authenticated with the metering service key.
    """
    key = request.headers.get("X-Metering-Key", "")
    if not METERING_SERVICE_KEY or key != METERING_SERVICE_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing metering service key")

    st = report.service_type.strip().lower()
    if st not in _METRICS:
        raise HTTPException(status_code=422, detail=f"service_type must be one of {sorted(_METRICS)}")
    if report.quantity is None or report.quantity < 0:
        raise HTTPException(status_code=422, detail="quantity must be >= 0")

    org_id = report.org_id
    if not org_id and report.user_id:
        org_id, _ = await _resolve_org(report.user_id)
    if not org_id:
        raise HTTPException(status_code=422, detail="org_id (or a resolvable user_id) is required")

    tier = await _tier_for_org(org_id)
    if _is_exempt(tier):
        logger.debug("[metered] exempt tier '%s' (org=%s) — %s report not metered", tier, org_id, st)
        return {"status": "skipped_exempt", "org_id": org_id, "tier": tier}

    meta = dict(report.metadata or {})
    meta.update({"model": report.model or "", "user_id": report.user_id, "via": "report_bridge"})
    event_id = await _meter(st, org_id, report.quantity, meta)
    return {"status": "recorded", "event_id": event_id, "metric": _METRICS[st]["metric"],
            "quantity": report.quantity, "unit": _METRICS[st]["unit"], "org_id": org_id}


@router.get("/health")
async def metered_health():
    return {
        "status": "healthy",
        "metrics": {k: v["metric"] for k, v in _METRICS.items()},
        "billing_enabled": BILLING_ENABLED,
        "report_bridge_key_configured": bool(METERING_SERVICE_KEY),
    }
