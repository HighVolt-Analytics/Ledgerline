"""Xero Accounting API HTTP client for the new Integrations layer."""

from __future__ import annotations

import uuid
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.integrations.xero.tokens import get_valid_access_token


class XeroApiError(Exception):
    def __init__(
        self,
        status_code: int,
        message: str,
        *,
        error_code: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.status_code = status_code
        self.message = message
        self.error_code = error_code or f"xero_http_{status_code}"
        self.details = details
        super().__init__(message)


def message_from_xero_response(response: httpx.Response, fallback: str) -> str:
    """Prefer Xero ValidationErrors over a generic PUT/POST failed string."""
    text = (response.text or "").strip()
    if not text:
        return fallback
    try:
        data = response.json()
    except ValueError:
        return text[:400]
    if not isinstance(data, dict):
        return text[:400]
    messages: list[str] = []
    for element in data.get("Elements") or []:
        if not isinstance(element, dict):
            continue
        for err in element.get("ValidationErrors") or []:
            if isinstance(err, dict):
                msg = str(err.get("Message") or "").strip()
                if msg:
                    messages.append(msg)
    if messages:
        return "; ".join(dict.fromkeys(messages))
    top = str(data.get("Message") or "").strip()
    return (top or text)[:400]


def accounting_headers(*, access_token: str, xero_tenant_id: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {access_token}",
        "xero-tenant-id": xero_tenant_id,
        "Accept": "application/json",
    }


class XeroApiClient:
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

    async def _headers(self) -> dict[str, str]:
        token = await get_valid_access_token(self._db, self._tenant_id)
        return accounting_headers(access_token=token, xero_tenant_id=self._xero_tenant_id)

    def _url(self, path: str) -> str:
        return get_settings().xero_accounting_api_path(path)

    async def get_json(self, path: str, *, params: dict[str, Any] | None = None) -> Any:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                self._url(path),
                headers=await self._headers(),
                params=params,
            )
        if response.status_code >= 400:
            raise XeroApiError(
                response.status_code,
                message_from_xero_response(response, "Xero GET failed"),
            )
        return response.json()

    async def post_json(self, path: str, *, json_body: dict[str, Any]) -> Any:
        headers = await self._headers()
        headers["Content-Type"] = "application/json"
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(self._url(path), headers=headers, json=json_body)
        if response.status_code >= 400:
            raise XeroApiError(
                response.status_code,
                message_from_xero_response(response, "Xero POST failed"),
            )
        if not response.content:
            return {}
        return response.json()

    async def put_json(self, path: str, *, json_body: dict[str, Any]) -> Any:
        headers = await self._headers()
        headers["Content-Type"] = "application/json"
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.put(self._url(path), headers=headers, json=json_body)
        if response.status_code >= 400:
            raise XeroApiError(
                response.status_code,
                message_from_xero_response(response, "Xero PUT failed"),
            )
        if not response.content:
            return {}
        return response.json()

    async def get_currencies(self) -> list[dict[str, Any]]:
        payload = await self.get_json("Currencies")
        currencies = payload.get("Currencies") if isinstance(payload, dict) else None
        if not isinstance(currencies, list):
            raise XeroApiError(
                502,
                "Xero Currencies response missing Currencies array",
                error_code="currencies_missing",
            )
        return [c for c in currencies if isinstance(c, dict)]

    async def put_bytes(
        self,
        path: str,
        *,
        content: bytes,
        content_type: str,
        params: dict[str, Any] | None = None,
    ) -> httpx.Response:
        headers = await self._headers()
        headers["Content-Type"] = content_type
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.put(
                self._url(path),
                headers=headers,
                params=params,
                content=content,
            )
        if response.status_code >= 400:
            raise XeroApiError(
                response.status_code,
                message_from_xero_response(response, "Xero PUT failed"),
            )
        return response
