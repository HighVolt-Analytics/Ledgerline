"""Redis-backed OTP and refresh token sessions."""

from __future__ import annotations

import json
import secrets
import uuid
from datetime import timedelta

import redis.asyncio as aioredis

from app.config import get_settings

_OTP_PREFIX = "auth_otp_v2:"
_REFRESH_PREFIX = "auth_refresh:"
_REVOKE_PREFIX = "auth_user_revoke:"
_PASSWORD_RESET_PREFIX = "auth_password_reset:"


def _redis() -> aioredis.Redis:
    return aioredis.from_url(get_settings().redis_url, decode_responses=True)


async def store_otp(*, auth_account_id: int, email: str, otp: str, ttl_seconds: int) -> None:
    r = _redis()
    try:
        await r.setex(f"{_OTP_PREFIX}{auth_account_id}:{email.lower()}", ttl_seconds, otp)
    finally:
        await r.aclose()


async def verify_otp(*, auth_account_id: int, email: str, otp: str) -> bool:
    settings = get_settings()
    if not settings.is_production and otp == settings.dev_otp_code:
        return True
    r = _redis()
    try:
        stored = await r.get(f"{_OTP_PREFIX}{auth_account_id}:{email.lower()}")
        return stored is not None and stored == otp
    finally:
        await r.aclose()


async def clear_otp(*, auth_account_id: int, email: str) -> None:
    r = _redis()
    try:
        await r.delete(f"{_OTP_PREFIX}{auth_account_id}:{email.lower()}")
    finally:
        await r.aclose()


async def store_password_reset_jti(*, jti: str, auth_account_id: int, ttl_seconds: int) -> None:
    r = _redis()
    try:
        await r.setex(f"{_PASSWORD_RESET_PREFIX}{jti}", ttl_seconds, str(auth_account_id))
    finally:
        await r.aclose()


async def consume_password_reset_jti(*, jti: str, auth_account_id: int) -> bool:
    """Return True and delete the key only when it matches the account (single-use)."""
    r = _redis()
    key = f"{_PASSWORD_RESET_PREFIX}{jti}"
    try:
        stored = await r.get(key)
        if stored is None or stored != str(auth_account_id):
            return False
        await r.delete(key)
        return True
    finally:
        await r.aclose()


_REFRESH_GRACE_SECONDS = 90


async def register_refresh_session(
    *,
    jti: str,
    user_id: int,
    tenant_id: uuid.UUID,
    ttl_days: int,
) -> None:
    r = _redis()
    try:
        payload = json.dumps({"user_id": user_id, "tenant_id": str(tenant_id)})
        await r.setex(f"{_REFRESH_PREFIX}{jti}", timedelta(days=ttl_days), payload)
    finally:
        await r.aclose()


async def validate_refresh_jti(jti: str) -> dict | None:
    r = _redis()
    try:
        raw = await r.get(f"{_REFRESH_PREFIX}{jti}")
        if not raw:
            return None
        return json.loads(raw)
    finally:
        await r.aclose()


async def revoke_refresh_jti(jti: str) -> None:
    r = _redis()
    try:
        await r.delete(f"{_REFRESH_PREFIX}{jti}")
    finally:
        await r.aclose()


async def grace_revoke_refresh_jti(jti: str, *, grace_seconds: int = _REFRESH_GRACE_SECONDS) -> None:
    """Short overlap so concurrent refresh (multi-tab) does not brick sibling sessions."""
    r = _redis()
    try:
        key = f"{_REFRESH_PREFIX}{jti}"
        ttl = await r.ttl(key)
        if ttl > 0:
            await r.expire(key, min(ttl, grace_seconds))
        else:
            await r.delete(key)
    finally:
        await r.aclose()


async def revoke_all_user_sessions(user_id: int) -> None:
    r = _redis()
    try:
        await r.setex(f"{_REVOKE_PREFIX}{user_id}", timedelta(days=90), "1")
    finally:
        await r.aclose()


async def is_user_revoked(user_id: int) -> bool:
    r = _redis()
    try:
        return await r.exists(f"{_REVOKE_PREFIX}{user_id}") > 0
    finally:
        await r.aclose()


def new_jti() -> str:
    return str(uuid.uuid4())


def generate_otp() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"
