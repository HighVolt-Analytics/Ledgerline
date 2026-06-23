"""Password hashing and JWT tokens."""

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from passlib.context import CryptContext

from app.config import get_settings

_pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")

TOKEN_TYPE_ACCESS = "access"
TOKEN_TYPE_REFRESH = "refresh"
TOKEN_TYPE_CHALLENGE = "challenge"
TOKEN_TYPE_TENANT_SELECT = "tenant_select"


def hash_password(password: str) -> str:
    return _pwd.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return _pwd.verify(plain, hashed)


def _encode(payload: dict[str, Any], *, minutes: int | None = None, days: int | None = None) -> str:
    settings = get_settings()
    data = dict(payload)
    now = datetime.now(timezone.utc)
    if minutes is not None:
        data["exp"] = now + timedelta(minutes=minutes)
    elif days is not None:
        data["exp"] = now + timedelta(days=days)
    data["iat"] = now
    return jwt.encode(data, settings.jwt_secret, algorithm="HS256")


def create_challenge_token(*, auth_account_id: int, email: str) -> str:
    return _encode(
        {
            "sub": str(auth_account_id),
            "email": email.lower(),
            "type": TOKEN_TYPE_CHALLENGE,
            "scope": "otp_pending",
        },
        minutes=5,
    )


def create_tenant_select_token(*, auth_account_id: int, email: str) -> str:
    return _encode(
        {
            "sub": str(auth_account_id),
            "email": email.lower(),
            "type": TOKEN_TYPE_TENANT_SELECT,
        },
        minutes=5,
    )


def create_access_token(
    *,
    user_id: int,
    tenant_id: uuid.UUID,
    tenant_slug: str,
    email: str,
    role: str,
) -> str:
    settings = get_settings()
    return _encode(
        {
            "sub": str(user_id),
            "tenant_id": str(tenant_id),
            "tenant_slug": tenant_slug,
            "email": email,
            "role": role,
            "type": TOKEN_TYPE_ACCESS,
        },
        minutes=settings.access_token_expire_minutes,
    )


def create_refresh_token(
    *,
    user_id: int,
    tenant_id: uuid.UUID,
    tenant_slug: str,
    email: str,
    role: str,
    jti: str,
) -> str:
    settings = get_settings()
    return _encode(
        {
            "sub": str(user_id),
            "tenant_id": str(tenant_id),
            "tenant_slug": tenant_slug,
            "email": email,
            "role": role,
            "type": TOKEN_TYPE_REFRESH,
            "jti": jti,
        },
        days=settings.refresh_token_expire_days,
    )


def decode_token(token: str) -> dict[str, Any] | None:
    settings = get_settings()
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError:
        return None


def decode_access_token(token: str) -> dict[str, Any] | None:
    payload = decode_token(token)
    if not payload:
        return None
    token_type = payload.get("type")
    if token_type is None:
        return payload
    if token_type == TOKEN_TYPE_ACCESS:
        return payload
    return None
