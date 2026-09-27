"""Fernet encryption for API keys and transitional platform-settings reads."""
import logging
import os
from cryptography.fernet import Fernet, InvalidToken
from typing import Optional

logger = logging.getLogger(__name__)
FERNET_TOKEN_PREFIX = "gAAAAA"


def looks_encrypted(value) -> bool:
    """Return whether value has the shape of a Fernet token."""
    if value is None:
        return False
    if isinstance(value, (bytes, bytearray)):
        try:
            value = value.decode()
        except (UnicodeDecodeError, AttributeError):
            return False
    return isinstance(value, str) and value.startswith(FERNET_TOKEN_PREFIX)


class KeyEncryption:
    """Handles encryption and decryption of API keys"""

    def __init__(self):
        """Initialize encryption with key from environment"""
        encryption_key = os.getenv('ENCRYPTION_KEY')
        if not encryption_key:
            raise ValueError(
                "ENCRYPTION_KEY environment variable not set. "
                "Generate one with: python3 -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
            )

        try:
            self.cipher = Fernet(encryption_key.encode())
        except Exception as e:
            raise ValueError(f"Invalid ENCRYPTION_KEY format: {e}")

    def encrypt_key(self, api_key: str) -> str:
        """
        Encrypt an API key

        Args:
            api_key: Plain text API key

        Returns:
            Encrypted API key as base64 string
        """
        if not api_key:
            raise ValueError("API key cannot be empty")

        try:
            encrypted = self.cipher.encrypt(api_key.encode())
            return encrypted.decode()
        except Exception as e:
            raise ValueError(f"Encryption failed: {e}")

    def decrypt_key(self, encrypted_key: str) -> str:
        """
        Decrypt an API key

        Args:
            encrypted_key: Base64 encrypted API key

        Returns:
            Decrypted plain text API key
        """
        if not encrypted_key:
            raise ValueError("Encrypted key cannot be empty")

        try:
            decrypted = self.cipher.decrypt(encrypted_key.encode())
            return decrypted.decode()
        except Exception as e:
            raise ValueError(f"Decryption failed: {e}")

    def decrypt_if_encrypted(self, value):
        """Decrypt Fernet-shaped values; preserve legacy plaintext values."""
        if not looks_encrypted(value):
            return value
        raw = value.decode() if isinstance(value, (bytes, bytearray)) else value
        try:
            return self.cipher.decrypt(raw.encode()).decode()
        except InvalidToken:
            logger.error("Platform value has Fernet shape but cannot be decrypted with the current key")
            return value

    def mask_key(self, api_key: str, visible_chars: int = 4) -> str:
        """
        Mask an API key for display

        Args:
            api_key: Plain text API key
            visible_chars: Number of characters to show at start and end

        Returns:
            Masked API key (e.g., "sk-1234...5678")
        """
        if not api_key or len(api_key) < visible_chars * 2:
            return "****"

        return f"{api_key[:visible_chars]}...{api_key[-visible_chars:]}"


# Singleton instance
_encryption_instance: Optional[KeyEncryption] = None


def get_encryption() -> KeyEncryption:
    """Get or create singleton encryption instance"""
    global _encryption_instance
    if _encryption_instance is None:
        _encryption_instance = KeyEncryption()
    return _encryption_instance


def decrypt_if_encrypted(value):
    """Read a mixed legacy-plaintext/new-ciphertext platform value safely."""
    if not looks_encrypted(value):
        return value
    try:
        return get_encryption().decrypt_if_encrypted(value)
    except ValueError as exc:
        logger.error("Encrypted platform value cannot be read: %s", exc)
        return value


def encrypt_if_plaintext(value: str) -> str:
    """Encrypt a value unless it is already ciphertext; safe to repeat."""
    if value is None or value == "" or looks_encrypted(value):
        return value
    return get_encryption().encrypt_key(value)
