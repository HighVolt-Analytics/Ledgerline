"""Approval policy GET/PUT for tenant-scoped privilege matrix."""

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthContext, actor_from_context, get_auth_context, get_db
from app.schemas.approval_policy import ApprovalPolicyPayload, ApprovalPolicyUnlock
from app.schemas.common import ApiEnvelope
from app.services.approval.approval_policy_io import (
    load_policy_for_tenant_async,
    save_policy_for_tenant_async,
    unlock_policy_async,
)
from app.services.audit.audit_service import log_event
from app.services.auth.privilege_service import require_privilege

router = APIRouter(prefix="/approval-policy", tags=["approval-policy"])


@router.get("", response_model=ApiEnvelope[ApprovalPolicyPayload])
async def get_approval_policy(
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[ApprovalPolicyPayload]:
    return ApiEnvelope(data=await load_policy_for_tenant_async(db, ctx.tenant_id))


@router.put("", response_model=ApiEnvelope[ApprovalPolicyPayload])
async def put_approval_policy(
    body: ApprovalPolicyPayload,
    request: Request,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[ApprovalPolicyPayload]:
    require_privilege(ctx, "Edit Policy")
    if body.locked:
        raise HTTPException(403, "Policy is locked — unlock before editing")
    before = (await load_policy_for_tenant_async(db, ctx.tenant_id)).model_dump()
    saved = await save_policy_for_tenant_async(
        db,
        ctx.tenant_id,
        body,
        updated_by_user_id=ctx.user_id,
    )
    actor_name, actor_email = await actor_from_context(db, ctx)
    client_ip = request.client.host if request.client else None
    await log_event(
        db,
        "approval_policy_updated",
        tenant_id=ctx.tenant_id,
        detail={"before": before, "after": saved.model_dump()},
        actor_name=actor_name,
        actor_email=actor_email,
        client_ip=client_ip,
    )
    return ApiEnvelope(data=saved)


@router.post("/unlock", response_model=ApiEnvelope[ApprovalPolicyPayload])
async def unlock_approval_policy(
    body: ApprovalPolicyUnlock,
    request: Request,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[ApprovalPolicyPayload]:
    require_privilege(ctx, "Edit Policy")
    before = (await load_policy_for_tenant_async(db, ctx.tenant_id)).model_dump()
    try:
        policy = await unlock_policy_async(
            db,
            ctx.tenant_id,
            body.code,
            updated_by_user_id=ctx.user_id,
        )
    except ValueError as exc:
        raise HTTPException(403, str(exc)) from exc
    actor_name, actor_email = await actor_from_context(db, ctx)
    client_ip = request.client.host if request.client else None
    await log_event(
        db,
        "approval_policy_unlocked",
        tenant_id=ctx.tenant_id,
        detail={"before": before, "after": policy.model_dump()},
        actor_name=actor_name,
        actor_email=actor_email,
        client_ip=client_ip,
    )
    return ApiEnvelope(data=policy)
