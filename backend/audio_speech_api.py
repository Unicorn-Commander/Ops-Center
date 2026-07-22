"""
Audio Speech API — public OpenAI-compatible TTS endpoint
========================================================

POST /api/v1/audio/speech

The route native apps (Majik's DJ voice, etc.) hit as `{base}/audio/speech`
with a metered `uc_` API key. Auth + billing mirror the chat-completions
proxy in litellm_api.py: the same `get_user_id` dependency (session cookie /
uc_ key / JWT / service key) and the same org-pool-vs-individual credit
split. Cost is per input character (TTS_CREDIT_PER_CHAR), charged AFTER a
successful synthesis; credit-exempt tiers are never charged.

Synthesis is proxied to the Kokoro OpenAI-compatible backends in
TTS_SPEECH_BACKENDS order (primary GPU box first, CPU fallback second).
This route is the credit-billing authority for uc_-key TTS — it does NOT
also report to the Lago unit-metering bridge (/api/v1/metered/report), which
is the separate org-plan rail fed by the LiteLLM gateway hook.
"""

import logging
import os
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from litellm_api import get_user_id, get_credit_system, is_credit_exempt
from litellm_credit_system import CreditSystem
from org_credit_integration import get_org_credit_integration

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/audio", tags=["Audio Speech"])

# Primary = kokoro on the GPU box, fallback = CPU kokoro on bigboy.
TTS_SPEECH_BACKENDS = [
    u.strip()
    for u in os.getenv(
        "TTS_SPEECH_BACKENDS",
        "http://100.94.145.98:8880,http://100.126.207.157:8882",
    ).split(",")
    if u.strip()
]
# Credits per input character. Default tracks the Lago tts_characters unit
# price ($15/1M chars with the standard markup ≈ 0.00002/char).
TTS_CREDIT_PER_CHAR = float(os.getenv("TTS_CREDIT_PER_CHAR", "0.00002"))
TTS_MAX_INPUT_CHARS = int(os.getenv("TTS_MAX_INPUT_CHARS", "4096"))
TTS_TIMEOUT_SECONDS = float(os.getenv("TTS_TIMEOUT_SECONDS", "60"))

# ElevenLabs premium engine (model "elevenlabs"): platform key, priced
# COST-PLUS over the real EL spend. With eleven_flash_v2_5 (0.5 EL-credit/char)
# the wholesale cost per char is: Creator $22/100k ≈ 0.00011, Pro $99/500k ≈
# 0.000099, Scale $330/2M ≈ 0.0000825 — so the 0.0002 default clears cost
# with ~1.8-2.4x margin at every paid tier (and still undercuts EL retail).
# Tune via env as the account tier changes. The account may be quota-limited —
# synthesis ALWAYS falls back to Kokoro on any EL failure so the default
# voice never goes silent; billing charges the rate of the engine that served.
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY", "")
ELEVENLABS_MODEL_ID = os.getenv("ELEVENLABS_MODEL_ID", "eleven_flash_v2_5")
ELEVENLABS_DEFAULT_VOICE = os.getenv("ELEVENLABS_DEFAULT_VOICE", "IKne3meq5aSn9XLyUdCD")  # Charlie
ELEVENLABS_CREDIT_PER_CHAR = float(os.getenv("ELEVENLABS_CREDIT_PER_CHAR", "0.0002"))

ALLOWED_MODELS = {"tts-1", "tts-1-hd", "kokoro", "gpt-4o-mini-tts", "elevenlabs"}


class SpeechRequest(BaseModel):
    model: str = "tts-1"
    input: str
    voice: str = "am_michael"
    response_format: Optional[str] = None
    speed: Optional[float] = None


def _is_kokoro_voice(voice: str) -> bool:
    """Kokoro ids look like am_michael / af_bella / bm_george."""
    import re

    return bool(re.fullmatch(r"[a-z]{2}_[a-z]+", voice or ""))


def _is_elevenlabs_voice_id(voice: str) -> bool:
    """EL voice ids are ~20-char alphanumeric tokens (never kokoro-shaped)."""
    import re

    return bool(re.fullmatch(r"[A-Za-z0-9]{12,40}", voice or ""))


