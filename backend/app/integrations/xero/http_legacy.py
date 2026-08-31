"""Centralized httpx client for Xero API with retries and token refresh."""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.integrations.xero.tokens import get_valid_access_token
from app.utils.logger import correlation_id_ctx, get_logger

logger = get_logger(__name__)

DEFAULT_TIMEOUT = 30.0
MAX_NETWORK_RETRIES = 3
MAX_429_RETRIES = 3
MAX_429_WAIT_SECONDS = 60.0
RETRYABLE_STATUS = {500, 502, 503, 504}


@dataclass
class XeroApiError(Exception):
    status_code: int
    error_code: str
    message: str
    details: dict[str, Any] | None = None

    def __str__(self) -> str:
        return self.message


def _correlation_id() -> str | None:
    return correlation_id_ctx.get()


def _resolve_url(path: str, *, base_url: str | None = None) -> str:
    if base_url:
        return f"{base_url.rstrip('/')}/{path.lstrip('/')}"
    settings = get_settings()
    if path.startswith("http://") or path.startswith("https://"):
        return path
    return settings.xero_accounting_api_path(path)


def _parse_error_response(status_code: int, body: str) -> XeroApiError:
    error_code = f"xero_http_{status_code}"
    message = body[:400] if body else f"Xero API error ({status_code})"
    details: dict[str, Any] | None = None
    try:
        payload = httpx.Response(status_code=status_code, content=body).json()
        if isinstance(payload, dict):
            details = payload
            elements = payload.get("Elements")
            if isinstance(elements, list) and elements:
                validation = elements[0].get("ValidationErrors")
                if isinstance(validation, list) and validation:
                    message = str(validation[0].get("Message") or message)
            message = str(
                payload.get("Detail")
                or payload.get("Message")
                or payload.get("error_description")
                or payload.get("error")
                or message
            )
            error_code = str(payload.get("Type") or payload.get("error") or error_code)
    except Exception:
        pass
    return XeroApiError(
        status_code=status_code,
        error_code=error_code[:64],
        message=message[:512],
        details=details,
    )


