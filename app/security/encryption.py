"""
Fernet-based encryption for sensitive data (cookies, credentials).

Usage:
    from app.security.encryption import encrypt, decrypt, is_available

    safe = encrypt("secret_cookies_json")
    original = decrypt(safe)

Set METAPORN_ENCRYPTION_KEY in environment (32-byte base64url key).
Generate with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
"""
from __future__ import annotations

import base64
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

_KEY_ENV = "METAPORN_ENCRYPTION_KEY"
_fernet = None


def _get_fernet():
    global _fernet
    if _fernet is not None:
        return _fernet
    try:
        from cryptography.fernet import Fernet
    except ImportError:
        logger.warning("cryptography package not installed — encryption disabled")
        return None

    raw_key = os.environ.get(_KEY_ENV, "").strip()
    if not raw_key:
        # Derive a deterministic (but weak) key from API_KEY if no dedicated key set
        api_key = os.environ.get("ADULT_META_API_KEY", "metaporn-default-key-change-me")
        import hashlib
        digest = hashlib.sha256(api_key.encode()).digest()
        raw_key = base64.urlsafe_b64encode(digest).decode()
        logger.warning(
            "METAPORN_ENCRYPTION_KEY not set — deriving from API key. "
            "Set a dedicated key for production security."
        )
    try:
        _fernet = Fernet(raw_key.encode())
        return _fernet
    except Exception as exc:
        logger.error("Invalid METAPORN_ENCRYPTION_KEY: %s", exc)
        return None


def is_available() -> bool:
    """Return True if encryption is fully operational."""
    return _get_fernet() is not None


def encrypt(plaintext: str) -> Optional[str]:
    """Encrypt a string. Returns base64url ciphertext or None on error."""
    if not plaintext:
        return plaintext
    f = _get_fernet()
    if f is None:
        return plaintext  # fallback: store unencrypted
    try:
        return f.encrypt(plaintext.encode()).decode()
    except Exception as exc:
        logger.error("Encryption failed: %s", exc)
        return None


def decrypt(ciphertext: str) -> Optional[str]:
    """Decrypt a string. Returns plaintext or None on error."""
    if not ciphertext:
        return ciphertext
    f = _get_fernet()
    if f is None:
        return ciphertext  # fallback: return as-is
    try:
        return f.decrypt(ciphertext.encode()).decode()
    except Exception as exc:
        logger.error("Decryption failed: %s", exc)
        return None
