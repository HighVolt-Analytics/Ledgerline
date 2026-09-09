"""Canonical per-tenant role slugs and privilege-matrix mapping."""

from __future__ import annotations

import enum

from app.models.user import SUPER_ADMIN_ROLE, UserRole

# Approve covers approve + reject + post (single privilege-matrix column).
APPROVAL_ACTIONS: tuple[str, ...] = (
    "View",
    "Comment",
    "Approve",
    "Edit Policy",
    "Manage Users",
)

# Legacy matrix / require_privilege action names that map onto Approve.
APPROVE_ALIASES: frozenset[str] = frozenset({"Approve", "Reject", "Post", "Publish"})

# Display labels used as privilege-matrix row keys (must stay in sync with frontend).
# Order: lowest privilege → highest (Admin last).
APPROVAL_ROLES: tuple[str, ...] = (
    "Employee",
    "Manager",
    "Department Head",
    "Finance Manager",
    "CFO",
    "Director",
    "Admin",
)


class TenantRole(str, enum.Enum):
    EMPLOYEE = "employee"
    MANAGER = "manager"
    DEPARTMENT_HEAD = "department_head"
    FINANCE_MANAGER = "finance_manager"
    CFO = "cfo"
    DIRECTOR = "director"
    ADMIN = "admin"


# Finance roles that may request unmasked account / BSB / IBAN over the API.
BANK_REVEAL_ROLES: frozenset[str] = frozenset(
    {
        TenantRole.ADMIN.value,
        TenantRole.FINANCE_MANAGER.value,
        TenantRole.CFO.value,
        TenantRole.DIRECTOR.value,
        UserRole.ADMIN.value,
    }
)


_MATRIX_ROW_BY_SLUG: dict[str, str] = {
    TenantRole.EMPLOYEE.value: "Employee",
    TenantRole.MANAGER.value: "Manager",
    TenantRole.DEPARTMENT_HEAD.value: "Department Head",
    TenantRole.FINANCE_MANAGER.value: "Finance Manager",
    TenantRole.CFO.value: "CFO",
    TenantRole.DIRECTOR.value: "Director",
    TenantRole.ADMIN.value: "Admin",
    # Legacy aliases (pre org-role rename)
    "user": "Employee",
    "functional_manager": "Manager",
    "functional_supervisor": "Department Head",
    "finance_head": "Finance Manager",
    "bookkeeper": "CFO",
    "auditor": "Director",
    UserRole.MEMBER.value: "Manager",
    "member": "Manager",
    "approver": "Manager",
    "viewer": "Employee",
}

_LEGACY_ALIASES: dict[str, TenantRole] = {
    "user": TenantRole.EMPLOYEE,
    "functional_manager": TenantRole.MANAGER,
    "functional_supervisor": TenantRole.DEPARTMENT_HEAD,
    "finance_head": TenantRole.FINANCE_MANAGER,
    "bookkeeper": TenantRole.CFO,
    "auditor": TenantRole.DIRECTOR,
    UserRole.MEMBER.value: TenantRole.MANAGER,
    "member": TenantRole.MANAGER,
    "approver": TenantRole.MANAGER,
    "viewer": TenantRole.EMPLOYEE,
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
    return "Employee"


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
