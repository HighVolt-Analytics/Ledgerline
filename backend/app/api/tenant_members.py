"""Tenant member management for the current tenant."""

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthContext, actor_from_context, get_auth_context, get_db
from app.models.tenant import Tenant
from app.schemas.common import ApiEnvelope
from app.schemas.tenant_member import (
    InviteMemberRequest,
    InviteMemberResponse,
    PendingInviteResponse,
    TenantMemberResponse,
    TenantMembersListResponse,
    UpdateMemberRoleRequest,
)
from app.services.audit_service import log_event
from app.services.auth_email_service import send_tenant_invite_email
from app.services.privilege_service import require_privilege
from app.services.tenant_members_service import (
    create_invite,
    deactivate_member,
    list_tenant_members,
    revoke_invite,
    update_member_role,
)

router = APIRouter(prefix="/tenants/current/members", tags=["tenant-members"])


def _member_response(row) -> TenantMemberResponse:
    return TenantMemberResponse(
        user_id=row.user_id,
        email=row.email,
        full_name=row.full_name,
        role=row.role,
        status=row.status,
        is_active=row.is_active,
    )


def _invite_response(row) -> PendingInviteResponse:
    return PendingInviteResponse(
        id=row.id,
        email=row.email,
        full_name=row.full_name,
        role=row.role,
        expires_at=row.expires_at,
        created_at=row.created_at,
    )


@router.get("", response_model=ApiEnvelope[TenantMembersListResponse])
async def get_tenant_members(
    ctx: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> ApiEnvelope[TenantMembersListResponse]:
    members, pending = await list_tenant_members(db, tenant_id=ctx.tenant_id)
    return ApiEnvelope(
        data=TenantMembersListResponse(
            members=[_member_response(m) for m in members],
            pending_invites=[_invite_response(i) for i in pending],
        )
    )


@router.patch("/{user_id}", response_model=ApiEnvelope[TenantMemberResponse])
async def patch_member_role(
    user_id: int,
    body: UpdateMemberRoleRequest,
    request: Request,
    ctx: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> ApiEnvelope[TenantMemberResponse]:
    require_privilege(ctx, "Manage Users")
    before_members, _ = await list_tenant_members(db, tenant_id=ctx.tenant_id)
    before = next((m for m in before_members if m.user_id == user_id), None)

    updated = await update_member_role(
        db,
        tenant_id=ctx.tenant_id,
        user_id=user_id,
        role=body.role,
    )

    actor_name, actor_email = await actor_from_context(db, ctx)
    client_ip = request.client.host if request.client else None
    await log_event(
        db,
        "tenant_member_role_changed",
        tenant_id=ctx.tenant_id,
        detail={
            "user_id": user_id,
            "before_role": before.role if before else None,
            "after_role": updated.role,
        },
        actor_name=actor_name,
        actor_email=actor_email,
        client_ip=client_ip,
    )
    return ApiEnvelope(data=_member_response(updated))


@router.delete("/{user_id}", response_model=ApiEnvelope[dict[str, str]])
async def remove_member(
    user_id: int,
    request: Request,
    ctx: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> ApiEnvelope[dict[str, str]]:
    require_privilege(ctx, "Manage Users")
    if ctx.user_id == user_id:
        raise HTTPException(400, "You cannot deactivate your own account")

    before_members, _ = await list_tenant_members(db, tenant_id=ctx.tenant_id)
    before = next((m for m in before_members if m.user_id == user_id), None)
    await deactivate_member(db, tenant_id=ctx.tenant_id, user_id=user_id)

    actor_name, actor_email = await actor_from_context(db, ctx)
    client_ip = request.client.host if request.client else None
    await log_event(
        db,
        "tenant_member_deactivated",
        tenant_id=ctx.tenant_id,
        detail={
            "user_id": user_id,
            "email": before.email if before else None,
            "role": before.role if before else None,
        },
        actor_name=actor_name,
        actor_email=actor_email,
        client_ip=client_ip,
    )
    return ApiEnvelope(data={"message": "Member deactivated"})


@router.delete("/invites/{invite_id}", response_model=ApiEnvelope[dict[str, str]])
async def revoke_member_invite(
    invite_id: int,
    request: Request,
    ctx: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> ApiEnvelope[dict[str, str]]:
    require_privilege(ctx, "Manage Users")
    revoked = await revoke_invite(db, tenant_id=ctx.tenant_id, invite_id=invite_id)

    actor_name, actor_email = await actor_from_context(db, ctx)
    client_ip = request.client.host if request.client else None
    await log_event(
        db,
        "tenant_member_invite_revoked",
        tenant_id=ctx.tenant_id,
        detail={
            "invite_id": revoked.invite_id,
            "email": revoked.email,
            "role": revoked.role,
        },
        actor_name=actor_name,
        actor_email=actor_email,
        client_ip=client_ip,
    )
    return ApiEnvelope(data={"message": "Invite revoked"})


@router.post("/invite", response_model=ApiEnvelope[InviteMemberResponse])
async def invite_member(
    body: InviteMemberRequest,
    request: Request,
    ctx: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> ApiEnvelope[InviteMemberResponse]:
    require_privilege(ctx, "Manage Users")

    created = await create_invite(
        db,
        tenant_id=ctx.tenant_id,
        email=body.email,
        full_name=body.full_name,
        role=body.role,
        invited_by_user_id=ctx.user_id,
    )

    tenant = await db.get(Tenant, ctx.tenant_id)
    email_sent = False
    email_error: str | None = None
    if tenant:
        tenant_name = tenant.name
        delivery = await send_tenant_invite_email(
            to_email=created.email,
            tenant_name=tenant_name,
            role=body.role,
            accept_url=created.accept_url,
        )
        email_sent = delivery.sent
        email_error = delivery.error

    actor_name, actor_email = await actor_from_context(db, ctx)
    client_ip = request.client.host if request.client else None
    await log_event(
        db,
        "tenant_member_invited",
        tenant_id=ctx.tenant_id,
        detail={
            "invite_id": created.invite_id,
            "email": created.email,
            "role": body.role,
        },
        actor_name=actor_name,
        actor_email=actor_email,
        client_ip=client_ip,
    )

    return ApiEnvelope(
        data=InviteMemberResponse(
            invite_id=created.invite_id,
            email=created.email,
            accept_url=created.accept_url,
            expires_at=created.expires_at,
            email_sent=email_sent,
            email_error=email_error,
        )
    )
