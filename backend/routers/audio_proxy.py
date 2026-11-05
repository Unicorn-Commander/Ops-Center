"""OpenAI-compatible TTS proxy backed by the internal Kokoro HA service."""

import logging
import os
from typing import Any, Dict

import httpx
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, Response

from litellm_api import get_user_id

logger = logging.getLogger(__name__)
KOKORO_TTS_URL = os.getenv("KOKORO_TTS_URL", "http://kokoro-ha").rstrip("/")
MAX_INPUT_CHARS = int(os.getenv("TTS_MAX_INPUT_CHARS", "4096"))
REQUEST_TIMEOUT = httpx.Timeout(60.0, connect=10.0)
ALLOWED_MODELS = {"kokoro", "tts-1", "tts-1-hd", "gpt-4o-mini-tts"}
DEFAULT_MODEL = "kokoro"
DEFAULT_VOICE = "am_michael"

router = APIRouter(prefix="/api/v1/audio", tags=["audio-tts"])


async def _meter_tts(user_id: str, model: str, chars: int) -> None:
    """Best-effort metering; synthesis must not fail because billing is down."""
    if chars <= 0:
        return
    try:
        from metered_compute_api import _resolve_org, _is_exempt, _meter
        org_id, plan_tier = await _resolve_org(user_id)
        if org_id and not _is_exempt(plan_tier):
            await _meter("tts", org_id, float(chars), {
                "model": model, "source": "audio_speech", "user_id": user_id,
            })
    except Exception as exc:
        logger.warning("[audio-tts] metering failed (best-effort): %s", exc)


@router.post("/speech")
async def speech(request: Request, user_id: str = Depends(get_user_id)) -> Response:
    """Proxy text-to-speech to Kokoro and meter successful character usage."""
    try:
        body: Dict[str, Any] = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"error": "invalid JSON body"})

    text = body.get("input")
    if not isinstance(text, str) or not text.strip():
        return JSONResponse(status_code=400, content={"error": "'input' (the text to speak) is required"})
    if len(text) > MAX_INPUT_CHARS:
        return JSONResponse(status_code=413, content={"error": "input too long"})

    model = body.get("model") if body.get("model") in ALLOWED_MODELS else DEFAULT_MODEL
    downstream: Dict[str, Any] = {
        "model": model,
        "input": text,
        "voice": body.get("voice") or DEFAULT_VOICE,
        "response_format": body.get("response_format") or "wav",
    }
    if isinstance(body.get("speed"), (int, float)):
        downstream["speed"] = body["speed"]

    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            resp = await client.post(f"{KOKORO_TTS_URL}/v1/audio/speech", json=downstream)
    except httpx.TimeoutException:
        return JSONResponse(status_code=504, content={"error": "TTS backend timed out"})
    except httpx.ConnectError:
        return JSONResponse(status_code=503, content={"error": "TTS backend unavailable"})
    except Exception:
        logger.exception("[audio-tts] proxy error")
        return JSONResponse(status_code=502, content={"error": "TTS backend error"})

    if resp.status_code != 200:
        return JSONResponse(status_code=resp.status_code, content={
            "error": "TTS backend returned an error", "detail": resp.text[:300],
        })
    await _meter_tts(user_id, model, len(text))
    return Response(content=resp.content, status_code=200,
                    media_type=resp.headers.get("content-type", "audio/wav"))
