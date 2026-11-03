"""Password hashing, JWT issuing/verification, TOTP helpers."""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

import pyotp
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from jose import JWTError, jwt

from app.core.config import settings

_ph = PasswordHasher(time_cost=3, memory_cost=64 * 1024, parallelism=2)
ALGO = "HS256"


def hash_password(password: str) -> str:
    return _ph.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    try:
        return _ph.verify(hashed, password)
    except VerifyMismatchError:
        return False
    except Exception:
        return False


def hash_pin(pin: str, salt: str) -> str:
    return _ph.hash(f"{salt}:{pin}")


def verify_pin(pin: str, salt: str, hashed: str) -> bool:
    return verify_password(f"{salt}:{pin}", hashed)


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _encode(payload: dict[str, Any], expires: timedelta, typ: str) -> str:
    to_encode = {**payload, "exp": now_utc() + expires, "iat": now_utc(), "typ": typ, "jti": secrets.token_urlsafe(8)}
    return jwt.encode(to_encode, settings.secret_key, algorithm=ALGO)


def create_access_token(user_id: str, role: str, mfa_ok: bool) -> str:
    return _encode({"sub": user_id, "role": role, "mfa": mfa_ok}, timedelta(minutes=settings.access_token_minutes), "access")


def create_verification_token(session_id: str, employee_id: str, method: str) -> str:
    return _encode(
        {"sub": employee_id, "sid": session_id, "method": method},
        timedelta(seconds=settings.verification_token_seconds),
        "verify",
    )


def decode_token(token: str, expected_typ: str) -> dict[str, Any] | None:
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[ALGO])
    except JWTError:
        return None
    if payload.get("typ") != expected_typ:
        return None
    return payload


def new_refresh_token() -> tuple[str, str]:
    """Returns (raw_token, sha256_hex). Only the hash is persisted."""
    raw = secrets.token_urlsafe(48)
    return raw, hashlib.sha256(raw.encode()).hexdigest()


def hash_refresh(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def new_totp_secret() -> str:
    return pyotp.random_base32()


def totp_uri(secret: str, email: str) -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=email, issuer_name=settings.app_name)


def verify_totp(secret: str, code: str) -> bool:
    return pyotp.TOTP(secret).verify(code.strip().replace(" ", ""), valid_window=1)
