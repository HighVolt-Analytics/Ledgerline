"""Tenants available to the signed-in user."""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthContext, get_auth_context, get_db
from app.models.tenant import Tenant
from app.schemas.common import ApiEnvelope
from app.schemas.tenant import CreateTenantRequest, TenantResponse
from app.services.membership_service import ensure_membership, list_user_tenants

router = APIRouter(prefix="/tenants", tags=["tenants"])


def _to_response(tenant: Tenant, *, current_tenant_id: uuid.UUID) -> TenantResponse:
    return TenantResponse(
        id=tenant.id,
        name=tenant.name,
        slug=tenant.slug,
        currency="AUD",
        is_current=tenant.id == current_tenant_id,
    )


@router.get("", response_model=ApiEnvelope[list[TenantResponse]])
async def list_my_tenants(
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[list[TenantResponse]]:
    tenants = await list_user_tenants(
        db, user_id=ctx.user_id, current_tenant_id=ctx.tenant_id
    )
    return ApiEnvelope(
        data=[_to_response(t, current_tenant_id=ctx.tenant_id) for t in tenants]
    )


@router.post("", response_model=ApiEnvelope[TenantResponse], status_code=201)
async def create_tenant(
    body: CreateTenantRequest,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[TenantResponse]:
    if ctx.user_id is None:
        raise HTTPException(401, "Sign in to create a tenant")

    slug = body.slug.strip().lower()
    taken = (
        await db.execute(select(Tenant).where(Tenant.slug == slug))
    ).scalar_one_or_none()
    if taken:
        raise HTTPException(409, f"Tenant slug '{slug}' is already taken")

    tenant = Tenant(name=body.name.strip(), slug=slug)
    db.add(tenant)
    await db.flush()
    await ensure_membership(db, user_id=ctx.user_id, tenant_id=tenant.id, role="admin")

    return ApiEnvelope(
        data=_to_response(tenant, current_tenant_id=ctx.tenant_id),
    )
