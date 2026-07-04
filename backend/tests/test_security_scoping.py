
from app.tenant_ids import PLATFORM_TENANT_UUID, TESTING_TENANT_UUID
"""Org-scoped API access (IDOR prevention)."""

from datetime import date
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.invoice import Invoice, InvoiceStatus
from app.models.journal import EntryType, JournalEntry
from app.models.line_item import LineItem
from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.services.auth.auth_service import create_access_token, hash_password
from app.services.auth.membership_service import ensure_membership


@pytest.mark.asyncio
async def test_line_items_cross_org_returns_404(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AUTH_REQUIRED", "true")
    get_settings.cache_clear()

    db_session.add(Tenant(id=PLATFORM_TENANT_UUID, name="Other Org", slug="other-org"))
    inv = Invoice(tenant_id=TESTING_TENANT_UUID, status=InvoiceStatus.PENDING, currency="AUD")
    db_session.add(inv)
    await db_session.flush()
    db_session.add(
        LineItem(
            tenant_id=TESTING_TENANT_UUID,
            invoice_id=inv.id,
            description="Secret line",
            qty=Decimal("1"),
            unit_price=Decimal("100"),
            amount=Decimal("100"),
        )
    )

    outsider = User(
        tenant_id=PLATFORM_TENANT_UUID,
        email="outsider@other.com",
        password_hash=hash_password("outsiderpass1"),
        full_name="Outsider",
        role=UserRole.MEMBER,
    )
    db_session.add(outsider)
    await db_session.flush()
    await ensure_membership(db_session, user_id=outsider.id, tenant_id=PLATFORM_TENANT_UUID)

    token = create_access_token(
        user_id=outsider.id,
        tenant_id=PLATFORM_TENANT_UUID,
        tenant_slug="other-org",
        email=outsider.email,
        role=outsider.role.value,
    )
    res = await client.get(
        f"/api/invoices/{inv.id}/line-items",
        headers={"Authorization": f"Bearer {token}", "X-Tenant-Id": str(PLATFORM_TENANT_UUID)},
    )
    assert res.status_code == 404

    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_journal_entries_cross_org_returns_404(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AUTH_REQUIRED", "true")
    get_settings.cache_clear()

    db_session.add(Tenant(id=PLATFORM_TENANT_UUID, name="Other Org", slug="other-org"))
    inv = Invoice(tenant_id=TESTING_TENANT_UUID, status=InvoiceStatus.PROCESSED, currency="AUD")
    db_session.add(inv)
    await db_session.flush()
    db_session.add(
        JournalEntry(
            tenant_id=TESTING_TENANT_UUID,
            invoice_id=inv.id,
            date=date(2026, 6, 1),
            account_code="5000",
            account_name="Expenses",
            debit=Decimal("100"),
            credit=Decimal("0"),
            entry_type=EntryType.DEBIT,
        )
    )

    outsider = User(
        tenant_id=PLATFORM_TENANT_UUID,
        email="outsider2@other.com",
        password_hash=hash_password("outsiderpass1"),
        full_name="Outsider",
        role=UserRole.MEMBER,
    )
    db_session.add(outsider)
    await db_session.flush()
    await ensure_membership(db_session, user_id=outsider.id, tenant_id=PLATFORM_TENANT_UUID)

    token = create_access_token(
        user_id=outsider.id,
        tenant_id=PLATFORM_TENANT_UUID,
        tenant_slug="other-org",
        email=outsider.email,
        role=outsider.role.value,
    )
    res = await client.get(
        f"/api/invoices/{inv.id}/journal-entries",
        headers={"Authorization": f"Bearer {token}", "X-Tenant-Id": str(PLATFORM_TENANT_UUID)},
    )
    assert res.status_code == 404

    get_settings.cache_clear()
