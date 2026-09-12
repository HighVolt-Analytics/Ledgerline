"""Amount-tier role approval quorum with escalation support."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any
import uuid

from app.api.deps import AuthContext
from app.models.user import SUPER_ADMIN_ROLE, UserRole
from app.schemas.approval_policy import ApprovalQuorumMode
from app.services.approval.amount_tier_approval import (
    AmountTierApprovalError,
    apply_document_approval,
    build_chain_from_amount,
    document_quorum_met,
    escalate_current_document_step,
    require_actor_for_current_step,
    require_actor_within_approval_limit,
)
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
        TenantRole.MANAGER.value,
        TenantRole.DEPARTMENT_HEAD.value,
        TenantRole.FINANCE_MANAGER.value,
        TenantRole.CFO.value,
        TenantRole.DIRECTOR.value,
        UserRole.ADMIN.value,
        SUPER_ADMIN_ROLE,
        # Legacy slugs still accepted until memberships are fully migrated
        "approver",
        "member",
        "functional_manager",
        "functional_supervisor",
        "finance_head",
        "bookkeeper",
        "auditor",
    }
)

_MODE_TO_REQUIRED: dict[str, int] = {
    "one_way": 1,
    "two_way": 2,
    "three_way": 3,
    "amount_tier": 1,
}

_ROUTE_TO_MODULE: dict[str, str] = {
    ROUTE_TEAM: "team_expenses",
    ROUTE_EXPENSES: "expenses",
    ROUTE_PURCHASE: "purchase",
    ROUTE_SALES: "sales",
}


class ApprovalQuorumForbiddenError(PermissionError):
    """Actor is outside the fixed approval pool or cannot cover the current step."""


@dataclass(frozen=True)
class QuorumProgress:
    module: str
    mode: ApprovalQuorumMode
    required: int
    recorded: int
    remaining: int
    quorum_met: bool
    chain: dict[str, Any]
    current_step_role: str | None = None

    def as_dict(self) -> dict[str, Any]:
        out = {
            "module": self.module,
            "mode": self.mode,
            "required": self.required,
            "recorded": self.recorded,
            "remaining": self.remaining,
            "quorum_met": self.quorum_met,
        }
        if self.current_step_role:
            out["current_step_role"] = self.current_step_role
        return out


def module_for_route_target(route_target: str | None) -> str:
    key = (route_target or "").strip()
    return _ROUTE_TO_MODULE.get(key, "expenses")


def mode_for_module(tenant_id: uuid.UUID, module_key: str) -> ApprovalQuorumMode:
    del tenant_id, module_key
    return "amount_tier"


def required_count(tenant_id: uuid.UUID, module_key: str) -> int:
    del tenant_id, module_key
    return 1


def actor_in_pool(ctx: AuthContext) -> bool:
    role = (ctx.role or "").strip().lower()
    if role in APPROVAL_POOL_ROLES:
        return True
    if role == SUPER_ADMIN_ROLE:
        return True
    normalized = normalize_tenant_role(ctx.role)
    return normalized in {
        TenantRole.ADMIN,
        TenantRole.MANAGER,
        TenantRole.DEPARTMENT_HEAD,
        TenantRole.FINANCE_MANAGER,
        TenantRole.CFO,
        TenantRole.DIRECTOR,
    }


def require_actor_in_pool(ctx: AuthContext) -> None:
    if not actor_in_pool(ctx):
        raise ApprovalQuorumForbiddenError(
            "Approval requires Manager, Department Head, Finance Manager, CFO, Director, or Admin"
        )


def _approvals_list(chain: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(chain, dict):
        return []
    raw = chain.get("approvals")
    if not isinstance(raw, list):
        return []
    return [a for a in raw if isinstance(a, dict)]


def recorded_count(chain: dict[str, Any] | None) -> int:
    if isinstance(chain, dict) and chain.get("mode") == "amount_tier":
        steps = [
            s
            for s in (chain.get("steps") or [])
            if isinstance(s, dict) and s.get("kind") == "document"
        ]
        if steps:
            return sum(1 for s in steps if s.get("status") == "approved")
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
    if isinstance(chain, dict) and (
        chain.get("mode") == "amount_tier" or chain.get("steps")
    ):
        return document_quorum_met(chain)
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
    if mode not in _MODE_TO_REQUIRED and mode != "amount_tier":
        mode = "one_way"
    try:
        required = int(chain.get("required") or _MODE_TO_REQUIRED.get(mode, 1))
    except (TypeError, ValueError):
        required = _MODE_TO_REQUIRED.get(mode, 1)
    recorded = recorded_count(chain)
    remaining = max(0, required - recorded)
    current_role = None
    for step in chain.get("steps") or []:
        if (
            isinstance(step, dict)
            and step.get("kind") == "document"
            and step.get("status") != "approved"
        ):
            current_role = str(step.get("escalated_to_role") or step.get("role") or "")
            break
    met = quorum_met(chain)
    return QuorumProgress(
        module=str(chain.get("module") or "expenses"),
        mode=mode,  # type: ignore[arg-type]
        required=required,
        recorded=recorded,
        remaining=0 if met else remaining,
        quorum_met=met,
        chain=chain,
        current_step_role=current_role or None,
    )


def empty_chain(
    *,
    tenant_id: uuid.UUID,
    module_key: str,
    amount: Any = None,
    policy: Any | None = None,
) -> dict[str, Any]:
    if policy is None:
        policy = load_policy_for_tenant(tenant_id)
    tiers = [t.model_dump() for t in policy.amount_approval_tiers]
    return build_chain_from_amount(
        tenant_id=tenant_id,
        module_key=module_key,
        amount=amount,
        tiers=tiers,
    )


def chain_needs_materialize(chain: dict[str, Any] | None) -> bool:
    if not isinstance(chain, dict) or not chain:
        return True
    steps = chain.get("steps")
    return not isinstance(steps, list) or not steps


def _pending_chain_without_approvals(chain: dict[str, Any] | None) -> bool:
    """True when chain exists but nobody has signed yet — safe to rebuild from policy."""
    if not isinstance(chain, dict) or not chain:
        return False
    steps = chain.get("steps")
    if not isinstance(steps, list) or not steps:
        return False
    for step in steps:
        if not isinstance(step, dict):
            continue
        if step.get("kind") == "document" and step.get("status") == "approved":
            return False
        if step.get("user_id") is not None:
            return False
    approvals = chain.get("approvals")
    if isinstance(approvals, list) and any(
        isinstance(a, dict) and a.get("user_id") is not None for a in approvals
    ):
        return False
    return True


def _policy_chain_signature(chain: dict[str, Any] | None) -> tuple[Any, ...]:
    """Compare unsigned chains to current policy without rewriting when unchanged."""
    if not isinstance(chain, dict):
        return ()
    doc_roles: list[tuple[Any, ...]] = []
    payment_role = None
    for step in chain.get("steps") or []:
        if not isinstance(step, dict):
            continue
        if step.get("kind") == "document":
            doc_roles.append(
                (
                    step.get("key"),
                    step.get("role"),
                    step.get("escalated_to_role"),
                )
            )
        elif step.get("kind") == "payment":
            payment_role = step.get("role")
    return (
        chain.get("tier_id"),
        str(chain.get("amount")),
        tuple(doc_roles),
        payment_role,
    )


def _sync_safe_attr(obj: Any, name: str, default: Any = None) -> Any:
    """Read an ORM attribute without triggering async lazy/deferred IO.

    List queries often ``defer(approval_chain)``. Touching an unloaded deferred
    column under AsyncSession raises MissingGreenlet and 500s mobile
    ``GET /api/approvals``.
    """
    try:
        from sqlalchemy import inspect as sa_inspect

        state = sa_inspect(obj)
        unloaded = getattr(state, "unloaded", None) or set()
        if name in unloaded:
            return default
        if name in state.dict:
            return state.dict.get(name, default)
    except Exception:
        pass
    try:
        return getattr(obj, name, default)
    except Exception:
        return default


def ensure_invoice_approval_chain(
    invoice: Any,
    *,
    policy: Any | None = None,
) -> bool:
    """Materialize / refresh the amount-tier chain when a doc enters Approvals.

    Returns True when the invoice's approval_chain was written/updated.
    Rebuilds unsigned chains when Policy & privileges tiers changed (e.g. after
    reprocess). Does not rewrite chains that already have approved steps.
    """
    tenant_id = _sync_safe_attr(invoice, "tenant_id", None)
    if tenant_id is None:
        return False
    existing = _sync_safe_attr(invoice, "approval_chain", None)
    module_key = module_for_route_target(_sync_safe_attr(invoice, "route_target", None))
    amount = _sync_safe_attr(invoice, "total", None)
    if chain_needs_materialize(existing):
        invoice.approval_chain = empty_chain(
            tenant_id=tenant_id,
            module_key=module_key,
            amount=amount,
            policy=policy,
        )
        return True
    if not _pending_chain_without_approvals(existing):
        return False
    refreshed = empty_chain(
        tenant_id=tenant_id,
        module_key=module_key,
        amount=amount,
        policy=policy,
    )
    if _policy_chain_signature(existing) == _policy_chain_signature(refreshed):
        return False
    invoice.approval_chain = refreshed
    return True


def record_approval(
    chain: dict[str, Any] | None,
    *,
    tenant_id: uuid.UUID,
    module_key: str,
    user_id: int,
    role: str,
    name: str,
    amount: Any = None,
    policy: Any | None = None,
) -> dict[str, Any]:
    """Append / advance amount-tier document approval; same user re-click is idempotent."""
    if policy is None:
        policy = load_policy_for_tenant(tenant_id)
    tiers = [t.model_dump() for t in policy.amount_approval_tiers]
    limits = dict(policy.approval_limits or {})

    if not isinstance(chain, dict) or not chain or not chain.get("steps"):
        base = build_chain_from_amount(
            tenant_id=tenant_id,
            module_key=module_key,
            amount=amount,
            tiers=tiers,
        )
    elif _pending_chain_without_approvals(chain):
        refreshed = build_chain_from_amount(
            tenant_id=tenant_id,
            module_key=module_key,
            amount=amount,
            tiers=tiers,
        )
        if _policy_chain_signature(chain) != _policy_chain_signature(refreshed):
            base = refreshed
        else:
            base = deepcopy(chain)
            base["module"] = module_key
            if amount is not None:
                base["amount"] = float(amount)
    else:
        base = deepcopy(chain)
        base["module"] = module_key
        if amount is not None:
            base["amount"] = float(amount) if amount is not None else base.get("amount")

    # Idempotent: if this user already approved a document step, return as-is
    for step in base.get("steps") or []:
        if (
            isinstance(step, dict)
            and step.get("kind") == "document"
            and step.get("status") == "approved"
            and step.get("user_id") is not None
            and int(step["user_id"]) == int(user_id)
        ):
            return base

    try:
        require_actor_within_approval_limit(limits, role, amount)
        require_actor_for_current_step(base, role)
        return apply_document_approval(
            base, user_id=user_id, role=role, name=name
        )
    except AmountTierApprovalError as exc:
        raise ApprovalQuorumForbiddenError(str(exc)) from exc


def escalate_approval_chain(
    chain: dict[str, Any] | None,
    *,
    note: str | None = None,
    actor_role: str | None = None,
    actor_name: str | None = None,
) -> dict[str, Any]:
    try:
        return escalate_current_document_step(
            chain,
            note=note,
            actor_role=actor_role,
            actor_name=actor_name,
        )
    except AmountTierApprovalError as exc:
        raise ApprovalQuorumForbiddenError(str(exc)) from exc


def clear_chain() -> None:
    """Helper sentinel — callers set the column to None."""
    return None
