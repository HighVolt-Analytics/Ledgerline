"""Platform super-admin APIs for cross-tenant management."""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthContext, get_db, require_super_admin
from app.models.tenant import Tenant
from app.models.user import User
from app.schemas.auth import TokenResponse
from app.schemas.common import ApiEnvelope
from app.schemas.platform import (
    CreatePlatformTenantRequest,
    DeletePlatformTenantRequest,
    PlatformInviteAdminRequest,
    PlatformInviteAdminResponse,
    PlatformTenantDetail,
    PlatformTenantSummary,
    UpdatePlatformTenantRequest,
)
from app.services.auth_email_service import send_tenant_invite_email
from app.services.platform_service import (
    create_client_tenant,
    delete_client_tenant,
    get_client_tenant,
    invite_tenant_admin,
    list_client_tenants,
    provision_client_tenant_access,
    update_client_tenant,
)
from app.tenant_roles import TenantRole

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

    tenant = await get_client_tenant(db, tenant_id=tenant_id)
    if not tenant:
        raise HTTPException(404, "Tenant not found")

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


@router.post("/tenants/{tenant_id}/enter-workspace", response_model=ApiEnvelope[TokenResponse])
async def enter_client_workspace(
    tenant_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(require_super_admin),
) -> ApiEnvelope[TokenResponse]:
    """Provision shadow admin access if needed, then mint a support-mode tenant session."""
    if ctx.user_id is None:
        raise HTTPException(401, "Sign in to open workspace")

    tenant = await get_client_tenant(db, tenant_id=tenant_id)
    if not tenant:
        raise HTTPException(404, "Tenant not found")

    try:
        client_user = await provision_client_tenant_access(
            db,
            tenant_id=tenant_id,
            operator_user_id=ctx.user_id,
        )
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc

    tenant_row = await db.get(Tenant, tenant_id)
    if not tenant_row:
        raise HTTPException(404, "Tenant not found")

    role = TenantRole.ADMIN.value
    from app.api.auth import (
        _membership_summaries_for_account,
        _mint_session_tokens,
        _user_response,
    )
    from app.tenant_settings import tenant_onboarding_completed

    operator = await db.get(User, ctx.user_id)
    if not operator or not operator.auth_account_id:
        raise HTTPException(401, "Session invalid")

    access, refresh = await _mint_session_tokens(
        db, user=client_user, tenant=tenant_row, role=role, is_support_session=True
    )
    memberships = await _membership_summaries_for_account(
        db, auth_account_id=operator.auth_account_id
    )
    return ApiEnvelope(
        data=TokenResponse(
            access_token=access,
            refresh_token=refresh,
            user=_user_response(
                client_user,
                tenant_row,
                role=role,
                is_support_session=True,
                onboarding_completed=tenant_onboarding_completed(tenant_row),
            ),
            memberships=memberships,
        )
    )


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
