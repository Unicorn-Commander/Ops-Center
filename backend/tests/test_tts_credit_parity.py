"""Credit parity for POST /api/v1/audio/speech.

Fakes the credit system, the org-credit integration, and httpx. No network.
The caller and the Kokoro hosts are fictional. The handler charges
round(len(input) * rate, 6); these tests expect that amount, once.
"""

import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

USER = "tester-basil@example.com"
TEXT = "Basil checks the booth."
PRIMARY = "http://kokoro-a.example:8880"
FALLBACK = "http://kokoro-b.example:8882"
# Not a credential. The ElevenLabs branch only runs when the module global is non-empty.
FIXTURE_EL_KEY = "fixture-el-not-a-key"


def _load_audio_speech_api():
    """Import the handler without pulling the billing DB.

    audio_speech_api imports litellm_api at module scope, and that import
    tries the platform-settings database. Stub the three names it needs,
    then drop the stubs so a later test can still import the real modules.
    The handler keeps the callables it already bound.
    """
    if "audio_speech_api" in sys.modules:
        return sys.modules["audio_speech_api"]

    installed = {}
    if "litellm_api" not in sys.modules:
        fake = types.ModuleType("litellm_api")
        fake.get_user_id = lambda: None
        fake.get_credit_system = lambda: None
        fake.is_credit_exempt = lambda _tier: False
        installed["litellm_api"] = fake
    if "litellm_credit_system" not in sys.modules:
        fake = types.ModuleType("litellm_credit_system")

        class CreditSystem:
            pass

        fake.CreditSystem = CreditSystem
        installed["litellm_credit_system"] = fake
    if "org_credit_integration" not in sys.modules:
        fake = types.ModuleType("org_credit_integration")
        fake.get_org_credit_integration = lambda: None
        installed["org_credit_integration"] = fake

    sys.modules.update(installed)
    try:
        import audio_speech_api
        return audio_speech_api
    finally:
        for name, mod in installed.items():
            if sys.modules.get(name) is mod:
                del sys.modules[name]


audio_speech_api = _load_audio_speech_api()

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest


def _kokoro_cost(text):
    return round(len(text) * audio_speech_api.TTS_CREDIT_PER_CHAR, 6)


def _el_cost(text):
    return round(len(text) * audio_speech_api.ELEVENLABS_CREDIT_PER_CHAR, 6)


class FakeCredits:
    def __init__(self, balance):
        self.balance = balance
        self.debits = []
        self.balance_calls = 0
        self.tier_calls = 0

    async def get_user_tier(self, user_id):
        self.tier_calls += 1
        return "professional"

    async def get_user_credits(self, user_id):
        self.balance_calls += 1
        return self.balance

    async def debit_credits(self, user_id, amount, metadata):
        self.debits.append({
            "user_id": user_id,
            "amount": amount,
            "metadata": dict(metadata),
        })
        return self.balance - amount, "txn-basil-fixture"


class FakeOrg:
    """No organization, so the handler bills the individual balance."""

    def __init__(self):
        self.checks = []
        self.deducts = []

    async def has_sufficient_org_credits(self, user_id, credits_needed):
        self.checks.append((user_id, credits_needed))
        return False, None, "User does not belong to any organization"

    async def deduct_org_credits(self, **kwargs):
        self.deducts.append(kwargs)
        return True, "org-fixture", 0


def _response(status_code, content=b"", content_type="audio/wav"):
    return types.SimpleNamespace(
        status_code=status_code,
        content=content,
        headers={"Content-Type": content_type},
        text="" if isinstance(content, bytes) else str(content),
    )


def _ok_audio():
    return _response(200, b"RIFFfixture-audio")


@pytest.fixture
def speech(monkeypatch):
    """One app, fictional backends, httpx fully scripted."""
    holder = {}

    def make(balance, script, exempt=False, el_key=""):
        credits = FakeCredits(balance)
        org = FakeOrg()
        calls = []
        constructed = []
        script = list(script)

        class FakeClient:
            def __init__(self, *args, **kwargs):
                constructed.append(True)
                self._i = 0

            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

            async def post(self, url, json=None, **_kw):
                # URLs only. Do not record headers: the ElevenLabs call carries the key.
                calls.append(url)
                if self._i >= len(script):
                    return _response(599)
                outcome = script[self._i]
                self._i += 1
                if isinstance(outcome, BaseException):
                    raise outcome
                return outcome

        monkeypatch.setattr(audio_speech_api, "is_credit_exempt", lambda _tier: exempt)
        monkeypatch.setattr(audio_speech_api, "get_org_credit_integration", lambda: org)
        monkeypatch.setattr(audio_speech_api, "ELEVENLABS_API_KEY", el_key)
        monkeypatch.setattr(audio_speech_api.httpx, "AsyncClient", FakeClient)
        monkeypatch.delenv("KOKORO_TTS_URL", raising=False)
        monkeypatch.setenv("TTS_SPEECH_BACKENDS", f"{PRIMARY},{FALLBACK}")

        app = FastAPI()
        app.include_router(audio_speech_api.router)
        app.dependency_overrides[audio_speech_api.get_user_id] = lambda: USER
        app.dependency_overrides[audio_speech_api.get_credit_system] = lambda: credits
        client = TestClient(app)
        holder["client"] = client
        return client, credits, calls, constructed, org

    yield make
    if "client" in holder:
        holder["client"].close()


def _speak(client, text=TEXT, model="tts-1", voice="am_michael"):
    return client.post(
        "/api/v1/audio/speech",
        json={"model": model, "input": text, "voice": voice},
    )


