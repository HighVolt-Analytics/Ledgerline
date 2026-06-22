"""Platform super-admin APIs for cross-tenant management."""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthContext, get_db, require_super_admin
from app.models.tenant import Tenant
from app.schemas.common import ApiEnvelope
from app.schemas.platform import (
    CreatePlatformTenantRequest,
    PlatformTenantDetail,
    PlatformTenantSummary,
    UpdatePlatformTenantRequest,
)
from app.services.platform_service import (
    create_client_tenant,
    get_client_tenant,
    list_client_tenants,
    update_client_tenant,
)

router = APIRouter(prefix="/platform", tags=["platform"])


@router.get("/tenants", response_model=ApiEnvelope[list[PlatformTenantSummary]])
async def list_tenants(
    db: AsyncSession = Depends(get_db),
    _ctx: AuthContext = Depends(require_super_admin),
) -> ApiEnvelope[list[PlatformTenantSummary]]:
    tenants = await list_client_tenants(db)
    return ApiEnvelope(data=tenants)


@router.post("/tenants", response_model=ApiEnvelope[PlatformTenantDetail], status_code=201)
async def create_tenant(
    body: CreatePlatformTenantRequest,
    db: AsyncSession = Depends(get_db),
    _ctx: AuthContext = Depends(require_super_admin),
) -> ApiEnvelope[PlatformTenantDetail]:
    slug = body.slug.strip().lower()
    taken = (
        await db.execute(select(Tenant).where(Tenant.slug == slug))
    ).scalar_one_or_none()
    if taken:
        raise HTTPException(409, f"Tenant slug '{slug}' is already taken")

    tenant = await create_client_tenant(db, body)
    return ApiEnvelope(data=tenant)


@router.get("/tenants/{tenant_id}", response_model=ApiEnvelope[PlatformTenantDetail])
async def get_tenant(
    tenant_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _ctx: AuthContext = Depends(require_super_admin),
) -> ApiEnvelope[PlatformTenantDetail]:
    tenant = await get_client_tenant(db, tenant_id=tenant_id)
    if not tenant:
        raise HTTPException(404, "Tenant not found")
    return ApiEnvelope(data=tenant)


@router.patch("/tenants/{tenant_id}", response_model=ApiEnvelope[PlatformTenantDetail])
async def update_tenant(
    tenant_id: uuid.UUID,
    body: UpdatePlatformTenantRequest,
    db: AsyncSession = Depends(get_db),
    _ctx: AuthContext = Depends(require_super_admin),
) -> ApiEnvelope[PlatformTenantDetail]:
    tenant = await update_client_tenant(db, tenant_id=tenant_id, body=body)
    if not tenant:
        raise HTTPException(404, "Tenant not found")
    return ApiEnvelope(data=tenant)
