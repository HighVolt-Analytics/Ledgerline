"""Membership switcher visibility rules."""

import uuid

from app.models.user import SUPER_ADMIN_ROLE
from app.services.membership_enumeration import (
    TenantMembershipAccount,
    filter_switchable_memberships,
    membership_is_switchable,
)


def _membership(*, is_platform: bool, role: str) -> TenantMembershipAccount:
    tid = uuid.uuid4()
    return TenantMembershipAccount(
        user_id=1,
        tenant_id=tid,
        tenant_name="LedgerLink Platform" if is_platform else "Testing",
        tenant_slug="platform" if is_platform else "testing",
        role=role,
        default_tenant=False,
        is_platform=is_platform,
    )


def test_client_tenant_always_switchable() -> None:
    m = _membership(is_platform=False, role="admin")
    assert membership_is_switchable(m) is True


def test_platform_tenant_only_for_super_admin() -> None:
    platform_viewer = _membership(is_platform=True, role="viewer")
    platform_super = _membership(is_platform=True, role=SUPER_ADMIN_ROLE)

    assert membership_is_switchable(platform_viewer) is False
    assert membership_is_switchable(platform_super) is True


def test_platform_shadow_membership_not_switchable() -> None:
    shadow = TenantMembershipAccount(
        user_id=2,
        tenant_id=uuid.uuid4(),
        tenant_name="Dhiren",
        tenant_slug="dhiren",
        role="admin",
        default_tenant=False,
        is_platform=False,
        is_platform_shadow=True,
    )
    assert membership_is_switchable(shadow) is False
    assert filter_switchable_memberships([shadow]) == []


def test_filter_drops_stray_platform_memberships() -> None:
    rows = [
        _membership(is_platform=False, role="admin"),
        _membership(is_platform=True, role="viewer"),
        _membership(is_platform=False, role="approver"),
    ]
    filtered = filter_switchable_memberships(rows)
    assert len(filtered) == 2
    assert all(not m.is_platform for m in filtered)
