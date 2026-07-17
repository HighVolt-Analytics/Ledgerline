"""HTTP client for PayPal REST APIs with bounded retries."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import httpx

from app.config import get_settings
from app.services.payments.paypal_token_service import get_access_token, invalidate_access_token
from app.utils.logger import correlation_id_ctx, get_logger

logger = get_logger(__name__)

DEFAULT_TIMEOUT = httpx.Timeout(30.0, connect=10.0)
RETRYABLE_5XX = frozenset({500, 502, 503, 504})
MAX_5XX_RETRIES = 2


class PaypalApiError(Exception):
    """PayPal API error with optional HTTP metadata."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        error_code: str | None = None,
        details: Any = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code
        self.details = details


def _correlation_header() -> str:
    return correlation_id_ctx.get() or str(uuid.uuid4())


def _safe_error_body(response: httpx.Response) -> dict[str, Any]:
    try:
        data = response.json()
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {}


class PaypalClient:
    """Thin httpx wrapper: auth, correlation, request-id, partner attribution, retries."""

    def __init__(self, *, timeout: httpx.Timeout | None = None) -> None:
        self._timeout = timeout or DEFAULT_TIMEOUT

    def _base_url(self) -> str:
        return get_settings().paypal_api_base_resolved.rstrip("/")

    def _partner_attribution_header(self) -> dict[str, str]:
        bn = get_settings().paypal_partner_attribution_id.strip()
        if not bn:
            return {}
        return {"PayPal-Partner-Attribution-Id": bn}

    async def request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | list[Any] | None = None,
        params: dict[str, Any] | None = None,
        paypal_request_id: str | None = None,
        headers: dict[str, str] | None = None,
        auth_required: bool = True,
    ) -> httpx.Response:
        url = path if path.startswith("http") else f"{self._base_url()}{path}"
        request_id = paypal_request_id or str(uuid.uuid4())
        correlation_id = _correlation_header()

        retried_401 = False
        retry_5xx = 0

        while True:
            req_headers: dict[str, str] = {
                "Accept": "application/json",
                "Content-Type": "application/json",
                "PayPal-Request-Id": request_id,
                "X-Correlation-Id": correlation_id,
            }
            req_headers.update(self._partner_attribution_header())
            if headers:
                req_headers.update(headers)

            if auth_required:
                token = await get_access_token(force_refresh=retried_401)
                req_headers["Authorization"] = f"Bearer {token}"

            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.request(
                    method.upper(),
                    url,
                    json=json,
                    params=params,
                    headers=req_headers,
                )

            if response.status_code == 401 and auth_required and not retried_401:
                logger.warning(
                    "paypal_api_401_reacquire",
                    method=method.upper(),
                    path=path,
                    correlation_id=correlation_id,
                )
                invalidate_access_token()
                retried_401 = True
                continue

            if response.status_code == 429:
                retry_after = response.headers.get("Retry-After", "1")
                try:
                    wait_s = min(float(retry_after), 30.0)
                except ValueError:
                    wait_s = 1.0
                logger.warning(
                    "paypal_api_429_retry",
                    method=method.upper(),
                    path=path,
                    wait_seconds=wait_s,
                    correlation_id=correlation_id,
                )
                await asyncio.sleep(wait_s)
                continue

            if response.status_code in RETRYABLE_5XX and retry_5xx < MAX_5XX_RETRIES:
                retry_5xx += 1
                wait_s = min(2**retry_5xx, 8)
                logger.warning(
                    "paypal_api_5xx_retry",
                    method=method.upper(),
                    path=path,
                    status_code=response.status_code,
                    attempt=retry_5xx,
                    wait_seconds=wait_s,
                    correlation_id=correlation_id,
                )
                await asyncio.sleep(wait_s)
                continue

            return response

    async def request_json(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | list[Any] | None = None,
        params: dict[str, Any] | None = None,
        paypal_request_id: str | None = None,
        headers: dict[str, str] | None = None,
        expected_statuses: frozenset[int] | None = None,
    ) -> dict[str, Any]:
        response = await self.request(
            method,
            path,
            json=json,
            params=params,
            paypal_request_id=paypal_request_id,
            headers=headers,
        )
        ok_statuses = expected_statuses or frozenset({200, 201, 202, 204})
        if response.status_code not in ok_statuses:
            body = _safe_error_body(response)
            name = str(body.get("name") or body.get("error") or "paypal_api_error")
            message = str(
                body.get("message")
                or body.get("error_description")
                or f"PayPal API error ({response.status_code})"
            )
            # Never include Authorization or tokens in logs
            logger.warning(
                "paypal_api_error",
                method=method.upper(),
                path=path,
                status_code=response.status_code,
                error_name=name,
            )
            raise PaypalApiError(
                message,
                status_code=response.status_code,
                error_code=name,
                details=body.get("details"),
            )
        if response.status_code == 204 or not response.content:
            return {}
        data = response.json()
        return data if isinstance(data, dict) else {"data": data}


_default_client: PaypalClient | None = None


def get_paypal_client() -> PaypalClient:
    global _default_client
    if _default_client is None:
        _default_client = PaypalClient()
    return _default_client
