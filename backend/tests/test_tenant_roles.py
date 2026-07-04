"""Tenant role slug mapping and privilege matrix wiring."""

import uuid

import pytest

from app.api.deps import AuthContext
from app.services.auth.privilege_service import (
    matrix_role_for_context,
    permissions_for_role,
    user_has_privilege,
)
from app.tenant_ids import TESTING_TENANT_UUID
from app.tenant_roles import (
    TenantRole,
    matrix_row_for_role,
    normalize_tenant_role,
    tenant_role_to_user_role,
)
from app.models.user import UserRole


def test_normalize_legacy_member_to_approver() -> None:
    assert normalize_tenant_role("member") == TenantRole.APPROVER


@pytest.mark.parametrize(
    ("slug", "matrix_row"),
    [
        ("admin", "Admin"),
        ("approver", "Approver"),
        ("bookkeeper", "Bookkeeper"),
        ("viewer", "Viewer"),
        ("auditor", "Auditor"),
        ("member", "Approver"),
    ],
)
def test_matrix_row_for_all_roles(slug: str, matrix_row: str) -> None:
    assert matrix_row_for_role(slug) == matrix_row


def test_tenant_role_to_user_role_maps_non_admin_to_member_enum() -> None:
    assert tenant_role_to_user_role("bookkeeper") == UserRole.MEMBER
    assert tenant_role_to_user_role("admin") == UserRole.ADMIN


def test_bookkeeper_cannot_approve_with_default_matrix() -> None:
    ctx = AuthContext(
        user_id=1,
        tenant_id=TESTING_TENANT_UUID,
        tenant_slug="testing",
        email="bk@test.com",
        role="bookkeeper",
    )
    assert matrix_role_for_context(ctx) == "Bookkeeper"
    assert user_has_privilege(ctx, "View") is True
    assert user_has_privilege(ctx, "Approve") is False


def test_viewer_cannot_comment_with_default_matrix() -> None:
    perms = permissions_for_role(TESTING_TENANT_UUID, "viewer")
    assert perms["View"] is True
    assert perms["Comment"] is False


def test_unknown_role_defaults_to_viewer_matrix_row() -> None:
    assert matrix_row_for_role("unknown-role") == "Viewer"
