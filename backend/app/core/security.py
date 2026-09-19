from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
import jwt

from app.core.config import Settings

# bcrypt only looks at the first 72 bytes; newer releases raise on longer input.
MAX_PASSWORD_BYTES = 72

# Verified against when the email is unknown, so "no such user" and "wrong
# password" take about the same time and can't be told apart by timing.
_DUMMY_HASH = bcrypt.hashpw(b"not-a-real-password", bcrypt.gensalt()).decode()


def hash_password(plain_password: str) -> str:
    return bcrypt.hashpw(plain_password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain_password: str, password_hash: str | None) -> bool:
    """Constant-ish time check; pass None when the user doesn't exist."""
    hashed = password_hash or _DUMMY_HASH
    matches = bcrypt.checkpw(plain_password.encode("utf-8")[:MAX_PASSWORD_BYTES], hashed.encode("utf-8"))
    return matches and password_hash is not None


def create_access_token(user_id: str, settings: Settings) -> str:
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": user_id,
        "iat": now,
        "exp": now + timedelta(minutes=settings.jwt_expire_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str, settings: Settings) -> dict[str, Any]:
    """Raises jwt.PyJWTError for bad signatures, expired or malformed tokens."""
    return jwt.decode(
        token,
        settings.jwt_secret_key,
        algorithms=[settings.jwt_algorithm],
        options={"require": ["sub", "exp"]},
    )
