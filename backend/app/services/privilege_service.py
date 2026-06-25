"""Org approval-policy privilege checks (Phase H)."""

from __future__ import annotations

import uuid

from fastapi import HTTPException

from app.api.deps import AuthContext
from app.services.approval_policy_io import load_policy_for_tenant
from app.tenant_roles import APPROVAL_ACTIONS, matrix_row_for_role
from app.utils.logger import get_logger

logger = get_logger(__name__)


def matrix_role_for_context(ctx: AuthContext) -> str:
    return matrix_row_for_role(ctx.role)


def _matrix_row_permissions(row: dict[str, bool]) -> dict[str, bool]:
    return {
        action: bool(
            row.get(action, row.get("Publish") if action == "Post" else False)
        )
        for action in APPROVAL_ACTIONS
    }


def permissions_for_role(tenant_id: uuid.UUID, role: str) -> dict[str, bool]:
    policy = load_policy_for_tenant(tenant_id)
    row = policy.matrix.get(matrix_row_for_role(role)) or {}
    return _matrix_row_permissions(row)


def permissions_for_context(ctx: AuthContext) -> dict[str, bool]:
    return permissions_for_role(ctx.tenant_id, ctx.role)


def user_has_privilege(ctx: AuthContext, action: str) -> bool:
    return permissions_for_context(ctx).get(action, False)


def require_privilege(ctx: AuthContext, action: str) -> None:
    allowed = user_has_privilege(ctx, action)
    logger.debug(
        "privilege_check",
        tenant_id=str(ctx.tenant_id),
        role=ctx.role,
        action=action,
        allowed=allowed,
    )
    if not allowed:
        raise HTTPException(403, f"Missing privilege: {action}")