@router.post("/speech")
async def create_speech(
    body: SpeechRequest,
    user_id: str = Depends(get_user_id),
    credit_system: CreditSystem = Depends(get_credit_system),
):
    text = body.input or ""
    if not text.strip():
        raise HTTPException(status_code=400, detail="input must not be empty")
    if len(text) > TTS_MAX_INPUT_CHARS:
        raise HTTPException(
            status_code=400,
            detail=f"input too long: {len(text)} chars (max {TTS_MAX_INPUT_CHARS})",
        )
    if body.model not in ALLOWED_MODELS:
        raise HTTPException(
            status_code=400,
            detail=f"unknown model '{body.model}' (allowed: {sorted(ALLOWED_MODELS)})",
        )

    user_tier = await credit_system.get_user_tier(user_id)
    wants_elevenlabs = body.model == "elevenlabs"
    # Pre-check at the highest rate this request could bill (EL); the actual
    # charge after synthesis uses the engine that served.
    precheck_rate = ELEVENLABS_CREDIT_PER_CHAR if wants_elevenlabs else TTS_CREDIT_PER_CHAR
    cost = round(len(text) * precheck_rate, 6)

    # Credit pre-check — same org-vs-individual split as chat completions.
    org_id = None
    if not is_credit_exempt(user_tier):
        org_integration = get_org_credit_integration()
        has_org_credits, org_id, message = await org_integration.has_sufficient_org_credits(
            user_id=user_id,
            credits_needed=cost,
        )
        if org_id:
            if not has_org_credits:
                raise HTTPException(
                    status_code=402,
                    detail=f"Insufficient organization credits. {message}",
                )
        else:
            balance = await credit_system.get_user_credits(user_id)
            if balance < cost:
                raise HTTPException(
                    status_code=402,
                    detail=f"Insufficient credits. Balance: {balance:.6f}, cost: {cost:.6f}",
                )

    audio_bytes = None
    content_type = "audio/mpeg"
    served_engine = None
    last_error = None
    async with httpx.AsyncClient(timeout=TTS_TIMEOUT_SECONDS) as client:
        # Engine 1: ElevenLabs (only for model "elevenlabs", only if a
        # platform key is configured). Any failure falls through to Kokoro.
        if wants_elevenlabs and ELEVENLABS_API_KEY:
            el_voice = body.voice if _is_elevenlabs_voice_id(body.voice) else ELEVENLABS_DEFAULT_VOICE
            try:
                resp = await client.post(
                    f"https://api.elevenlabs.io/v1/text-to-speech/{el_voice}",
                    params={"output_format": "mp3_44100_128"},
                    headers={"xi-api-key": ELEVENLABS_API_KEY},
                    json={"text": text, "model_id": ELEVENLABS_MODEL_ID},
                )
                if resp.status_code == 200 and resp.content:
                    audio_bytes = resp.content
                    content_type = resp.headers.get("Content-Type", "audio/mpeg")
                    served_engine = "elevenlabs"
                else:
                    last_error = f"elevenlabs returned {resp.status_code}"
                    logger.warning(f"TTS {last_error}; falling back to kokoro")
            except Exception as exc:
                last_error = f"elevenlabs: {exc}"
                logger.warning(f"TTS elevenlabs failed ({exc}); falling back to kokoro")

        # Engine 2: Kokoro backend chain (native for the OpenAI-style models,
        # fallback for "elevenlabs"). Voice must be a Kokoro id here — an EL
        # voice id degrades to the house default rather than erroring.
        if audio_bytes is None:
            payload = {
                "model": body.model if not wants_elevenlabs else "tts-1",
                "input": text,
                "voice": body.voice if _is_kokoro_voice(body.voice) else "am_michael",
            }
            if body.response_format:
                payload["response_format"] = body.response_format
            if body.speed is not None:
                payload["speed"] = body.speed
            for backend in TTS_SPEECH_BACKENDS:
                try:
                    resp = await client.post(f"{backend}/v1/audio/speech", json=payload)
                    if resp.status_code == 200 and resp.content:
                        audio_bytes = resp.content
                        content_type = resp.headers.get("Content-Type", content_type)
                        served_engine = "kokoro"
                        break
                    last_error = f"{backend} returned {resp.status_code}"
                    logger.warning(f"TTS backend {last_error}; trying next")
                except Exception as exc:
                    last_error = f"{backend}: {exc}"
                    logger.warning(f"TTS backend failed ({last_error}); trying next")

    if audio_bytes is None:
        raise HTTPException(
            status_code=502,
            detail=f"All TTS backends failed. Last error: {last_error}",
        )

    # Bill at the rate of the engine that actually served.
    served_rate = ELEVENLABS_CREDIT_PER_CHAR if served_engine == "elevenlabs" else TTS_CREDIT_PER_CHAR
    cost = round(len(text) * served_rate, 6)

    # Charge only after successful synthesis; never fail the response on a
    # deduction error (log loudly instead).
    if not is_credit_exempt(user_tier) and cost > 0:
        try:
            if org_id:
                success, used_org_id, _ = await get_org_credit_integration().deduct_org_credits(
                    user_id=user_id,
                    credits_used=cost,
                    service_name=f"{served_engine}-tts",
                    provider=served_engine,
                    model=body.model,
                    tokens_used=len(text),
                    power_level="balanced",
                    task_type="tts",
                    request_id=None,
                    org_id=org_id,
                )
                if success:
                    logger.info(
                        f"TTS: deducted {cost:.6f} credits from org {used_org_id} "
                        f"({len(text)} chars) for user {user_id}"
                    )
                else:
                    logger.error(f"TTS: org credit deduction FAILED for user {user_id} org {org_id}")
            else:
                await credit_system.debit_credits(
                    user_id=user_id,
                    amount=cost,
                    metadata={
                        "provider": served_engine,
                        "model": body.model,
                        "characters": len(text),
                        "task_type": "tts",
                        "cost": cost,
                    },
                )
                logger.info(
                    f"TTS: deducted {cost:.6f} credits from user {user_id} ({len(text)} chars)"
                )
        except Exception as exc:
            logger.error(f"TTS: credit deduction error for user {user_id}: {exc}", exc_info=True)

    return Response(
        content=audio_bytes,
        media_type=content_type,
        headers={"X-TTS-Engine": served_engine or "unknown"},
    )
