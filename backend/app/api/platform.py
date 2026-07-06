"""Platform super-admin APIs for cross-tenant management."""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthContext, cross_tenant_db_lookup, get_db, require_super_admin
from app.models.tenant import Tenant
from app.schemas.common import ApiEnvelope
from app.schemas.billing import (
    BillingUsageHistoryResponse,
    CreditLedgerEntryResponse,
    PlatformCreditSettingsResponse,
    PlatformCreditSettingsUpdate,
    PlatformTenantBillingUpdate,
)
from app.schemas.platform import (
    CreatePlatformTenantRequest,
    DeletePlatformTenantRequest,
    PlatformInviteAdminRequest,
    PlatformInviteAdminResponse,
    PlatformTenantDetail,
    PlatformTenantSummary,
    UpdatePlatformTenantRequest,
)
from app.services.credit_service import (
    get_platform_credit_settings,
    list_credit_ledger,
    set_tenant_plan,
    update_platform_credit_settings,
)
from app.schemas.tenant_member import (
    PendingInviteResponse,
    TenantMemberResponse,
    TenantMembersListResponse,
)
from app.services.auth.auth_email_service import send_tenant_invite_email
from app.services.tenant.platform_service import (
    create_client_tenant,
    delete_client_tenant,
    get_client_tenant,
    invite_tenant_admin,
    list_client_tenant_members,
    list_client_tenants,
    update_client_tenant,
)
from app.tenant_roles import TenantRole

router = APIRouter(prefix="/platform", tags=["platform"])


@router.get("/tenants", response_model=ApiEnvelope[list[PlatformTenantSummary]])
async def list_tenants(
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(require_super_admin),
) -> ApiEnvelope[list[PlatformTenantSummary]]:
    async with cross_tenant_db_lookup(db, restore_tenant_id=ctx.tenant_id):
        tenants = await list_client_tenants(db)
    return ApiEnvelope(data=tenants)


@router.post("/tenants", response_model=ApiEnvelope[PlatformTenantDetail], status_code=201)
async def create_tenant(
    body: CreatePlatformTenantRequest,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(require_super_admin),
) -> ApiEnvelope[PlatformTenantDetail]:
    if ctx.user_id is None:
        raise HTTPException(401, "Sign in to create a tenant")

    slug = body.slug.strip().lower()
    taken = (
        await db.execute(select(Tenant).where(Tenant.slug == slug))
    ).scalar_one_or_none()
    if taken:
        raise HTTPException(409, f"Tenant slug '{slug}' is already taken")

    async with cross_tenant_db_lookup(db, restore_tenant_id=ctx.tenant_id):
        tenant, invite = await create_client_tenant(db, body, invited_by_user_id=ctx.user_id)
    tenant_row = await db.get(Tenant, tenant.id)
    if tenant_row:
        await send_tenant_invite_email(
            to_email=invite.email,
            tenant_name=tenant_row.name,
            role=TenantRole.ADMIN.value,
            accept_url=invite.accept_url,
        )
    return ApiEnvelope(data=tenant)


@router.post(
    "/tenants/{tenant_id}/invite-admin",
    response_model=ApiEnvelope[PlatformInviteAdminResponse],
    status_code=201,
)
async def invite_admin(
    tenant_id: uuid.UUID,
    body: PlatformInviteAdminRequest,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(require_super_admin),
) -> ApiEnvelope[PlatformInviteAdminResponse]:
    if ctx.user_id is None:
        raise HTTPException(401, "Sign in to invite an admin")

    async with cross_tenant_db_lookup(db, restore_tenant_id=ctx.tenant_id):
        tenant = await get_client_tenant(db, tenant_id=tenant_id)
    if not tenant:
        raise HTTPException(404, "Tenant not found")

    async with cross_tenant_db_lookup(db, restore_tenant_id=ctx.tenant_id):
        created = await invite_tenant_admin(
            db,
            tenant_id=tenant_id,
            email=str(body.email),
            full_name=body.full_name,
            invited_by_user_id=ctx.user_id,
        )

    tenant_row = await db.get(Tenant, tenant_id)
    email_sent = False
    email_error: str | None = None
    if tenant_row:
        delivery = await send_tenant_invite_email(
            to_email=created.email,
            tenant_name=tenant_row.name,
            role=TenantRole.ADMIN.value,
            accept_url=created.accept_url,
        )
        email_sent = delivery.sent
        email_error = delivery.error

    return ApiEnvelope(
        data=PlatformInviteAdminResponse(
            invite_id=created.invite_id,
            email=created.email,
            accept_url=created.accept_url,
            expires_at=created.expires_at,
            email_sent=email_sent,
            email_error=email_error,
        )
    )


