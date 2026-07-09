"""API-level tenant isolation — authenticated users must not see other tenants' data."""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.connected_mailbox import ConnectedMailbox
from app.models.customer import CustomerRegistry
from app.models.invoice import Invoice, InvoiceStatus
from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.models.vendor import VendorRegistry
from app.services.auth.auth_service import create_access_token, hash_password
from app.services.auth.membership_service import ensure_membership
from app.tenant_ids import TESTING_TENANT_UUID
from tests.auth_test_helpers import tenant_auth_headers
from tests.tenant_page_api_endpoints import (
    TENANT_PAGE_GET_PATHS,
    TENANT_PAGE_GET_PATHS_EXPECT_200,
)


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


def _headers(token: str) -> dict[str, str]:
    return tenant_auth_headers(token, TESTING_TENANT_UUID)


async def _other_tenant(db_session: AsyncSession) -> Tenant:
    other = Tenant(
        id=uuid.uuid4(),
        name="Other Org",
        slug=f"other-org-{uuid.uuid4().hex[:8]}",
        is_active=True,
    )
    db_session.add(other)
    await db_session.flush()
    return other


@pytest.mark.asyncio
async def test_invoice_detail_cross_tenant_returns_404(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AUTH_REQUIRED", "true")
    get_settings.cache_clear()

    user = await _seed_user(db_session, email="iso-detail@test.com")
    other = await _other_tenant(db_session)
    other_inv = Invoice(tenant_id=other.id, status=InvoiceStatus.PENDING, currency="AUD")
    db_session.add(other_inv)
    await db_session.commit()

    token = _token_for(user)
    res = await client.get(f"/api/invoices/{other_inv.id}", headers=_headers(token))
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
    other = await _other_tenant(db_session)
    foreign = Invoice(tenant_id=other.id, status=InvoiceStatus.PENDING, currency="AUD")
    db_session.add_all([own, foreign])
    await db_session.commit()

    token = _token_for(user)
    res = await client.get("/api/invoices", headers=_headers(token))
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
    other = await _other_tenant(db_session)
    await db_session.commit()

    token = _token_for(user)
    res = await client.get(
        "/api/invoices",
        headers=tenant_auth_headers(token, other.id),
    )
    assert res.status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize("path", TENANT_PAGE_GET_PATHS)
async def test_page_get_endpoints_reject_missing_tenant_header(
    anon_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    path: str,
) -> None:
    monkeypatch.setenv("AUTH_REQUIRED", "true")
    get_settings.cache_clear()

    user = await _seed_user(db_session, email=f"iso-missing-{abs(hash(path))}@test.com")
    await db_session.commit()
    token = _token_for(user)

    missing = await anon_client.get(path, headers={"Authorization": f"Bearer {token}"})
    assert missing.status_code == 403, f"{path}: {missing.text}"


@pytest.mark.asyncio
@pytest.mark.parametrize("path", TENANT_PAGE_GET_PATHS)
async def test_page_get_endpoints_reject_spoofed_tenant_header(
    anon_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    path: str,
) -> None:
    monkeypatch.setenv("AUTH_REQUIRED", "true")
    get_settings.cache_clear()

    user = await _seed_user(db_session, email=f"iso-spoof-{abs(hash(path))}@test.com")
    other = await _other_tenant(db_session)
    await db_session.commit()
    token = _token_for(user)

    spoofed = await anon_client.get(path, headers=tenant_auth_headers(token, other.id))
    assert spoofed.status_code == 403, f"{path}: {spoofed.text}"


@pytest.mark.asyncio
@pytest.mark.parametrize("path", TENANT_PAGE_GET_PATHS_EXPECT_200)
async def test_page_get_endpoints_succeed_with_matching_tenant_header(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    path: str,
) -> None:
    monkeypatch.setenv("AUTH_REQUIRED", "true")
    get_settings.cache_clear()

    user = await _seed_user(db_session, email=f"iso-ok-{abs(hash(path))}@test.com")
    await db_session.commit()
    token = _token_for(user)

    ok = await client.get(path, headers=_headers(token))
    assert ok.status_code == 200, f"{path}: {ok.text}"


@pytest.mark.asyncio
async def test_mailbox_cross_tenant_delete_returns_404(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AUTH_REQUIRED", "true")
    get_settings.cache_clear()

    user = await _seed_user(db_session, email="iso-mailbox@test.com")
    other = await _other_tenant(db_session)
    foreign_mb = ConnectedMailbox(
        tenant_id=other.id,
        email="foreign@other-tenant.test",
        display_name="Foreign",
        is_active=True,
    )
    db_session.add(foreign_mb)
    await db_session.commit()

    token = _token_for(user)
    res = await client.delete(
        f"/api/mailboxes/{foreign_mb.id}",
        headers=_headers(token),
    )
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_mailbox_list_excludes_other_tenant(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AUTH_REQUIRED", "true")
    get_settings.cache_clear()

    user = await _seed_user(db_session, email="iso-mailbox-list@test.com")
    own_mb = ConnectedMailbox(
        tenant_id=TESTING_TENANT_UUID,
        email="own@tenant.test",
        display_name="Own",
        is_active=True,
    )
    other = await _other_tenant(db_session)
    foreign_mb = ConnectedMailbox(
        tenant_id=other.id,
        email="vishnu@highvolt.tech",
        display_name="Other Tenant Mailbox",
        is_active=True,
    )
    db_session.add_all([own_mb, foreign_mb])
    await db_session.commit()

    token = _token_for(user)
    res = await client.get("/api/mailboxes", headers=_headers(token))
    assert res.status_code == 200
    emails = {row["email"] for row in res.json()["data"]}
    assert "own@tenant.test" in emails
    assert "vishnu@highvolt.tech" not in emails


@pytest.mark.asyncio
async def test_vendor_cross_tenant_patch_returns_404(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AUTH_REQUIRED", "true")
    get_settings.cache_clear()

    user = await _seed_user(db_session, email="iso-vendor@test.com")
    other = await _other_tenant(db_session)
    foreign_vendor = VendorRegistry(
        tenant_id=other.id,
        vendor_name="Foreign Vendor Pty Ltd",
        vendor_slug="foreign-vendor",
        sender_pattern="foreign@other.test",
    )
    db_session.add(foreign_vendor)
    await db_session.commit()

    token = _token_for(user)
    res = await client.patch(
        f"/api/vendors/{foreign_vendor.id}",
        headers=_headers(token),
        json={"vendor_name": "Hijacked"},
    )
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_customer_cross_tenant_delete_returns_404(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AUTH_REQUIRED", "true")
    get_settings.cache_clear()

    user = await _seed_user(db_session, email="iso-customer@test.com")
    other = await _other_tenant(db_session)
    foreign_customer = CustomerRegistry(
        tenant_id=other.id,
        customer_name="Foreign Customer",
        customer_slug="foreign-customer",
        sender_pattern="customer@other.test",
    )
    db_session.add(foreign_customer)
    await db_session.commit()

    token = _token_for(user)
    res = await client.delete(
        f"/api/customers/{foreign_customer.id}",
        headers=_headers(token),
    )
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_rule_book_config_isolated_per_tenant(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Tenant A JWT must not read tenant B rule book via header spoof (403)."""
    monkeypatch.setenv("AUTH_REQUIRED", "true")
    get_settings.cache_clear()

    user = await _seed_user(db_session, email="iso-rulebook@test.com")
    other = await _other_tenant(db_session)
    await db_session.commit()

    token = _token_for(user)
    ok = await client.get("/api/rule-book/config", headers=_headers(token))
    assert ok.status_code == 200

    spoof = await client.get(
        "/api/rule-book/config",
        headers=tenant_auth_headers(token, other.id),
    )
    assert spoof.status_code == 403


@pytest.mark.asyncio
async def test_invalid_token_with_tenant_header_does_not_fall_back_to_default_org(
    anon_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """Bad/missing JWT must never return default-tenant data on tenant APIs."""
    user = await _seed_user(db_session, email="iso-auth-bypass@test.com")
    await db_session.commit()

    pactify_like = uuid.uuid4()
    headers = {
        "Authorization": "Bearer not-a-valid-jwt",
        "X-Tenant-Id": str(pactify_like),
    }
    res = await anon_client.get("/api/mailboxes", headers=headers)
    assert res.status_code == 401

    res2 = await anon_client.get(
        "/api/mailboxes",
        headers={"X-Tenant-Id": str(TESTING_TENANT_UUID)},
    )
    assert res2.status_code == 401

    res3 = await anon_client.get("/api/mailboxes")
    assert res3.status_code == 401

    token = _token_for(user)
    ok = await anon_client.get("/api/mailboxes", headers=_headers(token))
    assert ok.status_code == 200
