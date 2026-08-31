"""Access-token refresh for the Xero Accounting API."""

from __future__ import annotations

import asyncio
import base64
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
import redis.asyncio as aioredis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.integrations.core.token_crypto import decrypt_secret, encrypt_secret
from app.integrations.xero.oauth import token_url
from app.models.accounting_integration import (
    AccountingIntegration,
    AccountingIntegrationStatus,
    AccountingProvider,
)

REFRESH_MARGIN_SECONDS = 120
LOCK_TTL_SECONDS = 30
LOCK_WAIT_SECONDS = 15
LOCK_POLL_INTERVAL = 0.25
_LOCK_PREFIX = "integrations_xero_refresh:"


def _redis() -> aioredis.Redis:
    return aioredis.from_url(get_settings().redis_url, decode_responses=True)


def _expiring_soon(row: AccountingIntegration) -> bool:
    if not row.expires_at:
        return True
    margin = datetime.now(timezone.utc) + timedelta(seconds=REFRESH_MARGIN_SECONDS)
    expires = row.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    return expires <= margin


_token_expiring_soon = _expiring_soon


async def _acquire_lock(tenant_id: uuid.UUID) -> bool:
    r = _redis()
    try:
        return bool(await r.set(f"{_LOCK_PREFIX}{tenant_id}", "1", nx=True, ex=LOCK_TTL_SECONDS))
    finally:
        await r.aclose()


async def _release_lock(tenant_id: uuid.UUID) -> None:
    r = _redis()
    try:
        await r.delete(f"{_LOCK_PREFIX}{tenant_id}")
    finally:
        await r.aclose()


async def _row(db: AsyncSession, tenant_id: uuid.UUID) -> AccountingIntegration | None:
    return (
        await db.execute(
            select(AccountingIntegration).where(
                AccountingIntegration.tenant_id == tenant_id,
                AccountingIntegration.provider == AccountingProvider.XERO.value,
            )
        )
    ).scalar_one_or_none()


async def _refresh(db: AsyncSession, row: AccountingIntegration) -> None:
    prior_refresh = decrypt_secret(row.refresh_token_encrypted)
    if not prior_refresh:
        row.status = AccountingIntegrationStatus.NEEDS_REAUTH.value
        row.last_error = "Missing refresh token"
        row.last_error_code = "missing_refresh_token"
        await db.flush()
        raise RuntimeError("Xero refresh token missing")

    settings = get_settings()
    auth = base64.b64encode(
        f"{settings.xero_client_id.strip()}:{settings.xero_client_secret.strip()}".encode()
    ).decode("ascii")
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            token_url(),
            headers={
                "Authorization": f"Basic {auth}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={"grant_type": "refresh_token", "refresh_token": prior_refresh},
        )

    if response.status_code >= 400:
        error_code = "refresh_failed"
        message = "Xero token refresh failed"
        try:
            payload: dict[str, Any] = response.json()
            error_code = str(payload.get("error") or error_code)
            message = str(payload.get("error_description") or payload.get("error") or message)
        except Exception:
            pass
        if error_code == "invalid_grant":
            row.status = AccountingIntegrationStatus.NEEDS_REAUTH.value
            row.last_error_code = error_code
            row.last_error = message[:512]
            await db.flush()
            raise RuntimeError("Xero connection requires re-authentication")
        row.status = AccountingIntegrationStatus.ERROR.value
        row.last_error_code = error_code[:64]
        row.last_error = message[:512]
        await db.flush()
        raise RuntimeError(message)

    token_data: dict[str, Any] = response.json()
    access_token = str(token_data.get("access_token") or "")
    if not access_token:
        raise RuntimeError("Xero token refresh returned no access token")

    row.access_token_encrypted = encrypt_secret(access_token)
    rotated = token_data.get("refresh_token")
    if rotated:
        row.refresh_token_encrypted = encrypt_secret(str(rotated))
    expires_in = int(token_data.get("expires_in") or 0)
    row.expires_at = (
        datetime.now(timezone.utc) + timedelta(seconds=expires_in) if expires_in > 0 else None
    )
    row.token_version = int(row.token_version or 0) + 1
    row.last_refresh_at = datetime.now(timezone.utc)
    row.last_error = None
    row.last_error_code = None
    if row.status in {
        AccountingIntegrationStatus.EXPIRED.value,
        AccountingIntegrationStatus.ERROR.value,
    }:
        row.status = AccountingIntegrationStatus.CONNECTED.value
    await db.flush()


async def get_valid_access_token(db: AsyncSession, tenant_id: uuid.UUID) -> str:
    row = await _row(db, tenant_id)
    if row is None or not row.access_token_encrypted:
        raise RuntimeError("Xero is not connected")
    if row.status == AccountingIntegrationStatus.NEEDS_REAUTH.value:
        raise RuntimeError("Xero connection requires re-authentication")
    if not _expiring_soon(row):
        token = decrypt_secret(row.access_token_encrypted)
        if token:
            return token

    acquired = await _acquire_lock(tenant_id)
    try:
        if not _expiring_soon(row):
            token = decrypt_secret(row.access_token_encrypted)
            if token:
                return token
        await _refresh(db, row)
    finally:
        if acquired:
            await _release_lock(tenant_id)

    token = decrypt_secret(row.access_token_encrypted)
    if not token:
        raise RuntimeError("Xero access token unavailable after refresh")
    return token
