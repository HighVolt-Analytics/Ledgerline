"""Client country hint from request IP (for regional pricing display)."""

from __future__ import annotations

import httpx
from fastapi import APIRouter, Request

from app.schemas.common import ApiEnvelope

router = APIRouter(prefix="/geo", tags=["geo"])


def _client_ip(request: Request) -> str | None:
    forwarded = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
    if forwarded:
        return forwarded
    if request.client:
        return request.client.host
    return None


@router.get("/country", response_model=ApiEnvelope[dict[str, str | None]])
async def get_geo_country(request: Request) -> ApiEnvelope[dict[str, str | None]]:
    ip = _client_ip(request)
    if not ip or ip in {"127.0.0.1", "::1"}:
        return ApiEnvelope(data={"country_code": None})

    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            response = await client.get(
                f"http://ip-api.com/json/{ip}",
                params={"fields": "countryCode,status"},
            )
            if response.status_code == 200:
                payload = response.json()
                if payload.get("status") == "success" and payload.get("countryCode"):
                    code = str(payload["countryCode"]).strip().upper()
                    return ApiEnvelope(data={"country_code": code})
    except Exception:
        pass

    return ApiEnvelope(data={"country_code": None})
