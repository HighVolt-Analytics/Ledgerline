"""PayPal OAuth client-credentials token cache."""

from __future__ import annotations

import asyncio
import base64
import time
from typing import Any

import httpx

from app.config import get_settings
from app.utils.logger import get_logger

logger = get_logger(__name__)

_TOKEN_MARGIN_SECONDS = 60
_lock = asyncio.Lock()
_cached_token: str | None = None
_cached_expires_at: float = 0.0


class PaypalTokenError(Exception):
    """PayPal token acquisition failure."""


def _clear_token_cache() -> None:
    global _cached_token, _cached_expires_at
    _cached_token = None
    _cached_expires_at = 0.0


def invalidate_access_token() -> None:
    """Drop cached token (e.g. after a 401). Never logs the token."""
    _clear_token_cache()


async def get_access_token(*, force_refresh: bool = False) -> str:
    """Return a cached client-credentials access token, refreshing near expiry."""
    global _cached_token, _cached_expires_at

    settings = get_settings()
    if not settings.paypal_configured:
        raise PaypalTokenError("PayPal is not configured")

    now = time.monotonic()
    if (
        not force_refresh
        and _cached_token
        and now < (_cached_expires_at - _TOKEN_MARGIN_SECONDS)
    ):
        return _cached_token

    async with _lock:
        now = time.monotonic()
        if (
            not force_refresh
            and _cached_token
            and now < (_cached_expires_at - _TOKEN_MARGIN_SECONDS)
        ):
            return _cached_token

        token, expires_in = await _fetch_token()
        _cached_token = token
        _cached_expires_at = time.monotonic() + max(int(expires_in), 1)
        logger.info("paypal_access_token_acquired", expires_in=int(expires_in))
        return token


async def _fetch_token() -> tuple[str, int]:
    settings = get_settings()
    client_id = settings.paypal_client_id.strip()
    client_secret = settings.paypal_client_secret.strip()
    basic = base64.b64encode(f"{client_id}:{client_secret}".encode("utf-8")).decode("ascii")
    url = f"{settings.paypal_api_base_resolved}/v1/oauth2/token"

    async with httpx.AsyncClient(timeout=httpx.Timeout(20.0)) as client:
        response = await client.post(
            url,
            headers={
                "Authorization": f"Basic {basic}",
                "Accept": "application/json",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={"grant_type": "client_credentials"},
        )

    if response.status_code >= 400:
        logger.warning(
            "paypal_token_request_failed",
            status_code=response.status_code,
        )
        raise PaypalTokenError("Failed to acquire PayPal access token")

    payload: dict[str, Any] = response.json()
    token = str(payload.get("access_token") or "").strip()
    if not token:
        raise PaypalTokenError("PayPal token response missing access_token")
    expires_in = int(payload.get("expires_in") or 300)
    return token, expires_in
