"""Tenants available to the signed-in user."""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthContext, get_auth_context, get_db, require_admin, require_super_admin
from app.models.invoice import Invoice
from app.models.tenant import Tenant
from app.schemas.common import ApiEnvelope
from app.schemas.institution_settings import (
    InstitutionSettingsResponse,
    UpdateInstitutionSettingsRequest,
)
from app.schemas.onboarding import OnboardingStatusResponse, UpdateOnboardingRequest
from app.schemas.org_ai_brief import OrgAiBriefResponse, UpdateOrgAiBriefRequest
from app.schemas.tenant import CreateTenantRequest, TenantResponse
from app.services.auth.membership_service import ensure_membership, list_user_tenants
from app.services.rule_book.rule_book_config_repository import ensure_default_config
from app.services.tenant.org_ai_brief_service import (
    load_org_ai_brief,
    save_org_ai_brief,
    sync_org_legal_name_on_tenant_rename,
)
from app.schemas.chart_of_accounts import ChartOfAccountsResponse, UpdateChartOfAccountsRequest
from app.services.master_data.chart_of_accounts_service import load_chart_of_accounts, save_chart_of_accounts
from app.schemas.setup_checklist import SetupChecklistStateResponse
from app.services.tenant.tenant_setup_checklist_service import build_setup_checklist_state
from app.jurisdiction.packs import jurisdiction_api_view, tenant_jurisdiction
from app.tenant_settings import (
    DEFAULT_CURRENCY,
    default_institution_settings,
    institution_settings_view,
    merge_institution_settings,
    merge_onboarding_settings,
    set_setup_checklist_complete,
    tenant_currency,
    tenant_industry,
    tenant_labor_rate_per_hour,
    tenant_onboarding_completed,
    UnsupportedCurrencyError,
)

router = APIRouter(prefix="/tenants", tags=["tenants"])


