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


def test_normalize_legacy_member_to_manager() -> None:
    assert normalize_tenant_role("member") == TenantRole.MANAGER
    assert normalize_tenant_role("approver") == TenantRole.MANAGER
    assert normalize_tenant_role("viewer") == TenantRole.EMPLOYEE
    assert normalize_tenant_role("functional_manager") == TenantRole.MANAGER
    assert normalize_tenant_role("bookkeeper") == TenantRole.CFO
    assert normalize_tenant_role("user") == TenantRole.EMPLOYEE


@pytest.mark.parametrize(
    ("slug", "matrix_row"),
    [
        ("admin", "Admin"),
        ("employee", "Employee"),
        ("manager", "Manager"),
        ("department_head", "Department Head"),
        ("finance_manager", "Finance Manager"),
        ("cfo", "CFO"),
        ("director", "Director"),
        ("functional_manager", "Manager"),
        ("functional_supervisor", "Department Head"),
        ("finance_head", "Finance Manager"),
        ("bookkeeper", "CFO"),
        ("auditor", "Director"),
        ("user", "Employee"),
        ("approver", "Manager"),
        ("viewer", "Employee"),
        ("member", "Manager"),
    ],
)
def test_matrix_row_for_all_roles(slug: str, matrix_row: str) -> None:
    assert matrix_row_for_role(slug) == matrix_row


def test_tenant_role_to_user_role_maps_non_admin_to_member_enum() -> None:
    assert tenant_role_to_user_role("cfo") == UserRole.MEMBER
    assert tenant_role_to_user_role("admin") == UserRole.ADMIN


def test_employee_cannot_approve_with_default_matrix() -> None:
    ctx = AuthContext(
        user_id=1,
        tenant_id=TESTING_TENANT_UUID,
        tenant_slug="testing",
        email="emp@test.com",
        role="employee",
    )
    assert matrix_role_for_context(ctx) == "Employee"
    assert user_has_privilege(ctx, "View") is True
    assert user_has_privilege(ctx, "Approve") is False


def test_cfo_can_approve_with_default_matrix() -> None:
    ctx = AuthContext(
        user_id=2,
        tenant_id=TESTING_TENANT_UUID,
        tenant_slug="testing",
        email="cfo@test.com",
        role="cfo",
    )
    assert matrix_role_for_context(ctx) == "CFO"
    assert user_has_privilege(ctx, "Approve") is True
    # Reject/Post are aliases of Approve
    assert user_has_privilege(ctx, "Reject") is True
    assert user_has_privilege(ctx, "Post") is True


def test_employee_cannot_comment_with_default_matrix() -> None:
    perms = permissions_for_role(TESTING_TENANT_UUID, "employee")
    assert perms["View"] is True
    assert perms["Comment"] is False


def test_department_head_approve_implies_reject_and_post() -> None:
    perms = permissions_for_role(TESTING_TENANT_UUID, "department_head")
    assert perms["Approve"] is True
    assert perms["Reject"] is True
    assert perms["Post"] is True
    from app.tenant_roles import APPROVAL_ACTIONS

    assert "Reject" not in APPROVAL_ACTIONS
    assert "Post" not in APPROVAL_ACTIONS


def test_unknown_role_defaults_to_employee_matrix_row() -> None:
    assert matrix_row_for_role("unknown-role") == "Employee"
