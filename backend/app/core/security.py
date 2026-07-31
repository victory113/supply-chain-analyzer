"""Password hashing and JWT issuance/verification.

Deliberately dependency-light: bcrypt directly rather than passlib (whose
bcrypt backend detection breaks across bcrypt 4.x releases) and PyJWT rather
than python-jose.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt
import jwt

from app.core.config import settings
from app.core.exceptions import AuthenticationError

_BCRYPT_MAX_BYTES = 72  # bcrypt silently truncates beyond this


def hash_password(plain: str) -> str:
    if len(plain.encode("utf-8")) > _BCRYPT_MAX_BYTES:
        raise ValueError("Password exceeds the 72-byte bcrypt limit.")
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except ValueError:
        # Malformed hash in the database — treat as a failed login, not a crash.
        return False


def create_access_token(
    subject: str, *, expires_delta: timedelta | None = None, **claims: Any
) -> str:
    now = datetime.now(UTC)
    expire = now + (expires_delta or timedelta(minutes=settings.access_token_ttl_minutes))
    payload: dict[str, Any] = {
        "sub": subject,
        "iat": int(now.timestamp()),
        "exp": int(expire.timestamp()),
        "jti": str(uuid.uuid4()),
        "type": "access",
        **claims,
    }
    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict[str, Any]:
    try:
        payload: dict[str, Any] = jwt.decode(
            token,
            settings.secret_key,
            algorithms=[settings.jwt_algorithm],
            options={"require": ["exp", "sub"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise AuthenticationError("Token has expired.") from exc
    except jwt.InvalidTokenError as exc:
        raise AuthenticationError("Token is invalid.") from exc

    if payload.get("type") != "access":
        raise AuthenticationError("Token is not an access token.")
    return payload