@router.get("/tenants/{tenant_id}", response_model=ApiEnvelope[PlatformTenantDetail])
async def get_tenant(
    tenant_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(require_super_admin),
) -> ApiEnvelope[PlatformTenantDetail]:
    async with cross_tenant_db_lookup(db, restore_tenant_id=ctx.tenant_id):
        tenant = await get_client_tenant(db, tenant_id=tenant_id)
    if not tenant:
        raise HTTPException(404, "Tenant not found")
    return ApiEnvelope(data=tenant)


@router.get(
    "/tenants/{tenant_id}/members",
    response_model=ApiEnvelope[TenantMembersListResponse],
)
async def list_tenant_members_for_platform(
    tenant_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(require_super_admin),
) -> ApiEnvelope[TenantMembersListResponse]:
    """List all users and pending invites for a client tenant."""
    async with cross_tenant_db_lookup(db, restore_tenant_id=ctx.tenant_id):
        result = await list_client_tenant_members(db, tenant_id=tenant_id)
    if result is None:
        raise HTTPException(404, "Tenant not found")

    members, pending = result
    return ApiEnvelope(
        data=TenantMembersListResponse(
            members=[
                TenantMemberResponse(
                    user_id=m.user_id,
                    email=m.email,
                    full_name=m.full_name,
                    role=m.role,
                    status=m.status,
                    is_active=m.is_active,
                )
                for m in members
            ],
            pending_invites=[
                PendingInviteResponse(
                    id=i.id,
                    email=i.email,
                    full_name=i.full_name,
                    role=i.role,
                    expires_at=i.expires_at,
                    created_at=i.created_at,
                )
                for i in pending
            ],
        )
    )


@router.patch("/tenants/{tenant_id}", response_model=ApiEnvelope[PlatformTenantDetail])
async def update_tenant(
    tenant_id: uuid.UUID,
    body: UpdatePlatformTenantRequest,
    db: AsyncSession = Depends(get_db),
    _ctx: AuthContext = Depends(require_super_admin),
) -> ApiEnvelope[PlatformTenantDetail]:
    try:
        tenant = await update_client_tenant(db, tenant_id=tenant_id, body=body)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if not tenant:
        raise HTTPException(404, "Tenant not found")
    return ApiEnvelope(data=tenant)


@router.post("/tenants/{tenant_id}/delete-permanently", response_model=ApiEnvelope[dict[str, str]])
async def delete_tenant_permanently(
    tenant_id: uuid.UUID,
    body: DeletePlatformTenantRequest,
    db: AsyncSession = Depends(get_db),
    _ctx: AuthContext = Depends(require_super_admin),
) -> ApiEnvelope[dict[str, str]]:
    try:
        deleted = await delete_client_tenant(db, tenant_id=tenant_id, body=body)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if not deleted:
        raise HTTPException(404, "Tenant not found")
    return ApiEnvelope(data={"status": "deleted"})


def _ledger_row(row) -> CreditLedgerEntryResponse:
    return CreditLedgerEntryResponse(
        id=row.id,
        event_type=row.event_type,
        description=row.description,
        pages=row.pages,
        credits_per_page=row.credits_per_page,
        credits_delta=row.credits_delta,
        balance_after=row.balance_after,
        plan_at_event=row.plan_at_event,
        amount_paid=float(row.amount_paid) if row.amount_paid is not None else None,
        currency_code=row.currency_code,
        azure_cost_usd=float(row.azure_cost_usd) if row.azure_cost_usd is not None else None,
        azure_cost_breakdown=row.azure_cost_breakdown_json,
        filename=row.filename,
        invoice_id=row.invoice_id,
        created_at=row.created_at,
    )


