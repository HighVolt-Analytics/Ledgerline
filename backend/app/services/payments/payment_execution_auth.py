"""Role checks for manual payment execution orchestration."""

from __future__ import annotations

from app.api.deps import AuthContext
from app.models.user import UserRole
from app.services.auth.privilege_service import user_has_privilege
from app.tenant_roles import TenantRole

PAYMENT_EXECUTION_ROLES = frozenset(
    {
        TenantRole.ADMIN.value,
        TenantRole.APPROVER.value,
        UserRole.ADMIN.value,
        UserRole.MEMBER.value,
        "admin",
        "approver",
        "member",
    }
)


class PaymentExecutionUnauthorizedError(Exception):
    """Actor lacks Tenant Admin / Approver permission for payment execution."""


def actor_can_execute_manual_payment(ctx: AuthContext) -> bool:
    role = (ctx.role or "").strip().lower()
    if role in PAYMENT_EXECUTION_ROLES:
        return True
    return user_has_privilege(ctx, "Approve")


def require_payment_execution_role(ctx: AuthContext) -> None:
    if not actor_can_execute_manual_payment(ctx):
        raise PaymentExecutionUnauthorizedError(
            "Payment execution requires Tenant Admin or Approver role"
        )
