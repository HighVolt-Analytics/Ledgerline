"""CSRF OAuth state (JWT) and one-time jti in Redis. Provider-agnostic."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
import redis.asyncio as aioredis

from app.config import get_settings

STATE_TTL_MINUTES = 20
STATE_TTL_SECONDS = STATE_TTL_MINUTES * 60
_JTI_PREFIX = "integrations_oauth_jti:"


def _redis() -> aioredis.Redis:
    return aioredis.from_url(get_settings().redis_url, decode_responses=True)


def create_oauth_state(
    *,
    provider: str,
    tenant_id: uuid.UUID | str,
    user_id: int,
    typ: str,
) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=STATE_TTL_MINUTES)
    payload: dict[str, Any] = {
        "typ": typ,
        "provider": provider,
        "org_id": str(tenant_id),
        "sub": str(user_id),
        "jti": str(uuid.uuid4()),
        "exp": expire,
    }
    return jwt.encode(payload, get_settings().jwt_secret, algorithm="HS256")


def parse_oauth_state(state: str, *, provider: str, typ: str) -> dict[str, Any]:
    payload = jwt.decode(state, get_settings().jwt_secret, algorithms=["HS256"])
    if payload.get("typ") != typ:
        raise ValueError("Invalid OAuth state")
    if payload.get("provider") != provider:
        raise ValueError("OAuth state provider mismatch")
    return payload


async def consume_oauth_jti(jti: str, *, ttl_seconds: int = STATE_TTL_SECONDS) -> bool:
    """True if jti is new; False if replayed."""
    if not jti:
        return False
    r = _redis()
    try:
        created = await r.set(f"{_JTI_PREFIX}{jti}", "1", nx=True, ex=ttl_seconds)
        return bool(created)
    finally:
        await r.aclose()


async def validate_oauth_state_replay(state_payload: dict[str, Any]) -> None:
    jti = str(state_payload.get("jti") or "")
    if not jti:
        raise ValueError("OAuth state missing replay guard")
    if not await consume_oauth_jti(jti):
        raise ValueError("OAuth state already used")
