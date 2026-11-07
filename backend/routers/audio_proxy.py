"""Credit-metered OpenAI-compatible TTS.

server.py includes this module's ``router``. That object is
``audio_speech_api.router``: prod's POST /api/v1/audio/speech (credit
precheck, debit after a successful synthesis, ElevenLabs with Kokoro
fallback). The endpoint function's ``__module__`` stays
``audio_speech_api``; the cutover smoke checks that. There is no second
handler on this path.
"""

from audio_speech_api import router as _audio_speech_router

# Assignment, not only an import: the CI smoke treats a module-scope
# assignment as the router symbol. Same object either way.
router = _audio_speech_router

__all__ = ["router"]
