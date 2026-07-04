"""API-level tenant isolation — authenticated users must not see other tenants' data."""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.invoice import Invoice, InvoiceStatus
from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.services.auth.auth_service import create_access_token, hash_password
from app.services.auth.membership_service import ensure_membership
from app.tenant_ids import TESTING_TENANT_UUID


async def _seed_user(db_session: AsyncSession, *, email: str) -> User:
    user = User(
        tenant_id=TESTING_TENANT_UUID,
        email=email,
        password_hash=hash_password("password123"),
        full_name="Isolation Tester",
        role=UserRole.ADMIN,
        is_active=True,
    )
    db_session.add(user)
    await db_session.flush()
    await ensure_membership(
        db_session, user_id=user.id, tenant_id=TESTING_TENANT_UUID, role="admin"
    )
    await db_session.commit()
    return user


def _token_for(user: User) -> str:
    return create_access_token(
        user_id=user.id,
        tenant_id=TESTING_TENANT_UUID,
        tenant_slug="testing",
        email=user.email,
        role="admin",
    )


@pytest.mark.asyncio
async def test_invoice_detail_cross_tenant_returns_404(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AUTH_REQUIRED", "true")
    get_settings.cache_clear()

    user = await _seed_user(db_session, email="iso-detail@test.com")
    other = Tenant(
        id=uuid.uuid4(),
        name="Other Org",
        slug="other-org-isolation",
        is_active=True,
    )
    db_session.add(other)
    other_inv = Invoice(tenant_id=other.id, status=InvoiceStatus.PENDING, currency="AUD")
    db_session.add(other_inv)
    await db_session.commit()

    token = _token_for(user)
    res = await client.get(
        f"/api/invoices/{other_inv.id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_invoice_list_excludes_other_tenant(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AUTH_REQUIRED", "true")
    get_settings.cache_clear()

    user = await _seed_user(db_session, email="iso-list@test.com")
    own = Invoice(tenant_id=TESTING_TENANT_UUID, status=InvoiceStatus.PENDING, currency="AUD")
    other = Tenant(
        id=uuid.uuid4(),
        name="Rival",
        slug="rival-org-isolation",
        is_active=True,
    )
    db_session.add(other)
    foreign = Invoice(tenant_id=other.id, status=InvoiceStatus.PENDING, currency="AUD")
    db_session.add_all([own, foreign])
    await db_session.commit()

    token = _token_for(user)
    res = await client.get(
        "/api/invoices",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 200
    ids = {row["id"] for row in res.json()["data"]}
    assert own.id in ids
    assert foreign.id not in ids


@pytest.mark.asyncio
async def test_x_tenant_id_header_mismatch_rejected(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AUTH_REQUIRED", "true")
    get_settings.cache_clear()

    user = await _seed_user(db_session, email="iso-header@test.com")
    other = Tenant(
        id=uuid.uuid4(),
        name="Spoof Target",
        slug="spoof-target",
        is_active=True,
    )
    db_session.add(other)
    await db_session.commit()

    token = _token_for(user)
    res = await client.get(
        "/api/invoices",
        headers={
            "Authorization": f"Bearer {token}",
            "X-Tenant-Id": str(other.id),
        },
    )
    assert res.status_code == 403
