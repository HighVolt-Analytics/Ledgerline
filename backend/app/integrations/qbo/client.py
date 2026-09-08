"""QuickBooks Online Accounting API client."""

from __future__ import annotations

import uuid
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.integrations.qbo.tokens import get_valid_access_token

MINOR_VERSION = "75"


class QboApiError(Exception):
    def __init__(self, status_code: int, message: str) -> None:
        self.status_code = status_code
        self.message = message
        super().__init__(message)


def _api_base() -> str:
    settings = get_settings()
    if settings.quickbooks_sandbox_mode:
        return "https://sandbox-quickbooks.api.intuit.com"
    return "https://quickbooks.api.intuit.com"


def message_from_qbo_response(response: httpx.Response, fallback: str) -> str:
    text = (response.text or "").strip()
    if not text:
        return fallback
    try:
        data = response.json()
    except ValueError:
        return text[:400]
    fault = data.get("Fault") if isinstance(data, dict) else None
    if isinstance(fault, dict):
        errors = fault.get("Error") or []
        messages: list[str] = []
        for err in errors:
            if isinstance(err, dict):
                msg = str(err.get("Message") or err.get("Detail") or "").strip()
                if msg:
                    messages.append(msg)
        if messages:
            return "; ".join(dict.fromkeys(messages))[:400]
    return text[:400]


class QboApiClient:
    def __init__(self, *, db: AsyncSession, tenant_id: uuid.UUID, realm_id: str) -> None:
        self._db = db
        self._tenant_id = tenant_id
        self._realm_id = realm_id

    async def _headers(self) -> dict[str, str]:
        token = await get_valid_access_token(self._db, self._tenant_id)
        return {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        }

    def _company_url(self, path: str) -> str:
        base = _api_base().rstrip("/")
        return f"{base}/v3/company/{self._realm_id}/{path.lstrip('/')}"

    async def query(self, statement: str) -> dict[str, Any]:
        url = self._company_url("query")
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.get(
                url,
                headers=await self._headers(),
                params={"query": statement, "minorversion": MINOR_VERSION},
            )
        if response.status_code >= 400:
            raise QboApiError(
                response.status_code,
                message_from_qbo_response(response, "QuickBooks query failed"),
            )
        payload = response.json()
        return payload if isinstance(payload, dict) else {}

    async def post_entity(self, entity: str, body: dict[str, Any]) -> dict[str, Any]:
        headers = await self._headers()
        headers["Content-Type"] = "application/json"
        url = f"{self._company_url(entity)}?minorversion={MINOR_VERSION}"
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(url, headers=headers, json=body)
        if response.status_code >= 400:
            raise QboApiError(
                response.status_code,
                message_from_qbo_response(response, "QuickBooks POST failed"),
            )
        if not response.content:
            return {}
        payload = response.json()
        return payload if isinstance(payload, dict) else {}
