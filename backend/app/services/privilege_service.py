"""Org approval-policy privilege checks (Phase H)."""

from __future__ import annotations

from fastapi import HTTPException

from app.api.deps import AuthContext
from app.models.user import UserRole
from app.services.approval_policy_io import load_policy_for_tenant

_MATRIX_ROLE_BY_JWT: dict[str, str] = {
    UserRole.ADMIN.value: "Admin",
    UserRole.MEMBER.value: "Approver",
}


def matrix_role_for_context(ctx: AuthContext) -> str:
    return _MATRIX_ROLE_BY_JWT.get(ctx.role, "Approver")


def user_has_privilege(ctx: AuthContext, action: str) -> bool:
    policy = load_policy_for_tenant(ctx.tenant_id)
    role = matrix_role_for_context(ctx)
    row = policy.matrix.get(role) or {}
    return bool(row.get(action, False))


def require_privilege(ctx: AuthContext, action: str) -> None:
    if not user_has_privilege(ctx, action):
        raise HTTPException(403, f"Missing privilege: {action}")
