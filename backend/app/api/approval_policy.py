"""Approval policy GET/PUT for org-scoped privilege matrix."""

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import AuthContext, get_auth_context
from app.schemas.approval_policy import ApprovalPolicyPayload, ApprovalPolicyUnlock
from app.schemas.common import ApiEnvelope
from app.services.approval_policy_io import (
    load_policy_for_org,
    save_policy_for_org,
    unlock_policy,
)

router = APIRouter(prefix="/approval-policy", tags=["approval-policy"])


@router.get("", response_model=ApiEnvelope[ApprovalPolicyPayload])
async def get_approval_policy(
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[ApprovalPolicyPayload]:
    return ApiEnvelope(data=load_policy_for_org(ctx.org_id))


@router.put("", response_model=ApiEnvelope[ApprovalPolicyPayload])
async def put_approval_policy(
    body: ApprovalPolicyPayload,
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[ApprovalPolicyPayload]:
    if body.locked:
        raise HTTPException(403, "Policy is locked — unlock before editing")
    saved = save_policy_for_org(ctx.org_id, body)
    return ApiEnvelope(data=saved)


@router.post("/unlock", response_model=ApiEnvelope[ApprovalPolicyPayload])
async def unlock_approval_policy(
    body: ApprovalPolicyUnlock,
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[ApprovalPolicyPayload]:
    try:
        policy = unlock_policy(ctx.org_id, body.code)
    except ValueError as exc:
        raise HTTPException(403, str(exc)) from exc
    return ApiEnvelope(data=policy)