@router.get("/credit-settings", response_model=ApiEnvelope[PlatformCreditSettingsResponse])
async def get_credit_settings(
    db: AsyncSession = Depends(get_db),
    _ctx: AuthContext = Depends(require_super_admin),
) -> ApiEnvelope[PlatformCreditSettingsResponse]:
    settings = await get_platform_credit_settings(db)
    return ApiEnvelope(
        data=PlatformCreditSettingsResponse(
            credits_per_page=settings.credits_per_page,
            universal_credits_per_page=settings.universal_credits_per_page,
            topup_factor_in=float(settings.topup_factor_in),
            topup_factor_sg=float(settings.topup_factor_sg),
            topup_factor_au=float(settings.topup_factor_au),
        )
    )


@router.patch("/credit-settings", response_model=ApiEnvelope[PlatformCreditSettingsResponse])
async def patch_credit_settings(
    body: PlatformCreditSettingsUpdate,
    db: AsyncSession = Depends(get_db),
    _ctx: AuthContext = Depends(require_super_admin),
) -> ApiEnvelope[PlatformCreditSettingsResponse]:
    settings = await update_platform_credit_settings(
        db,
        credits_per_page=body.credits_per_page,
        universal_credits_per_page=body.universal_credits_per_page,
        topup_factor_in=body.topup_factor_in,
        topup_factor_sg=body.topup_factor_sg,
        topup_factor_au=body.topup_factor_au,
    )
    await db.commit()
    return ApiEnvelope(
        data=PlatformCreditSettingsResponse(
            credits_per_page=settings.credits_per_page,
            universal_credits_per_page=settings.universal_credits_per_page,
            topup_factor_in=float(settings.topup_factor_in),
            topup_factor_sg=float(settings.topup_factor_sg),
            topup_factor_au=float(settings.topup_factor_au),
        )
    )


@router.get(
    "/tenants/{tenant_id}/usage",
    response_model=ApiEnvelope[BillingUsageHistoryResponse],
)
async def get_tenant_usage_history(
    tenant_id: uuid.UUID,
    page: int = 1,
    page_size: int = 50,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(require_super_admin),
) -> ApiEnvelope[BillingUsageHistoryResponse]:
    async with cross_tenant_db_lookup(db, restore_tenant_id=ctx.tenant_id):
        tenant = await db.get(Tenant, tenant_id)
        if not tenant or tenant.is_platform:
            raise HTTPException(404, "Tenant not found")
        offset = (page - 1) * page_size
        rows, total = await list_credit_ledger(db, tenant_id, limit=page_size, offset=offset)
    pages = max(1, (total + page_size - 1) // page_size)
    return ApiEnvelope(
        data=BillingUsageHistoryResponse(
            items=[_ledger_row(r) for r in rows],
            total=total,
            page=page,
            pages=pages,
        )
    )


@router.patch("/tenants/{tenant_id}/billing", response_model=ApiEnvelope[PlatformTenantDetail])
async def patch_tenant_billing(
    tenant_id: uuid.UUID,
    body: PlatformTenantBillingUpdate,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(require_super_admin),
) -> ApiEnvelope[PlatformTenantDetail]:
    async with cross_tenant_db_lookup(db, restore_tenant_id=ctx.tenant_id):
        tenant = await db.get(Tenant, tenant_id)
        if not tenant or tenant.is_platform:
            raise HTTPException(404, "Tenant not found")
        await set_tenant_plan(
            db,
            tenant_id,
            plan=body.plan,
            enterprise_monthly_credits=body.enterprise_monthly_credits,
            credits_per_page_override=body.credits_per_page_override,
            grant_credits=body.grant_credits,
        )
        await db.commit()
        detail = await get_client_tenant(db, tenant_id=tenant_id)
    if not detail:
        raise HTTPException(404, "Tenant not found")
    return ApiEnvelope(data=detail)