def _to_response(tenant: Tenant, *, current_tenant_id: uuid.UUID) -> TenantResponse:
    return TenantResponse(
        id=tenant.id,
        name=tenant.name,
        slug=tenant.slug,
        currency=tenant_currency(tenant),
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

    tenant = Tenant(
        name=body.name.strip(),
        slug=slug,
        currency=DEFAULT_CURRENCY,
        settings_json=default_institution_settings(),
    )
    db.add(tenant)
    await db.flush()
    await ensure_membership(db, user_id=ctx.user_id, tenant_id=tenant.id, role="admin")
    await ensure_default_config(db, tenant.id)

    return ApiEnvelope(
        data=_to_response(tenant, current_tenant_id=ctx.tenant_id),
    )


def _institution_response(tenant: Tenant, *, has_ledger_activity: bool = False) -> InstitutionSettingsResponse:
    view = institution_settings_view(tenant)
    juris = jurisdiction_api_view(tenant_jurisdiction(tenant))
    return InstitutionSettingsResponse(
        name=tenant.name,
        **view,
        **juris,
        labor_rate_per_hour=tenant_labor_rate_per_hour(tenant),
        has_ledger_activity=has_ledger_activity,
    )


async def _tenant_has_ledger_activity(db: AsyncSession, tenant_id: uuid.UUID) -> bool:
    count = (
        await db.execute(
            select(func.count()).select_from(Invoice).where(Invoice.tenant_id == tenant_id)
        )
    ).scalar_one()
    return int(count or 0) > 0


@router.get("/current/institution", response_model=ApiEnvelope[InstitutionSettingsResponse])
async def get_institution_settings(
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[InstitutionSettingsResponse]:
    tenant = await db.get(Tenant, ctx.tenant_id)
    if not tenant:
        raise HTTPException(404, "Tenant not found")
    has_activity = await _tenant_has_ledger_activity(db, tenant.id)
    return ApiEnvelope(data=_institution_response(tenant, has_ledger_activity=has_activity))


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


@router.get("/current/org-ai-brief", response_model=ApiEnvelope[OrgAiBriefResponse])
async def get_org_ai_brief(
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[OrgAiBriefResponse]:
    """Tenant org context for AI classification (stored in rule book config JSON)."""
    return ApiEnvelope(data=await load_org_ai_brief(db, ctx.tenant_id))


@router.patch("/current/org-ai-brief", response_model=ApiEnvelope[OrgAiBriefResponse])
async def update_org_ai_brief(
    body: UpdateOrgAiBriefRequest,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(require_admin),
) -> ApiEnvelope[OrgAiBriefResponse]:
    if ctx.is_support_session:
        raise HTTPException(403, "Support sessions cannot edit org AI brief")
    saved = await save_org_ai_brief(
        db,
        ctx.tenant_id,
        body,
        updated_by_user_id=ctx.user_id,
    )
    return ApiEnvelope(data=saved)


@router.get("/current/chart-of-accounts", response_model=ApiEnvelope[ChartOfAccountsResponse])
async def get_chart_of_accounts(
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[ChartOfAccountsResponse]:
    """Tenant chart of accounts (stored in rule book config JSON with RLS)."""
    return ApiEnvelope(data=await load_chart_of_accounts(db, ctx.tenant_id))


@router.patch("/current/chart-of-accounts", response_model=ApiEnvelope[ChartOfAccountsResponse])
async def update_chart_of_accounts(
    body: UpdateChartOfAccountsRequest,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(require_admin),
) -> ApiEnvelope[ChartOfAccountsResponse]:
    if ctx.is_support_session:
        raise HTTPException(403, "Support sessions cannot edit chart of accounts")
    saved = await save_chart_of_accounts(
        db,
        ctx.tenant_id,
        body,
        updated_by_user_id=ctx.user_id,
    )
    return ApiEnvelope(data=saved)


@router.patch("/current/institution", response_model=ApiEnvelope[InstitutionSettingsResponse])
async def update_institution_settings(
    body: UpdateInstitutionSettingsRequest,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(require_admin),
) -> ApiEnvelope[InstitutionSettingsResponse]:
    tenant = await db.get(Tenant, ctx.tenant_id)
    if not tenant:
        raise HTTPException(404, "Tenant not found")
    if (
        body.name is None
        and body.country is None
        and body.currency is None
        and body.timezone is None
        and body.locale is None
        and body.custom_bundle_field_key is None
        and body.labor_rate_per_hour is None
    ):
        raise HTTPException(400, "No settings to update")

    if body.name is not None:
        old_name = tenant.name
        tenant.name = body.name.strip()
        await sync_org_legal_name_on_tenant_rename(
            db,
            ctx.tenant_id,
            old_name=old_name,
            new_name=tenant.name,
            updated_by_user_id=ctx.user_id,
        )

    try:
        tenant.settings_json = merge_institution_settings(
            tenant.settings_json,
            country=body.country,
            timezone=body.timezone,
            locale=body.locale,
            custom_bundle_field_key=body.custom_bundle_field_key,
            currency=body.currency,
            labor_rate_per_hour=body.labor_rate_per_hour,
        )
        if body.currency is not None and str(body.currency).strip():
            from app.services.shared.currency_catalog_service import ensure_currency_row

            tenant.currency = await ensure_currency_row(db, body.currency)
    except UnsupportedCurrencyError as exc:
        raise HTTPException(400, str(exc)) from exc

    await db.commit()
    await db.refresh(tenant)
    has_activity = await _tenant_has_ledger_activity(db, tenant.id)
    return ApiEnvelope(data=_institution_response(tenant, has_ledger_activity=has_activity))


@router.get("/current/setup-checklist", response_model=ApiEnvelope[SetupChecklistStateResponse])
async def get_setup_checklist(
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[SetupChecklistStateResponse]:
    tenant = await db.get(Tenant, ctx.tenant_id)
    if not tenant:
        raise HTTPException(404, "Tenant not found")
    state = await build_setup_checklist_state(
        db,
        tenant=tenant,
        user_role=ctx.role,
        is_support_session=ctx.is_support_session,
    )
    return ApiEnvelope(data=state)


@router.post("/current/setup-checklist/complete", response_model=ApiEnvelope[SetupChecklistStateResponse])
async def complete_setup_checklist(
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(require_admin),
) -> ApiEnvelope[SetupChecklistStateResponse]:
    if ctx.is_support_session:
        raise HTTPException(403, "Support sessions cannot complete setup checklist")
    tenant = await db.get(Tenant, ctx.tenant_id)
    if not tenant:
        raise HTTPException(404, "Tenant not found")
    tenant.settings_json = set_setup_checklist_complete(tenant.settings_json)
    await db.commit()
    await db.refresh(tenant)
    state = await build_setup_checklist_state(
        db,
        tenant=tenant,
        user_role=ctx.role,
        is_support_session=ctx.is_support_session,
    )
    return ApiEnvelope(data=state)
