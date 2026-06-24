"""Tenants available to the signed-in user."""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthContext, get_auth_context, get_db, require_admin, require_super_admin
from app.models.tenant import Tenant
from app.schemas.common import ApiEnvelope
from app.schemas.institution_settings import (
    InstitutionSettingsResponse,
    UpdateInstitutionSettingsRequest,
)
from app.schemas.onboarding import OnboardingStatusResponse, UpdateOnboardingRequest
from app.schemas.tenant import CreateTenantRequest, TenantResponse
from app.services.membership_service import ensure_membership, list_user_tenants
from app.tenant_settings import (
    default_institution_settings,
    institution_settings_view,
    merge_institution_settings,
    merge_onboarding_settings,
    tenant_industry,
    tenant_onboarding_completed,
)

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
    ctx: AuthContext = Depends(require_super_admin),
) -> ApiEnvelope[TenantResponse]:
    if ctx.user_id is None:
        raise HTTPException(401, "Sign in to create a tenant")

    slug = body.slug.strip().lower()
    taken = (
        await db.execute(select(Tenant).where(Tenant.slug == slug))
    ).scalar_one_or_none()
    if taken:
        raise HTTPException(409, f"Tenant slug '{slug}' is already taken")

    tenant = Tenant(name=body.name.strip(), slug=slug, settings_json=default_institution_settings())
    db.add(tenant)
    await db.flush()
    await ensure_membership(db, user_id=ctx.user_id, tenant_id=tenant.id, role="admin")

    return ApiEnvelope(
        data=_to_response(tenant, current_tenant_id=ctx.tenant_id),
    )


@router.get("/current/institution", response_model=ApiEnvelope[InstitutionSettingsResponse])
async def get_institution_settings(
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[InstitutionSettingsResponse]:
    tenant = await db.get(Tenant, ctx.tenant_id)
    if not tenant:
        raise HTTPException(404, "Tenant not found")
    view = institution_settings_view(tenant)
    return ApiEnvelope(data=InstitutionSettingsResponse(**view))


def _onboarding_steps(*, completed: bool, has_industry: bool) -> list[str]:
    steps = ["profile"]
    if not has_industry:
        steps.append("industry")
    if not completed:
        steps.append("complete")
    return steps


@router.get("/current/onboarding", response_model=ApiEnvelope[OnboardingStatusResponse])
async def get_onboarding_status(
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[OnboardingStatusResponse]:
    tenant = await db.get(Tenant, ctx.tenant_id)
    if not tenant:
        raise HTTPException(404, "Tenant not found")

    completed = tenant_onboarding_completed(tenant)
    industry = tenant_industry(tenant)
    view = institution_settings_view(tenant)
    return ApiEnvelope(
        data=OnboardingStatusResponse(
            completed=completed,
            country=view["country"],
            industry=industry,
            steps=_onboarding_steps(completed=completed, has_industry=industry is not None),
        )
    )


@router.patch("/current/onboarding", response_model=ApiEnvelope[OnboardingStatusResponse])
async def update_onboarding(
    body: UpdateOnboardingRequest,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(require_admin),
) -> ApiEnvelope[OnboardingStatusResponse]:
    if ctx.is_support_session:
        raise HTTPException(403, "Support sessions cannot complete tenant onboarding")

    tenant = await db.get(Tenant, ctx.tenant_id)
    if not tenant:
        raise HTTPException(404, "Tenant not found")

    if body.country is not None:
        tenant.settings_json = merge_institution_settings(tenant.settings_json, country=body.country)
    tenant.settings_json = merge_onboarding_settings(
        tenant.settings_json,
        industry=body.industry,
        onboarding_completed=True if body.complete else None,
    )
    await db.commit()
    await db.refresh(tenant)

    completed = tenant_onboarding_completed(tenant)
    industry = tenant_industry(tenant)
    view = institution_settings_view(tenant)
    return ApiEnvelope(
        data=OnboardingStatusResponse(
            completed=completed,
            country=view["country"],
            industry=industry,
            steps=_onboarding_steps(completed=completed, has_industry=industry is not None),
        )
    )


@router.patch("/current/institution", response_model=ApiEnvelope[InstitutionSettingsResponse])
async def update_institution_settings(
    body: UpdateInstitutionSettingsRequest,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(require_admin),
) -> ApiEnvelope[InstitutionSettingsResponse]:
    tenant = await db.get(Tenant, ctx.tenant_id)
    if not tenant:
        raise HTTPException(404, "Tenant not found")
    if body.country is None and body.timezone is None and body.locale is None:
        raise HTTPException(400, "No settings to update")

    tenant.settings_json = merge_institution_settings(
        tenant.settings_json,
        country=body.country,
        timezone=body.timezone,
        locale=body.locale,
    )
    await db.commit()
    await db.refresh(tenant)
    view = institution_settings_view(tenant)
    return ApiEnvelope(data=InstitutionSettingsResponse(**view))
