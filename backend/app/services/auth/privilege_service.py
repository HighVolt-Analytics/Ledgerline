"""Org approval-policy privilege checks (Phase H)."""

from __future__ import annotations

import uuid

from fastapi import HTTPException

from app.api.deps import AuthContext
from app.services.approval.approval_policy_io import load_policy_for_tenant
from app.tenant_roles import (
    APPROVAL_ACTIONS,
    APPROVE_ALIASES,
    BANK_REVEAL_ROLES,
    matrix_row_for_role,
    normalize_tenant_role,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)


def matrix_role_for_context(ctx: AuthContext) -> str:
    return matrix_row_for_role(ctx.role)


def _canonical_action(action: str) -> str:
    """Map Reject/Post/Publish onto the single Approve privilege."""
    if action in APPROVE_ALIASES:
        return "Approve"
    return action


def _matrix_row_permissions(row: dict[str, bool]) -> dict[str, bool]:
    """Return canonical privileges; Reject/Post mirror Approve for API consumers."""
    can_approve = bool(
        row.get("Approve")
        or row.get("Reject")
        or row.get("Post")
        or row.get("Publish")
    )
    out: dict[str, bool] = {}
    for action in APPROVAL_ACTIONS:
        if action == "Approve":
            out[action] = can_approve
        else:
            out[action] = bool(row.get(action, False))
    # Backward-compatible aliases for older clients / call sites
    out["Reject"] = can_approve
    out["Post"] = can_approve
    return out


def permissions_for_role(tenant_id: uuid.UUID, role: str) -> dict[str, bool]:
    policy = load_policy_for_tenant(tenant_id)
    row = policy.matrix.get(matrix_row_for_role(role)) or {}
    return _matrix_row_permissions(row)


def permissions_for_context(ctx: AuthContext) -> dict[str, bool]:
    return permissions_for_role(ctx.tenant_id, ctx.role)


def user_has_privilege(ctx: AuthContext, action: str) -> bool:
    perms = permissions_for_context(ctx)
    key = _canonical_action(action)
    return bool(perms.get(key, False))


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
        # Surface the canonical name so clients see "Approve" for reject/post too.
        raise HTTPException(403, f"Missing privilege: {_canonical_action(action)}")


def can_reveal_bank_details(ctx: AuthContext) -> bool:
    """Admin / Finance Manager / CFO / Director may request unmasked bank identifiers."""
    slug = (ctx.role or "").strip().lower()
    if slug in BANK_REVEAL_ROLES:
        return True
    normalized = normalize_tenant_role(ctx.role)
    return normalized is not None and normalized.value in BANK_REVEAL_ROLES


def require_bank_reveal(ctx: AuthContext) -> None:
    if not can_reveal_bank_details(ctx):
        raise HTTPException(403, "Missing privilege to reveal bank details")
