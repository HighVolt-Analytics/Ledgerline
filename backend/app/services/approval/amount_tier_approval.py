"""Amount-tier role approval matrix (document steps + payment approval)."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
import uuid

from app.tenant_roles import TenantRole, format_tenant_role_label, normalize_tenant_role

# Hierarchy for escalation: higher index can cover lower required roles.
ROLE_RANK: dict[str, int] = {
    TenantRole.EMPLOYEE.value: 0,
    TenantRole.MANAGER.value: 1,
    TenantRole.DEPARTMENT_HEAD.value: 2,
    TenantRole.FINANCE_MANAGER.value: 3,
    TenantRole.CFO.value: 4,
    TenantRole.DIRECTOR.value: 5,
    TenantRole.ADMIN.value: 6,
}

MATRIX_ROLE_LABELS: tuple[str, ...] = (
    "Manager",
    "Department Head",
    "Finance Manager",
    "CFO",
    "Director",
    "Admin",
)

_LABEL_TO_SLUG: dict[str, str] = {
    "Manager": TenantRole.MANAGER.value,
    "Department Head": TenantRole.DEPARTMENT_HEAD.value,
    "Finance Manager": TenantRole.FINANCE_MANAGER.value,
    "CFO": TenantRole.CFO.value,
    "Director": TenantRole.DIRECTOR.value,
    "Admin": TenantRole.ADMIN.value,
}

DEFAULT_AMOUNT_APPROVAL_TIERS: list[dict[str, Any]] = [
    {
        "id": "tier-0-5k",
        "min_amount": 0,
        "max_amount": 5000,
        "approval_1": "Manager",
        "approval_2": None,
        "approval_3": None,
    },
    {
        "id": "tier-5k-20k",
        "min_amount": 5001,
        "max_amount": 20000,
        "approval_1": "Manager",
        "approval_2": "Department Head",
        "approval_3": None,
    },
    {
        "id": "tier-20k-50k",
        "min_amount": 20001,
        "max_amount": 50000,
        "approval_1": "Department Head",
        "approval_2": "Finance Manager",
        "approval_3": None,
    },
    {
        "id": "tier-50k-250k",
        "min_amount": 50001,
        "max_amount": 250000,
        "approval_1": "Department Head",
        "approval_2": "Finance Manager",
        "approval_3": "CFO",
    },
    {
        "id": "tier-250k-plus",
        "min_amount": 250001,
        "max_amount": None,
        "approval_1": "Finance Manager",
        "approval_2": "CFO",
        "approval_3": "Director",
    },
]


class AmountTierApprovalError(PermissionError):
    """Actor cannot cover the current approval step."""


def _to_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        if isinstance(value, Decimal):
            return float(value)
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalize_role_label(raw: Any) -> str | None:
    if raw is None or raw == "" or raw == "—":
        return None
    text = str(raw).strip()
    if not text:
        return None
    if text in MATRIX_ROLE_LABELS:
        return text
    normalized = normalize_tenant_role(text)
    if normalized is None:
        # Try label via slug map reverse
        slug = text.lower().replace(" ", "_")
        for label, s in _LABEL_TO_SLUG.items():
            if s == slug:
                return label
        return None
    return format_tenant_role_label(normalized.value)


def normalize_amount_approval_tiers(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list) or not raw:
        return deepcopy(DEFAULT_AMOUNT_APPROVAL_TIERS)
    out: list[dict[str, Any]] = []
    for idx, row in enumerate(raw):
        if not isinstance(row, dict):
            continue
        min_amount = _to_float(row.get("min_amount"))
        if min_amount is None or min_amount < 0:
            min_amount = 0.0
        max_amount = _to_float(row.get("max_amount"))
        if max_amount is not None and max_amount < min_amount:
            max_amount = min_amount
        tier_id = str(row.get("id") or f"tier-{idx}").strip() or f"tier-{idx}"
        out.append(
            {
                "id": tier_id,
                "min_amount": min_amount,
                "max_amount": max_amount,
                "approval_1": _normalize_role_label(row.get("approval_1")),
                "approval_2": _normalize_role_label(row.get("approval_2")),
                "approval_3": _normalize_role_label(row.get("approval_3")),
            }
        )
    return out or deepcopy(DEFAULT_AMOUNT_APPROVAL_TIERS)


def role_slug_for_label(label: str | None) -> str | None:
    if not label:
        return None
    return _LABEL_TO_SLUG.get(label) or (
        normalize_tenant_role(label).value if normalize_tenant_role(label) else None
    )


def role_rank(raw: str | None) -> int:
    if not raw:
        return -1
    normalized = normalize_tenant_role(raw)
    if normalized is not None:
        return ROLE_RANK.get(normalized.value, -1)
    label = _normalize_role_label(raw)
    slug = role_slug_for_label(label)
    return ROLE_RANK.get(slug or "", -1)


def next_higher_role_label(label: str | None) -> str | None:
    slug = role_slug_for_label(label)
    if not slug:
        return "Manager"
    current = ROLE_RANK.get(slug, -1)
    for candidate in (
        TenantRole.MANAGER,
        TenantRole.DEPARTMENT_HEAD,
        TenantRole.FINANCE_MANAGER,
        TenantRole.CFO,
        TenantRole.DIRECTOR,
        TenantRole.ADMIN,
    ):
        if ROLE_RANK[candidate.value] > current:
            return format_tenant_role_label(candidate.value)
    return "Admin"


def find_tier_for_amount(
    tiers: list[dict[str, Any]], amount: float | Decimal | None
) -> dict[str, Any]:
    tiers = normalize_amount_approval_tiers(tiers)
    amt = _to_float(amount)
    if amt is None:
        amt = 0.0
    # Prefer inclusive ranges; last open-ended tier catches the rest.
    matched = tiers[0]
    for tier in tiers:
        lo = float(tier["min_amount"])
        hi = tier["max_amount"]
        if hi is None:
            if amt >= lo:
                matched = tier
        else:
            if lo <= amt <= float(hi):
                return tier
            if amt >= lo:
                matched = tier
    return matched


@dataclass(frozen=True)
class ResolvedStep:
    index: int
    key: str
    role: str
    kind: str  # document | payment


def resolve_steps_for_amount(
    tiers: list[dict[str, Any]], amount: float | Decimal | None
) -> tuple[dict[str, Any], list[ResolvedStep]]:
    tier = find_tier_for_amount(tiers, amount)
    steps: list[ResolvedStep] = []
    for key, kind in (
        ("approval_1", "document"),
        ("approval_2", "document"),
        ("approval_3", "payment"),
    ):
        role = tier.get(key)
        if role:
            steps.append(
                ResolvedStep(index=len(steps), key=key, role=str(role), kind=kind)
            )
    return tier, steps


def document_steps(steps: list[ResolvedStep] | list[dict[str, Any]]) -> list[Any]:
    out = []
    for step in steps:
        kind = step.kind if isinstance(step, ResolvedStep) else step.get("kind")
        if kind == "document":
            out.append(step)
    return out


def payment_step_role(
    tiers: list[dict[str, Any]], amount: float | Decimal | None
) -> str | None:
    _, steps = resolve_steps_for_amount(tiers, amount)
    for step in steps:
        if step.kind == "payment":
            return step.role
    return None


def build_chain_from_amount(
    *,
    tenant_id: uuid.UUID,
    module_key: str,
    amount: float | Decimal | None,
    tiers: list[dict[str, Any]],
) -> dict[str, Any]:
    del tenant_id
    tier, steps = resolve_steps_for_amount(tiers, amount)
    doc = document_steps(steps)
    return {
        "module": module_key,
        "mode": "amount_tier",
        "required": max(1, len(doc)) if doc else 1,
        "amount": _to_float(amount),
        "tier_id": tier.get("id"),
        "steps": [
            {
                "index": s.index,
                "key": s.key,
                "role": s.role,
                "kind": s.kind,
                "status": "pending",
                "escalated_to_role": None,
                "user_id": None,
                "name": None,
                "at": None,
            }
            for s in steps
        ],
        "approvals": [],
    }


def effective_step_role(step: dict[str, Any]) -> str:
    return str(step.get("escalated_to_role") or step.get("role") or "")


def current_document_step(chain: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(chain, dict):
        return None
    for step in chain.get("steps") or []:
        if not isinstance(step, dict):
            continue
        if step.get("kind") != "document":
            continue
        if step.get("status") != "approved":
            return step
    return None


def actor_can_cover_role(actor_role: str | None, required_label: str | None) -> bool:
    if role_rank(actor_role) < 0:
        return False
    if not required_label:
        return True
    return role_rank(actor_role) >= role_rank(required_label)


def require_actor_for_current_step(chain: dict[str, Any] | None, actor_role: str | None) -> None:
    step = current_document_step(chain)
    if step is None:
        # No pending document step — allow pool members (legacy / complete)
        return
    required = effective_step_role(step)
    if not actor_can_cover_role(actor_role, required):
        raise AmountTierApprovalError(
            f"Current step requires {required} or higher. "
            "Escalate to a higher role if you cannot approve."
        )


def escalate_current_document_step(
    chain: dict[str, Any] | None,
    *,
    note: str | None = None,
    actor_role: str | None = None,
    actor_name: str | None = None,
) -> dict[str, Any]:
    """Raise the pending document step to the next higher role."""
    if not isinstance(chain, dict) or not chain:
        raise AmountTierApprovalError("Nothing to escalate — start approval first")
    base = deepcopy(chain)
    step = current_document_step(base)
    if step is None:
        raise AmountTierApprovalError("All document approval steps are already complete")
    current = effective_step_role(step)
    higher = next_higher_role_label(current)
    step["escalated_to_role"] = higher
    step["escalated"] = True
    history = base.get("escalations")
    if not isinstance(history, list):
        history = []
    history.append(
        {
            "from_role": current,
            "to_role": higher,
            "note": (note or "").strip() or None,
            "by_role": (actor_role or "").strip() or None,
            "by_name": (actor_name or "").strip() or None,
            "at": datetime.now(timezone.utc).isoformat(),
            "step_key": step.get("key"),
        }
    )
    base["escalations"] = history
    # Keep steps list in sync (step is a reference into base["steps"])
    return base


def apply_document_approval(
    chain: dict[str, Any],
    *,
    user_id: int,
    role: str,
    name: str,
) -> dict[str, Any]:
    """Mark the current document step approved and append legacy approvals entry."""
    base = deepcopy(chain)
    require_actor_for_current_step(base, role)
    step = current_document_step(base)
    now = datetime.now(timezone.utc).isoformat()
    if step is not None:
        required_label = effective_step_role(step)
        step["status"] = "approved"
        step["user_id"] = int(user_id)
        step["name"] = (name or "").strip() or f"User {user_id}"
        # Keep matrix role label on the step; actor slug goes on actor_role.
        step["required_role"] = step.get("required_role") or step.get("role")
        step["role"] = step.get("required_role") or required_label
        step["actor_role"] = (role or "").strip().lower() or "unknown"
        step["at"] = now
        step["covered_role"] = required_label

    approvals = [
        a for a in (base.get("approvals") or []) if isinstance(a, dict)
    ]
    existing_ids = {int(a["user_id"]) for a in approvals if a.get("user_id") is not None}
    if int(user_id) not in existing_ids:
        approvals.append(
            {
                "user_id": int(user_id),
                "role": (role or "").strip().lower() or "unknown",
                "name": (name or "").strip() or f"User {user_id}",
                "at": now,
                "step_key": step.get("key") if step else None,
            }
        )
    base["approvals"] = approvals

    doc_pending = current_document_step(base) is not None
    doc_total = len(
        [
            s
            for s in (base.get("steps") or [])
            if isinstance(s, dict) and s.get("kind") == "document"
        ]
    )
    base["required"] = max(1, doc_total) if doc_total else int(base.get("required") or 1)
    base["mode"] = "amount_tier"
    if not doc_pending and doc_total == 0:
        # Fallback: no configured document steps — single approval satisfies
        base["required"] = 1
    return base


def document_quorum_met(chain: dict[str, Any] | None) -> bool:
    if not isinstance(chain, dict):
        return False
    steps = [
        s
        for s in (chain.get("steps") or [])
        if isinstance(s, dict) and s.get("kind") == "document"
    ]
    if not steps:
        # Legacy chains without steps
        try:
            required = int(chain.get("required") or 0)
        except (TypeError, ValueError):
            required = 0
        approvals = [
            a for a in (chain.get("approvals") or []) if isinstance(a, dict)
        ]
        ids = {int(a["user_id"]) for a in approvals if a.get("user_id") is not None}
        return required > 0 and len(ids) >= required
    return all(s.get("status") == "approved" for s in steps)


def require_payment_approver_role(
    tiers: list[dict[str, Any]],
    amount: float | Decimal | None,
    actor_role: str | None,
) -> None:
    required = payment_step_role(tiers, amount)
    if not required:
        return
    if not actor_can_cover_role(actor_role, required):
        raise AmountTierApprovalError(
            f"Payment approval requires {required} or higher for this amount"
        )