def test_insufficient_credits_refused_before_any_backend_call(speech):
    client, credits, calls, constructed, _org = speech(balance=0, script=[_ok_audio()])
    resp = _speak(client)
    assert resp.status_code == 402
    assert calls == []
    assert constructed == []
    assert credits.debits == []
    assert credits.balance_calls == 1


def test_success_debits_once_at_kokoro_char_rate(speech):
    client, credits, calls, _constructed, org = speech(balance=10, script=[_ok_audio()])
    resp = _speak(client)
    expected = _kokoro_cost(TEXT)
    assert expected == round(len(TEXT) * audio_speech_api.TTS_CREDIT_PER_CHAR, 6)
    assert expected > 0
    assert resp.status_code == 200
    assert resp.headers["X-TTS-Engine"] == "kokoro"
    assert resp.content == b"RIFFfixture-audio"
    assert calls == [f"{PRIMARY}/v1/audio/speech"]
    assert len(credits.debits) == 1
    debit = credits.debits[0]
    assert debit["user_id"] == USER
    assert debit["amount"] == expected
    assert debit["metadata"]["characters"] == len(TEXT)
    assert debit["metadata"]["provider"] == "kokoro"
    assert debit["metadata"]["cost"] == expected
    assert org.deducts == []


def test_backend_error_does_not_debit(speech):
    client, credits, calls, _constructed, _org = speech(
        balance=10,
        script=[RuntimeError("kokoro fixture down"), RuntimeError("kokoro fixture down")],
    )
    resp = _speak(client)
    assert resp.status_code == 502
    assert calls == [f"{PRIMARY}/v1/audio/speech", f"{FALLBACK}/v1/audio/speech"]
    assert credits.debits == []
    assert credits.balance_calls == 1


def test_credit_exempt_user_is_not_debited(speech):
    client, credits, calls, _constructed, org = speech(
        balance=0, script=[_ok_audio()], exempt=True,
    )
    resp = _speak(client)
    assert resp.status_code == 200
    assert calls == [f"{PRIMARY}/v1/audio/speech"]
    assert credits.debits == []
    assert credits.balance_calls == 0
    assert org.checks == []


def test_first_backend_down_uses_second_and_debits_once(speech):
    client, credits, calls, _constructed, _org = speech(
        balance=10,
        script=[_response(503), _ok_audio()],
    )
    resp = _speak(client)
    assert resp.status_code == 200
    assert resp.headers["X-TTS-Engine"] == "kokoro"
    assert calls == [f"{PRIMARY}/v1/audio/speech", f"{FALLBACK}/v1/audio/speech"]
    assert len(credits.debits) == 1
    assert credits.debits[0]["amount"] == _kokoro_cost(TEXT)


def test_elevenlabs_failure_falls_back_to_kokoro_rate(speech):
    client, credits, calls, _constructed, org = speech(
        balance=10,
        script=[_response(429), _ok_audio()],
        el_key=FIXTURE_EL_KEY,
    )
    resp = _speak(client, model="elevenlabs")
    kokoro = _kokoro_cost(TEXT)
    premium = _el_cost(TEXT)
    assert premium > kokoro
    assert resp.status_code == 200
    assert resp.headers["X-TTS-Engine"] == "kokoro"
    assert calls[0].startswith("https://api.elevenlabs.io/v1/text-to-speech/")
    assert calls[1] == f"{PRIMARY}/v1/audio/speech"
    assert len(calls) == 2
    assert len(credits.debits) == 1
    assert credits.debits[0]["amount"] == kokoro
    assert credits.debits[0]["metadata"]["provider"] == "kokoro"
    # Precheck holds the premium rate; the charge is the engine that served.
    assert org.checks == [(USER, premium)]


def test_kokoro_tts_url_is_called_first(monkeypatch, speech):
    monkeypatch.delenv("KOKORO_TTS_URL", raising=False)
    monkeypatch.delenv("TTS_SPEECH_BACKENDS", raising=False)
    assert audio_speech_api._resolve_tts_speech_backends() == [
        "http://100.94.145.98:8880",
        "http://100.126.207.157:8882",
    ]

    client, _credits, calls, _constructed, _org = speech(balance=10, script=[_ok_audio()])
    preferred = "http://kokoro-preferred.example"
    monkeypatch.setenv("KOKORO_TTS_URL", preferred + "/")
    monkeypatch.setenv("TTS_SPEECH_BACKENDS", f"{PRIMARY},{FALLBACK},{PRIMARY}")
    assert audio_speech_api._resolve_tts_speech_backends() == [preferred, PRIMARY, FALLBACK]
    monkeypatch.setenv("KOKORO_TTS_URL", PRIMARY)
    assert audio_speech_api._resolve_tts_speech_backends() == [PRIMARY, FALLBACK]
    monkeypatch.setenv("KOKORO_TTS_URL", preferred)

    resp = _speak(client)
    assert resp.status_code == 200
    assert calls == [f"{preferred}/v1/audio/speech"]


def test_over_max_input_chars_refused_without_debit(speech):
    client, credits, calls, constructed, _org = speech(balance=10, script=[_ok_audio()])
    too_long = "x" * (audio_speech_api.TTS_MAX_INPUT_CHARS + 1)
    resp = _speak(client, text=too_long)
    assert resp.status_code == 400
    assert "too long" in resp.json()["detail"]
    assert calls == []
    assert constructed == []
    assert credits.debits == []
    assert credits.tier_calls == 0
