"""Canonical per-tenant role slugs and privilege-matrix mapping."""

from __future__ import annotations

import enum

from app.models.user import SUPER_ADMIN_ROLE, UserRole

APPROVAL_ACTIONS: tuple[str, ...] = (
    "View",
    "Comment",
    "Approve",
    "Reject",
    "Post",
    "Edit Policy",
    "Manage Users",
)

# Display labels used as privilege-matrix row keys (must stay in sync with frontend).
APPROVAL_ROLES: tuple[str, ...] = (
    "Admin",
    "Functional manager",
    "Functional supervisor",
    "Finance head",
    "Bookkeeper",
    "Auditor",
    "User",
)


class TenantRole(str, enum.Enum):
    ADMIN = "admin"
    FUNCTIONAL_MANAGER = "functional_manager"
    FUNCTIONAL_SUPERVISOR = "functional_supervisor"
    FINANCE_HEAD = "finance_head"
    BOOKKEEPER = "bookkeeper"
    AUDITOR = "auditor"
    USER = "user"


# Finance roles that may request unmasked account / BSB / IBAN over the API.
BANK_REVEAL_ROLES: frozenset[str] = frozenset(
    {
        TenantRole.ADMIN.value,
        TenantRole.FINANCE_HEAD.value,
        TenantRole.BOOKKEEPER.value,
        UserRole.ADMIN.value,
    }
)


_MATRIX_ROW_BY_SLUG: dict[str, str] = {
    TenantRole.ADMIN.value: "Admin",
    TenantRole.FUNCTIONAL_MANAGER.value: "Functional manager",
    TenantRole.FUNCTIONAL_SUPERVISOR.value: "Functional supervisor",
    TenantRole.FINANCE_HEAD.value: "Finance head",
    TenantRole.BOOKKEEPER.value: "Bookkeeper",
    TenantRole.AUDITOR.value: "Auditor",
    TenantRole.USER.value: "User",
    # Legacy aliases (pre-privilege-matrix expansion)
    UserRole.MEMBER.value: "Functional manager",
    "member": "Functional manager",
    "approver": "Functional manager",
    "viewer": "User",
}

_LEGACY_ALIASES: dict[str, TenantRole] = {
    UserRole.MEMBER.value: TenantRole.FUNCTIONAL_MANAGER,
    "member": TenantRole.FUNCTIONAL_MANAGER,
    "approver": TenantRole.FUNCTIONAL_MANAGER,
    "viewer": TenantRole.USER,
}


def normalize_tenant_role(raw: str | None) -> TenantRole | None:
    if not raw:
        return None
    slug = raw.strip().lower()
    if slug in _LEGACY_ALIASES:
        return _LEGACY_ALIASES[slug]
    try:
        return TenantRole(slug)
    except ValueError:
        return None


def matrix_row_for_role(raw: str) -> str:
    if raw == SUPER_ADMIN_ROLE:
        return "Admin"
    slug = raw.strip().lower()
    if slug in _MATRIX_ROW_BY_SLUG:
        return _MATRIX_ROW_BY_SLUG[slug]
    return "User"


def format_tenant_role_label(raw: str) -> str:
    """Human-readable role label for emails and UI."""
    return matrix_row_for_role(raw)


def tenant_role_to_user_role(raw: str) -> UserRole:
    """Map membership slug to legacy users.role enum for row sync."""
    normalized = normalize_tenant_role(raw)
    if normalized == TenantRole.ADMIN:
        return UserRole.ADMIN
    if raw == SUPER_ADMIN_ROLE:
        return UserRole.SUPER_ADMIN
    return UserRole.MEMBER


def is_valid_tenant_role(raw: str) -> bool:
    return normalize_tenant_role(raw) is not None or raw == SUPER_ADMIN_ROLE
