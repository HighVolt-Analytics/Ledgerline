"""Tenant isolation after switching active organisation."""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.invoice import Invoice, InvoiceStatus
from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.services.auth_service import create_access_token, hash_password
from app.services.membership_service import ensure_membership
from app.tenant_ids import TESTING_TENANT_UUID


async def _seed_multi_tenant_user(
    db_session: AsyncSession,
    *,
    email: str,
    other_tenant: Tenant,
) -> tuple[User, Invoice, Invoice]:
    user = User(
        tenant_id=TESTING_TENANT_UUID,
        email=email,
        password_hash=hash_password("password123"),
        full_name="Switcher",
        role=UserRole.ADMIN,
        is_active=True,
    )
    db_session.add(user)
    await db_session.flush()
    await ensure_membership(
        db_session, user_id=user.id, tenant_id=TESTING_TENANT_UUID, role="admin"
    )
    await ensure_membership(
        db_session, user_id=user.id, tenant_id=other_tenant.id, role="admin"
    )
    home_inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.PENDING,
        currency="AUD",
    )
    other_inv = Invoice(
        tenant_id=other_tenant.id,
        status=InvoiceStatus.PENDING,
        currency="AUD",
    )
    db_session.add_all([home_inv, other_inv])
    await db_session.commit()
    return user, home_inv, other_inv


@pytest.mark.asyncio
async def test_switch_tenant_limits_invoice_list_to_target_tenant(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AUTH_REQUIRED", "true")
    get_settings.cache_clear()

    other = Tenant(
        id=uuid.uuid4(),
        name="Other Org",
        slug="other-org-switch",
        is_active=True,
    )
    db_session.add(other)
    await db_session.flush()

    user, home_inv, other_inv = await _seed_multi_tenant_user(
        db_session,
        email="switcher@test.com",
        other_tenant=other,
    )

    home_token = create_access_token(
        user_id=user.id,
        tenant_id=TESTING_TENANT_UUID,
        tenant_slug="testing",
        email=user.email,
        role="admin",
    )
    res_home = await client.get(
        "/api/invoices",
        headers={"Authorization": f"Bearer {home_token}"},
    )
    assert res_home.status_code == 200
    home_ids = {row["id"] for row in res_home.json()["data"]}
    assert home_inv.id in home_ids
    assert other_inv.id not in home_ids

    switch = await client.post(
        "/api/auth/switch-tenant",
        headers={"Authorization": f"Bearer {home_token}"},
        json={"tenant_id": str(other.id)},
    )
    assert switch.status_code == 200
    switched_token = switch.json()["data"]["access_token"]

    res_other = await client.get(
        "/api/invoices",
        headers={"Authorization": f"Bearer {switched_token}"},
    )
    assert res_other.status_code == 200
    other_ids = {row["id"] for row in res_other.json()["data"]}
    assert other_inv.id in other_ids
    assert home_inv.id not in other_ids
