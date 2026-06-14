"""
The Guide — an end-user-facing help agent for Ops-Center.

DISTINCT from Colonel: Colonel is the root-level admin/ops agent (bash, docker,
filesystem — full system access). The Guide is for END USERS: it has ZERO
system access — it cannot run any skill, command, or action. It only explains
how to use the platform and points to the right page, grounded in the help
knowledge base. Safe by construction (no skill-execution path exists here).

Ops-center-native: it calls the local inference gateway directly (no Brigade
dependency) with an INTERNAL key and a local model, so end users are never
billed for asking for help and a malicious prompt can't run anything.
"""

import logging
import os
import re
import time
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

logger = logging.getLogger("help_guide")

router = APIRouter(prefix="/api/v1/help", tags=["help"])

# Reuse the platform's user-auth dependency (session cookie / Bearer / API key).
from litellm_api import get_user_id  # noqa: E402

GUIDE_NAME = os.getenv("HELP_GUIDE_NAME", "Guide")
# Model is configurable; if unset or unavailable we auto-pick an available local
# model from the gateway so this works on any node without per-node config.
_CONFIGURED_MODEL = os.getenv("HELP_GUIDE_MODEL", "")

_model_cache: Dict[str, Any] = {"ts": 0.0, "model": None}
_MODEL_TTL = 300.0

# --- The Guide's knowledge (kept compact; mirrors src/data/helpContent.js) ----
GUIDE_KNOWLEDGE = """
Unicorn Commander Ops-Center is the management hub for the UC-Cloud suite. Key areas and pages:

BILLING & PLANS:
- /admin/billing/tiers — subscription tiers (price, included apps, limits, markup).
- /admin/billing/rates — the rate book: markup %, credit value (default $0.01), per-model overrides; local models are bundled ($0) or metered.
- /admin/billing/credits — Buy Credits (one wallet spans free local + paid cloud usage).
- /admin/billing/credit-packs — define buyable credit packs.
- /admin/billing/inference-policy — per-(app,model) included-vs-metered; default is metered.
- /admin/billing/agent-pricing — units charged per federated agent invocation.

AI & MODELS:
- /admin/ai/models — model catalog: federation (local GPU, free/bundled) + cloud (cost+markup via gateway).
- /admin/ai/model-lists — curated per-app model lists with tier visibility.

INFRASTRUCTURE & FEDERATION:
- /admin/infra/federation — node identity, branding, peers, advertised services.
- /admin/infra/federation/contracts — ENFORCED trust per peer: trust_mode (full/scoped/consumer/publisher/isolated), publish[]/consume[] ACLs; global default isolated = deny-by-default.
- /admin/infra/services, /resources, /hardware, /network, /storage, /traefik — server management.

PEOPLE & ACCESS:
- /admin/people/users — users (tier controls app access; role controls Ops-Center permissions).
- /admin/people/organizations — orgs are tenants/workspaces sharing billing + a credit pool.
- /admin/people/org-features — grant a specific app to one org regardless of its tier.
- /admin/people/authentication — Keycloak SSO (uchub realm), brokered Google/GitHub/Microsoft.

MONITORING & INTEGRATIONS:
- /admin/monitoring/analytics, /logs, /alerts, /audit — observability.
- /admin/integrations/credentials — Stripe/Lago/Keycloak/Cloudflare/Forgejo keys (with test).
- /admin/integrations/email — email providers.

PLATFORM:
- /admin (Admin Dashboard) — infra health. /admin/my-dashboard — personal credits/usage/subscription.
- /admin/platform/white-label, /landing — branding. /admin/platform/extensions — add-ons marketplace.

KEY CONCEPTS:
- Subscription = app access (+ some included inference). Credits = a metered inference wallet. They are ORTHOGONAL: a solo founder can need more credits than an enterprise.
- Local models (own GPUs) bill $0 (fair-use throttled). Cloud models bill provider cost + markup.
- Colonel is the root-level admin agent (separate from you). You are the Guide — you help end users and never run actions.

COMMON Q&A:
Q: How do credits work? A: One wallet covers free local ($0) and paid cloud (cost+markup) usage; top up on the Buy Credits page or via your plan allocation.
Q: How do I upgrade my plan? A: From My Dashboard or Current Plan, choose a higher tier; it takes effect immediately.
Q: Metered vs included models? A: Included = bundled into a subscription (cost absorbed); metered = drawn from the credit wallet. Set per (app, model) under Inference Policy; default is metered.
Q: Federation Settings vs Contracts? A: Settings = node identity/peers/advertised services; Contracts = the ENFORCED trust (trust_mode + publish/consume ACLs) that gates traffic.
Q: How do I give an org a premium app without changing its tier? A: Use Org Feature Grants (/admin/people/org-features).
Q: Tier vs role? A: Tier controls which apps a user can access; role controls what they can do inside Ops-Center.
"""