class XeroClient:
    def __init__(
        self,
        *,
        db: AsyncSession,
        tenant_id: uuid.UUID,
        xero_tenant_id: str,
    ) -> None:
        self._db = db
        self._tenant_id = tenant_id
        self._xero_tenant_id = xero_tenant_id

    async def request(
        self,
        method: str,
        path: str,
        *,
        base_url: str | None = None,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | list[Any] | None = None,
        refreshed: bool = False,
    ) -> httpx.Response:
        access_token = await get_valid_access_token(self._db, self._tenant_id)
        url = _resolve_url(path, base_url=base_url)
        headers = {
            "Authorization": f"Bearer {access_token}",
            "xero-tenant-id": self._xero_tenant_id,
            "Accept": "application/json",
        }
        cid = _correlation_id()
        if cid:
            headers["X-Correlation-Id"] = cid
        if json_body is not None:
            headers["Content-Type"] = "application/json"

        attempt = 0
        rate_limit_attempt = 0
        while True:
            attempt += 1
            try:
                async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
                    response = await client.request(
                        method,
                        url,
                        headers=headers,
                        params=params,
                        json=json_body,
                    )
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                if attempt >= MAX_NETWORK_RETRIES:
                    logger.warning(
                        "xero_api_network_error",
                        method=method,
                        path=path,
                        correlation_id=cid,
                        error=str(exc),
                    )
                    raise XeroApiError(
                        status_code=0,
                        error_code="xero_network_error",
                        message="Xero API network error",
                    ) from exc
                await asyncio.sleep(min(2 ** (attempt - 1), 4))
                continue

            if response.status_code == 401 and not refreshed:
                logger.info(
                    "xero_api_token_refresh_retry",
                    method=method,
                    path=path,
                    correlation_id=cid,
                )
                await get_valid_access_token(self._db, self._tenant_id, force_refresh=True)
                return await self.request(
                    method,
                    path,
                    base_url=base_url,
                    params=params,
                    json_body=json_body,
                    refreshed=True,
                )

            if response.status_code == 429:
                rate_limit_attempt += 1
                if rate_limit_attempt > MAX_429_RETRIES:
                    raise _parse_error_response(response.status_code, response.text)
                retry_after = response.headers.get("Retry-After")
                try:
                    wait_seconds = float(retry_after) if retry_after else 2.0
                except ValueError:
                    wait_seconds = 2.0
                wait_seconds = min(max(wait_seconds, 1.0), MAX_429_WAIT_SECONDS)
                logger.info(
                    "xero_api_rate_limited",
                    method=method,
                    path=path,
                    correlation_id=cid,
                    wait_seconds=wait_seconds,
                )
                await asyncio.sleep(wait_seconds)
                continue

            if response.status_code in RETRYABLE_STATUS and attempt < MAX_NETWORK_RETRIES:
                await asyncio.sleep(min(2 ** (attempt - 1), 4))
                continue

            if response.status_code >= 400:
                raise _parse_error_response(response.status_code, response.text)

            return response

    async def get_json(self, path: str, *, params: dict[str, Any] | None = None) -> Any:
        response = await self.request("GET", path, params=params)
        return response.json()

    async def get_currencies(self) -> list[dict[str, Any]]:
        """Fetch organisation currencies from the Xero Currencies endpoint.

        Organisation payloads often omit ``Currencies``; never treat a missing
        nested array as an empty successful sync.
        """
        payload = await self.get_json("Currencies")
        if not isinstance(payload, dict):
            raise XeroApiError(
                status_code=502,
                error_code="invalid_currencies_response",
                message="Xero Currencies response was not a JSON object",
            )
        currencies = payload.get("Currencies")
        if currencies is None:
            raise XeroApiError(
                status_code=502,
                error_code="currencies_missing",
                message="Xero Currencies response did not include a Currencies array",
            )
        if not isinstance(currencies, list):
            raise XeroApiError(
                status_code=502,
                error_code="invalid_currencies_response",
                message="Xero Currencies response Currencies field was not a list",
            )
        return [c for c in currencies if isinstance(c, dict)]

    async def post_json(
        self,
        path: str,
        *,
        json_body: dict[str, Any] | list[Any],
        params: dict[str, Any] | None = None,
    ) -> Any:
        response = await self.request("POST", path, params=params, json_body=json_body)
        if not response.content:
            return {}
        return response.json()

    async def put_bytes(
        self,
        path: str,
        *,
        content: bytes,
        content_type: str,
        params: dict[str, Any] | None = None,
        refreshed: bool = False,
    ) -> httpx.Response:
        """Binary PUT (e.g. invoice PDF attachments). Never logs content."""
        access_token = await get_valid_access_token(self._db, self._tenant_id)
        url = _resolve_url(path)
        headers = {
            "Authorization": f"Bearer {access_token}",
            "xero-tenant-id": self._xero_tenant_id,
            "Accept": "application/json",
            "Content-Type": content_type,
        }
        cid = _correlation_id()
        if cid:
            headers["X-Correlation-Id"] = cid

        attempt = 0
        rate_limit_attempt = 0
        while True:
            attempt += 1
            try:
                async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
                    response = await client.request(
                        "PUT",
                        url,
                        headers=headers,
                        params=params,
                        content=content,
                    )
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                if attempt >= MAX_NETWORK_RETRIES:
                    raise XeroApiError(
                        status_code=0,
                        error_code="xero_network_error",
                        message="Xero API network error",
                    ) from exc
                await asyncio.sleep(min(2 ** (attempt - 1), 4))
                continue

            if response.status_code == 401 and not refreshed:
                await get_valid_access_token(self._db, self._tenant_id, force_refresh=True)
                return await self.put_bytes(
                    path,
                    content=content,
                    content_type=content_type,
                    params=params,
                    refreshed=True,
                )

            if response.status_code == 429:
                rate_limit_attempt += 1
                if rate_limit_attempt > MAX_429_RETRIES:
                    raise _parse_error_response(response.status_code, response.text)
                retry_after = response.headers.get("Retry-After")
                try:
                    wait_seconds = float(retry_after) if retry_after else 2.0
                except ValueError:
                    wait_seconds = 2.0
                wait_seconds = min(max(wait_seconds, 1.0), MAX_429_WAIT_SECONDS)
                await asyncio.sleep(wait_seconds)
                continue

            if response.status_code in RETRYABLE_STATUS and attempt < MAX_NETWORK_RETRIES:
                await asyncio.sleep(min(2 ** (attempt - 1), 4))
                continue

            if response.status_code >= 400:
                raise _parse_error_response(response.status_code, response.text)
            return response
