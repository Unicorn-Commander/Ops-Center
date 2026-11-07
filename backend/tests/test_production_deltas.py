import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cryptography.fernet import Fernet


def test_platform_encryption_helpers_support_plaintext_and_ciphertext(monkeypatch):
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("ENCRYPTION_KEY", key)
    import key_encryption

    key_encryption._encryption_instance = None
    ciphertext = key_encryption.encrypt_if_plaintext("secret-value")
    assert ciphertext.startswith("gAAAAA")
    assert key_encryption.decrypt_if_encrypted(ciphertext) == "secret-value"
    assert key_encryption.decrypt_if_encrypted("legacy-plaintext") == "legacy-plaintext"
    assert key_encryption.encrypt_if_plaintext(ciphertext) == ciphertext


def test_audio_router_registers_openai_speech_route():
    """server.py includes routers.audio_proxy.router; that is prod's handler.

    Stubs satisfy audio_speech_api on a fresh import (no billing DB). When
    the parity tests already loaded the module, keep that module: replacing
    litellm_api in sys.modules would not change the bound handler.
    """
    if "audio_speech_api" not in sys.modules:
        fake_litellm = types.ModuleType("litellm_api")
        fake_litellm.get_user_id = lambda: None
        fake_litellm.get_credit_system = lambda: None
        fake_litellm.is_credit_exempt = lambda _tier: False
        sys.modules["litellm_api"] = fake_litellm
        if "litellm_credit_system" not in sys.modules:
            fake_credits = types.ModuleType("litellm_credit_system")

            class CreditSystem:
                pass

            fake_credits.CreditSystem = CreditSystem
            sys.modules["litellm_credit_system"] = fake_credits
        if "org_credit_integration" not in sys.modules:
            fake_org = types.ModuleType("org_credit_integration")
            fake_org.get_org_credit_integration = lambda: None
            sys.modules["org_credit_integration"] = fake_org

    from routers.audio_proxy import router
    import audio_speech_api

    assert router is audio_speech_api.router
    speech = [
        route for route in router.routes
        if getattr(route, "path", None) == "/api/v1/audio/speech"
    ]
    assert len(speech) == 1
    assert speech[0].endpoint.__module__ == "audio_speech_api"
