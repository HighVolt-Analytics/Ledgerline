"""Redis-backed signup wizard state (pre-tenant provisioning)."""

from __future__ import annotations

import json
import secrets
import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Literal

import redis.asyncio as aioredis

from app.config import get_settings

_SIGNUP_PREFIX = "signup_session:v1:"
_REGISTER_META_PREFIX = "signup_register_meta:"
_TTL_HOURS = 48

SignupStatus = Literal["identity", "organization", "plan", "payment", "provisioning", "completed"]
SignupProvider = Literal["email", "google", "microsoft"]


@dataclass
class SignupSession:
    session_id: str
    email: str
    full_name: str
    provider: SignupProvider
    status: SignupStatus
    password_hash: str | None = None
    auth_account_id: int | None = None
    organization_name: str | None = None
    organization_slug: str | None = None
    country: str | None = None
    plan: str | None = None
    tenant_id: str | None = None
    stripe_session_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "email": self.email,
            "full_name": self.full_name,
            "provider": self.provider,
            "status": self.status,
            "password_hash": self.password_hash,
            "auth_account_id": self.auth_account_id,
            "organization_name": self.organization_name,
            "organization_slug": self.organization_slug,
            "country": self.country,
            "plan": self.plan,
            "tenant_id": self.tenant_id,
            "stripe_session_id": self.stripe_session_id,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SignupSession:
        return cls(
            session_id=str(data["session_id"]),
            email=str(data["email"]),
            full_name=str(data.get("full_name") or ""),
            provider=data.get("provider") or "email",
            status=data.get("status") or "identity",
            password_hash=data.get("password_hash"),
            auth_account_id=data.get("auth_account_id"),
            organization_name=data.get("organization_name"),
            organization_slug=data.get("organization_slug"),
            country=data.get("country"),
            plan=data.get("plan"),
            tenant_id=data.get("tenant_id"),
            stripe_session_id=data.get("stripe_session_id"),
        )


def _redis() -> aioredis.Redis:
    return aioredis.from_url(get_settings().redis_url, decode_responses=True)


def _ttl_seconds() -> int:
    return _TTL_HOURS * 3600


def new_session_id() -> str:
    return str(uuid.uuid4())


async def save_signup_session(session: SignupSession) -> None:
    r = _redis()
    try:
        await r.setex(
            f"{_SIGNUP_PREFIX}{session.session_id}",
            _ttl_seconds(),
            json.dumps(session.to_dict()),
        )
    finally:
        await r.aclose()


async def load_signup_session(session_id: str) -> SignupSession | None:
    r = _redis()
    try:
        raw = await r.get(f"{_SIGNUP_PREFIX}{session_id}")
        if not raw:
            return None
        return SignupSession.from_dict(json.loads(raw))
    finally:
        await r.aclose()


async def delete_signup_session(session_id: str) -> None:
    r = _redis()
    try:
        await r.delete(f"{_SIGNUP_PREFIX}{session_id}")
    finally:
        await r.aclose()


async def store_register_meta(*, email: str, password_hash: str, full_name: str) -> None:
    r = _redis()
    try:
        payload = json.dumps(
            {"email": email.lower(), "password_hash": password_hash, "full_name": full_name}
        )
        await r.setex(f"{_REGISTER_META_PREFIX}{email.lower()}", _ttl_seconds(), payload)
    finally:
        await r.aclose()


async def pop_register_meta(email: str) -> dict[str, Any] | None:
    r = _redis()
    key = f"{_REGISTER_META_PREFIX}{email.lower()}"
    try:
        raw = await r.get(key)
        if not raw:
            return None
        await r.delete(key)
        return json.loads(raw)
    finally:
        await r.aclose()


def generate_simulated_stripe_session_id() -> str:
    return f"sim_{secrets.token_urlsafe(16)}"


_SIGNUP_OTP_PREFIX = "signup_otp:"


async def store_signup_otp(*, email: str, otp: str, ttl_seconds: int) -> None:
    r = _redis()
    try:
        await r.setex(f"{_SIGNUP_OTP_PREFIX}{email.lower()}", ttl_seconds, otp)
    finally:
        await r.aclose()


async def verify_signup_otp(*, email: str, otp: str) -> bool:
    settings = get_settings()
    if not settings.is_production and otp == settings.dev_otp_code:
        return True
    r = _redis()
    try:
        stored = await r.get(f"{_SIGNUP_OTP_PREFIX}{email.lower()}")
        return stored is not None and stored == otp
    finally:
        await r.aclose()


async def clear_signup_otp(*, email: str) -> None:
    r = _redis()
    try:
        await r.delete(f"{_SIGNUP_OTP_PREFIX}{email.lower()}")
    finally:
        await r.aclose()