GUIDE_SYSTEM_PROMPT = f"""You are {GUIDE_NAME}, the friendly help assistant for Unicorn Commander Ops-Center.

Your job: help end users and admins understand and navigate the platform — what a page does, where to find a setting, how billing/credits/federation/access work. Be warm, concise, and practical. When relevant, name the exact page (e.g. "go to Billing → Rates at /admin/billing/rates").

Hard rules:
- You CANNOT take any action, run any command, change any setting, or access the system. You only explain and guide. If asked to DO something, explain where the user can do it themselves.
- Only answer questions about using Unicorn Commander / Ops-Center. For anything off-topic, briefly say it's outside your scope and suggest the relevant page or contacting support.
- If you are not sure, say so and point to the most relevant page or the Help panel's FAQ tab. Do not invent features.
- Keep answers short (2-5 sentences) unless asked for detail.

Use this knowledge base:
{GUIDE_KNOWLEDGE}
"""


class GuideMessage(BaseModel):
    role: str
    content: str


class GuideAskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=4000)
    page: Optional[str] = None          # current route, for context
    page_help: Optional[str] = None     # optional: the current page's help text
    history: List[GuideMessage] = Field(default_factory=list)


_THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


def _strip_thinking(text: str) -> str:
    """Reasoning models (Qwen3/DeepSeek-style) emit <think>...</think> chain-of-
    thought. Strip it so the Guide shows only the answer."""
    if not text:
        return text
    # Remove properly-closed reasoning blocks, then any stray/unclosed tags
    # (keeping the answer text that follows a bare <think> prefix).
    text = _THINK_BLOCK.sub("", text)
    text = re.sub(r"</?think>", "", text, flags=re.IGNORECASE)
    return text.strip()


async def _resolve_gateway() -> tuple:
    try:
        from gateway_key_provisioning import _resolve_gateway_creds
        url, key = await _resolve_gateway_creds()
        return (url or "").rstrip("/"), key or ""
    except Exception as exc:
        logger.debug("Guide gateway creds unavailable: %s", exc)
        return "", ""


async def _pick_model(gateway_url: str, master_key: str, client: httpx.AsyncClient) -> Optional[str]:
    """Choose an available model: configured one if present, else a small/local
    model from the gateway, else the first available. Cached."""
    now = time.monotonic()
    if _model_cache["model"] and (now - _model_cache["ts"]) < _MODEL_TTL:
        return _model_cache["model"]
    try:
        resp = await client.get(f"{gateway_url}/v1/models", headers={"Authorization": f"Bearer {master_key}"})
        ids = [m.get("id") for m in (resp.json().get("data") or []) if m.get("id")] if resp.status_code == 200 else []
    except Exception as exc:
        logger.debug("Guide model list fetch failed: %s", exc)
        ids = []
    chosen = None
    if _CONFIGURED_MODEL and (_CONFIGURED_MODEL in ids or not ids):
        chosen = _CONFIGURED_MODEL
    if not chosen and ids:
        # prefer small/local chat models for a fast, free help experience
        prefer = ("local", "qwen3-30b", "gpt-oss", "gemma", "llama-3.2", "qwen3.6")
        for p in prefer:
            match = next((m for m in ids if p in m.lower()), None)
            if match:
                chosen = match
                break
        chosen = chosen or ids[0]
    if chosen:
        _model_cache.update({"model": chosen, "ts": now})
    return chosen


@router.post("/guide/ask")
async def guide_ask(payload: GuideAskRequest, request: Request, user_id: str = Depends(get_user_id)):
    """Ask the Guide. Returns {answer}. Never bills the user (internal key +
    local model); never executes anything. Fail-soft to a helpful message."""
    fallback = (
        "I'm having trouble reaching my knowledge service right now. "
        "Try the FAQ tab in this Help panel, or check the page you're on — most settings have an info banner."
    )
    gateway_url, master_key = await _resolve_gateway()
    if not gateway_url or not master_key:
        return {"answer": fallback, "ok": False}

    system = GUIDE_SYSTEM_PROMPT
    if payload.page:
        system += f"\n\nThe user is currently on: {payload.page}"
    if payload.page_help:
        system += f"\nHelp shown for this page:\n{payload.page_help[:2000]}"

    messages = [{"role": "system", "content": system}]
    for m in payload.history[-6:]:
        if m.role in ("user", "assistant") and m.content:
            messages.append({"role": m.role, "content": m.content[:4000]})
    messages.append({"role": "user", "content": payload.question})

    timeout = float(os.getenv("HELP_GUIDE_TIMEOUT", "60"))
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            model = await _pick_model(gateway_url, master_key, client)
            if not model:
                return {"answer": fallback, "ok": False}
            resp = await client.post(
                f"{gateway_url}/v1/chat/completions",
                headers={"Authorization": f"Bearer {master_key}", "Content-Type": "application/json"},
                json={"model": model, "messages": messages, "temperature": 0.3, "max_tokens": 700},
            )
        if resp.status_code >= 400:
            logger.warning("Guide gateway %d: %s", resp.status_code, resp.text[:200])
            # stale model? clear cache so next call re-picks.
            _model_cache.update({"model": None, "ts": 0.0})
            return {"answer": fallback, "ok": False}
        data = resp.json()
        answer = (((data.get("choices") or [{}])[0].get("message") or {}).get("content") or "").strip()
        answer = _strip_thinking(answer)
        return {"answer": answer or fallback, "ok": bool(answer), "model": model}
    except Exception as exc:
        logger.warning("Guide ask failed for user %s: %s", user_id, exc)
        return {"answer": fallback, "ok": False}
