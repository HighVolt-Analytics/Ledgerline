"""Resolve tenant from HTTP request."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

from sqlalchemy import select

from app.tenant_ids import parse_tenant_id

if TYPE_CHECKING:
    from starlette.requests import Request
    from sqlalchemy.ext.asyncio import AsyncSession


class TenantResolutionSource(str, Enum):
    JWT = "jwt"
    HEADER_SLUG = "header_slug"
    QUERY_TENANT = "query_tenant"
    NONE = "none"


@dataclass(frozen=True)
class TenantResolution:
    tenant_id: uuid.UUID | None
    tenant_slug: str | None
    source: TenantResolutionSource


_SKIP_DEFAULT_PATHS = (
    "/api/auth/login",
    "/api/auth/verify-otp",
    "/api/auth/resend-otp",
    "/api/auth/select-tenant",
    "/api/auth/forgot-password",
    "/api/auth/reset-password",
    "/health",
    "/connect-mailbox",
)


class TenantResolutionService:
    @staticmethod
    def should_skip_default(path: str) -> bool:
        p = path.rstrip("/") or "/"
        for prefix in _SKIP_DEFAULT_PATHS:
            if p == prefix or p.startswith(prefix + "/"):
                return True
        if "/webhook" in p or p.startswith("/auth/whatsapp") or p.startswith("/auth/meta"):
            return True
        return False

    @staticmethod
    async def resolve_slug(session: AsyncSession, slug: str) -> uuid.UUID | None:
        from app.models.tenant import Tenant

        row = (
            await session.execute(select(Tenant.id).where(Tenant.slug == slug.lower()))
        ).scalar_one_or_none()
        return row

    @staticmethod
    async def resolve_from_request(
        request: Request,
        session: AsyncSession,
        *,
        jwt_tenant_id: uuid.UUID | None = None,
        jwt_tenant_slug: str | None = None,
    ) -> TenantResolution:
        if jwt_tenant_id is not None:
            return TenantResolution(
                tenant_id=jwt_tenant_id,
                tenant_slug=jwt_tenant_slug,
                source=TenantResolutionSource.JWT,
            )

        slug_hdr = (request.headers.get("X-Tenant-Slug") or "").strip().lower()
        if slug_hdr:
            tid = await TenantResolutionService.resolve_slug(session, slug_hdr)
            return TenantResolution(tid, slug_hdr, TenantResolutionSource.HEADER_SLUG)

        slug_q = (request.query_params.get("tenant") or "").strip().lower()
        if slug_q:
            tid = await TenantResolutionService.resolve_slug(session, slug_q)
            return TenantResolution(tid, slug_q, TenantResolutionSource.QUERY_TENANT)

        return TenantResolution(None, None, TenantResolutionSource.NONE)

    @staticmethod
    def validate_header_scope(
        resolved_tenant_id: uuid.UUID | None,
        x_tenant_id_hdr: str | None,
    ) -> str | None:
        if resolved_tenant_id is None or not x_tenant_id_hdr:
            return None
        hdr_tid = parse_tenant_id(x_tenant_id_hdr)
        if hdr_tid is None:
            return "X-Tenant-Id must be a UUID"
        if hdr_tid != resolved_tenant_id:
            return "X-Tenant-Id does not match authenticated tenant scope"
        return None
