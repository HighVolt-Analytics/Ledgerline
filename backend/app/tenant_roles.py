"""Canonical per-tenant role slugs and privilege-matrix mapping."""

from __future__ import annotations

import enum

from app.models.user import SUPER_ADMIN_ROLE, UserRole

APPROVAL_ACTIONS: tuple[str, ...] = (
    "View",
    "Comment",
    "Approve",
    "Reject",
    "Publish",
    "Edit Policy",
    "Manage Users",
)


class TenantRole(str, enum.Enum):
    ADMIN = "admin"
    APPROVER = "approver"
    BOOKKEEPER = "bookkeeper"
    VIEWER = "viewer"
    AUDITOR = "auditor"


_MATRIX_ROW_BY_SLUG: dict[str, str] = {
    TenantRole.ADMIN.value: "Admin",
    TenantRole.APPROVER.value: "Approver",
    TenantRole.BOOKKEEPER.value: "Bookkeeper",
    TenantRole.VIEWER.value: "Viewer",
    TenantRole.AUDITOR.value: "Auditor",
    # Legacy aliases
    UserRole.MEMBER.value: "Approver",
    "member": "Approver",
}

_LEGACY_ALIASES: dict[str, TenantRole] = {
    UserRole.MEMBER.value: TenantRole.APPROVER,
    "member": TenantRole.APPROVER,
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
    return "Viewer"


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
