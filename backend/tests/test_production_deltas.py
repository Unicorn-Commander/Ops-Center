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
    fake_litellm = types.ModuleType("litellm_api")
    fake_litellm.get_user_id = lambda: None
    sys.modules["litellm_api"] = fake_litellm
    from routers.audio_proxy import router

    routes = {route.path for route in router.routes}
    assert "/api/v1/audio/speech" in routes
