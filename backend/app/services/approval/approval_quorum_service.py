"""Per-module approval quorum (1/2/3-way) from a fixed leadership pool."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
import uuid

from app.api.deps import AuthContext
from app.models.user import SUPER_ADMIN_ROLE, UserRole
from app.schemas.approval_policy import ApprovalQuorumMode
from app.services.approval.approval_policy_io import load_policy_for_tenant
from app.tenant_roles import TenantRole, normalize_tenant_role
from app.services.vault.vault_paths import (
    ROUTE_EXPENSES,
    ROUTE_PURCHASE,
    ROUTE_SALES,
    ROUTE_TEAM,
)

APPROVAL_POOL_ROLES: frozenset[str] = frozenset(
    {
        TenantRole.ADMIN.value,
        TenantRole.FUNCTIONAL_MANAGER.value,
        TenantRole.FUNCTIONAL_SUPERVISOR.value,
        TenantRole.FINANCE_HEAD.value,
        UserRole.ADMIN.value,
        SUPER_ADMIN_ROLE,
        # Legacy slugs still accepted until memberships are fully migrated
        "approver",
        "member",
    }
)

_MODE_TO_REQUIRED: dict[str, int] = {
    "one_way": 1,
    "two_way": 2,
    "three_way": 3,
}

_ROUTE_TO_MODULE: dict[str, str] = {
    ROUTE_TEAM: "team_expenses",
    ROUTE_EXPENSES: "expenses",
    ROUTE_PURCHASE: "purchase",
    ROUTE_SALES: "sales",
}


class ApprovalQuorumForbiddenError(PermissionError):
    """Actor is outside the fixed approval pool."""


@dataclass(frozen=True)
class QuorumProgress:
    module: str
    mode: ApprovalQuorumMode
    required: int
    recorded: int
    remaining: int
    quorum_met: bool
    chain: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "module": self.module,
            "mode": self.mode,
            "required": self.required,
            "recorded": self.recorded,
            "remaining": self.remaining,
            "quorum_met": self.quorum_met,
        }


def module_for_route_target(route_target: str | None) -> str:
    key = (route_target or "").strip()
    return _ROUTE_TO_MODULE.get(key, "expenses")


def mode_for_module(tenant_id: uuid.UUID, module_key: str) -> ApprovalQuorumMode:
    policy = load_policy_for_tenant(tenant_id)
    by_module = policy.approval_matrix.by_module or {}
    mode = by_module.get(module_key) or "one_way"
    if mode not in _MODE_TO_REQUIRED:
        return "one_way"
    return mode  # type: ignore[return-value]


def required_count(tenant_id: uuid.UUID, module_key: str) -> int:
    return _MODE_TO_REQUIRED[mode_for_module(tenant_id, module_key)]


def actor_in_pool(ctx: AuthContext) -> bool:
    role = (ctx.role or "").strip().lower()
    if role in APPROVAL_POOL_ROLES:
        return True
    if role == SUPER_ADMIN_ROLE:
        return True
    normalized = normalize_tenant_role(ctx.role)
    return normalized in {
        TenantRole.ADMIN,
        TenantRole.FUNCTIONAL_MANAGER,
        TenantRole.FUNCTIONAL_SUPERVISOR,
        TenantRole.FINANCE_HEAD,
    }


def require_actor_in_pool(ctx: AuthContext) -> None:
    if not actor_in_pool(ctx):
        raise ApprovalQuorumForbiddenError(
            "Approval requires Admin, Functional manager, Functional supervisor, or Finance head"
        )


def _approvals_list(chain: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(chain, dict):
        return []
    raw = chain.get("approvals")
    if not isinstance(raw, list):
        return []
    return [a for a in raw if isinstance(a, dict)]


def recorded_count(chain: dict[str, Any] | None) -> int:
    ids = {
        int(a["user_id"])
        for a in _approvals_list(chain)
        if a.get("user_id") is not None
    }
    return len(ids)


def approver_user_ids(chain: dict[str, Any] | None) -> set[int]:
    """Every distinct user id that recorded an approval in this chain.

    Used for payment segregation-of-duties: an invoice approver must not
    also be the one who releases its payment.
    """
    return {
        int(a["user_id"])
        for a in _approvals_list(chain)
        if a.get("user_id") is not None
    }


def last_approval_user_id(chain: dict[str, Any] | None) -> int | None:
    """Most recent approver's user id, or None when the chain is empty."""
    approvals = _approvals_list(chain)
    if not approvals:
        return None
    uid = approvals[-1].get("user_id")
    return int(uid) if uid is not None else None


def quorum_met(chain: dict[str, Any] | None) -> bool:
    if not isinstance(chain, dict):
        return False
    try:
        required = int(chain.get("required") or 0)
    except (TypeError, ValueError):
        required = 0
    if required <= 0:
        return False
    return recorded_count(chain) >= required


def progress_from_chain(chain: dict[str, Any] | None) -> QuorumProgress | None:
    if not isinstance(chain, dict) or not chain:
        return None
    mode = str(chain.get("mode") or "one_way")
    if mode not in _MODE_TO_REQUIRED:
        mode = "one_way"
    try:
        required = int(chain.get("required") or _MODE_TO_REQUIRED[mode])
    except (TypeError, ValueError):
        required = _MODE_TO_REQUIRED[mode]
    recorded = recorded_count(chain)
    remaining = max(0, required - recorded)
    return QuorumProgress(
        module=str(chain.get("module") or "expenses"),
        mode=mode,  # type: ignore[arg-type]
        required=required,
        recorded=recorded,
        remaining=remaining,
        quorum_met=recorded >= required,
        chain=chain,
    )


def empty_chain(
    *,
    tenant_id: uuid.UUID,
    module_key: str,
) -> dict[str, Any]:
    mode = mode_for_module(tenant_id, module_key)
    return {
        "module": module_key,
        "mode": mode,
        "required": _MODE_TO_REQUIRED[mode],
        "approvals": [],
    }


def record_approval(
    chain: dict[str, Any] | None,
    *,
    tenant_id: uuid.UUID,
    module_key: str,
    user_id: int,
    role: str,
    name: str,
) -> dict[str, Any]:
    """Append a distinct approver; same user re-click is idempotent."""
    base = deepcopy(chain) if isinstance(chain, dict) and chain else empty_chain(
        tenant_id=tenant_id, module_key=module_key
    )
    # Refresh required/mode from current policy when starting or continuing
    mode = mode_for_module(tenant_id, module_key)
    base["module"] = module_key
    base["mode"] = mode
    base["required"] = _MODE_TO_REQUIRED[mode]

    approvals = _approvals_list(base)
    existing_ids = {int(a["user_id"]) for a in approvals if a.get("user_id") is not None}
    if int(user_id) not in existing_ids:
        approvals.append(
            {
                "user_id": int(user_id),
                "role": (role or "").strip().lower() or "unknown",
                "name": (name or "").strip() or f"User {user_id}",
                "at": datetime.now(timezone.utc).isoformat(),
            }
        )
    base["approvals"] = approvals
    return base


def clear_chain() -> None:
    """Helper sentinel — callers set the column to None."""
    return None
