"""Symmetric encryption for biometric templates and TOTP secrets (AES-256-GCM)."""
from __future__ import annotations

import base64
import hashlib
import os

import numpy as np
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import settings

_NONCE_LEN = 12


def _key() -> bytes:
    raw = settings.template_key.encode()
    try:
        k = base64.urlsafe_b64decode(raw + b"=" * (-len(raw) % 4))
        if len(k) == 32:
            return k
    except Exception:
        pass
    # Derive a stable 32-byte key from whatever was configured (dev convenience; prod must use 32 random bytes).
    return hashlib.sha256(raw).digest()


def encrypt_bytes(plain: bytes, aad: bytes = b"") -> bytes:
    nonce = os.urandom(_NONCE_LEN)
    return nonce + AESGCM(_key()).encrypt(nonce, plain, aad)


def decrypt_bytes(blob: bytes, aad: bytes = b"") -> bytes:
    nonce, ct = blob[:_NONCE_LEN], blob[_NONCE_LEN:]
    return AESGCM(_key()).decrypt(nonce, ct, aad)


def encrypt_embedding(vec: np.ndarray, aad: str) -> bytes:
    return encrypt_bytes(vec.astype(np.float32).tobytes(), aad.encode())


def decrypt_embedding(blob: bytes, aad: str) -> np.ndarray:
    return np.frombuffer(decrypt_bytes(blob, aad.encode()), dtype=np.float32).copy()


def encrypt_str(s: str) -> str:
    return base64.urlsafe_b64encode(encrypt_bytes(s.encode())).decode()


def decrypt_str(s: str) -> str:
    return decrypt_bytes(base64.urlsafe_b64decode(s.encode())).decode()
