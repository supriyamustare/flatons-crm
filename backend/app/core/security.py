"""Password hashing (bcrypt) and JWT creation/verification."""

import uuid
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import Any, Literal

import bcrypt
import jwt

from app.core.config import get_settings

TokenType = Literal["access", "refresh"]


def hash_password(password: str) -> str:
    rounds = get_settings().bcrypt_rounds
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds)).decode()


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), hashed.encode())
    except ValueError:
        return False


@lru_cache
def dummy_hash() -> str:
    """Hash checked when an email doesn't exist, so response time doesn't reveal it."""
    return hash_password("not-a-real-password")


def create_token(
    *, user_id: int, token_version: int, token_type: TokenType, expires_in: timedelta
) -> str:
    settings = get_settings()
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "type": token_type,
        "ver": token_version,
        "iat": now,
        "exp": now + expires_in,
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)


def decode_token(token: str, expected_type: TokenType) -> dict[str, Any]:
    """Return the payload, or raise jwt.InvalidTokenError (bad signature, expired, wrong type)."""
    settings = get_settings()
    payload = jwt.decode(
        token,
        settings.secret_key,
        algorithms=[settings.algorithm],
        options={"require": ["sub", "type", "ver", "exp"]},
    )
    if payload.get("type") != expected_type:
        raise jwt.InvalidTokenError("Wrong token type")
    return payload
