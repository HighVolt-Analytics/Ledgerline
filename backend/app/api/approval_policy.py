"""Approval policy GET/PUT for org-scoped privilege matrix."""

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthContext, actor_from_context, get_auth_context, get_db
from app.schemas.approval_policy import ApprovalPolicyPayload, ApprovalPolicyUnlock
from app.schemas.common import ApiEnvelope
from app.services.approval_policy_io import (
    load_policy_for_org,
    save_policy_for_org,
    unlock_policy,
)
from app.services.audit_service import log_event
from app.services.privilege_service import require_privilege

router = APIRouter(prefix="/approval-policy", tags=["approval-policy"])


@router.get("", response_model=ApiEnvelope[ApprovalPolicyPayload])
async def get_approval_policy(
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[ApprovalPolicyPayload]:
    return ApiEnvelope(data=load_policy_for_org(ctx.org_id))


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
    before = load_policy_for_org(ctx.org_id).model_dump()
    saved = save_policy_for_org(ctx.org_id, body)
    actor_name, actor_email = await actor_from_context(db, ctx)
    client_ip = request.client.host if request.client else None
    await log_event(
        db,
        "approval_policy_updated",
        org_id=ctx.org_id,
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
    before = load_policy_for_org(ctx.org_id).model_dump()
    try:
        policy = unlock_policy(ctx.org_id, body.code)
    except ValueError as exc:
        raise HTTPException(403, str(exc)) from exc
    actor_name, actor_email = await actor_from_context(db, ctx)
    client_ip = request.client.host if request.client else None
    await log_event(
        db,
        "approval_policy_unlocked",
        org_id=ctx.org_id,
        detail={"before": before, "after": policy.model_dump()},
        actor_name=actor_name,
        actor_email=actor_email,
        client_ip=client_ip,
    )
    return ApiEnvelope(data=policy)
