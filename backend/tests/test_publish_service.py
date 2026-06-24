"""Tests for ledger publish service."""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog
from app.models.invoice import Invoice, InvoiceStatus
from app.models.journal import EntryType, JournalEntry
from app.services.billing_io import load_billing_for_tenant, save_billing_for_tenant
from app.services.publish_service import (
    PUBLISH_CREDIT_COST,
    InsufficientCreditsError,
    is_published_to_ledger,
    publish_invoice_to_ledger,
)


@pytest.mark.asyncio
async def test_publish_records_audit_and_charges_credits(
    db_session: AsyncSession,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path / "uploads"))
    from app.config import get_settings

    get_settings.cache_clear()

    inv = Invoice(
        tenant_id=1,
        vendor="Acme",
        invoice_no="PUB-001",
        document_ref="DOC-9",
        invoice_date=date(2026, 6, 1),
        total=Decimal("110.00"),
        status=InvoiceStatus.PROCESSED,
    )
    db_session.add(inv)
    await db_session.flush()
    db_session.add(
        JournalEntry(
            invoice_id=inv.id,
            date=date(2026, 6, 1),
            account_code="6100",
            account_name="Office Expenses",
            debit=Decimal("110.00"),
            credit=Decimal("0"),
            entry_type=EntryType.DEBIT,
        )
    )
    db_session.add(
        JournalEntry(
            invoice_id=inv.id,
            date=date(2026, 6, 1),
            account_code="2000",
            account_name="Accounts Payable",
            debit=Decimal("0"),
            credit=Decimal("110.00"),
            entry_type=EntryType.CREDIT,
        )
    )
    await db_session.commit()

    balance_before = load_billing_for_tenant(1).balance
    published = await publish_invoice_to_ledger(
        db_session,
        inv,
        actor_name="Admin",
        actor_email="admin@example.com",
    )
    await db_session.commit()

    assert published is True
    assert await is_published_to_ledger(db_session, inv.id)
    assert load_billing_for_tenant(1).balance == balance_before - PUBLISH_CREDIT_COST

    row = (
        await db_session.execute(
            select(AuditLog)
            .where(
                AuditLog.invoice_id == inv.id,
                AuditLog.event == "invoice_published_to_ledger",
            )
            .order_by(AuditLog.id.desc())
        )
    ).scalars().first()
    assert row is not None
    assert row.detail is not None
    assert row.detail.get("document_ref") == "DOC-9"
    assert row.detail.get("target") == "workbook"


@pytest.mark.asyncio
async def test_publish_is_idempotent(db_session: AsyncSession, tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path / "uploads"))
    from app.config import get_settings

    get_settings.cache_clear()

    inv = Invoice(
        tenant_id=1,
        vendor="Acme",
        invoice_date=date(2026, 6, 2),
        total=Decimal("50.00"),
        status=InvoiceStatus.PROCESSED,
    )
    db_session.add(inv)
    await db_session.flush()
    db_session.add(
        JournalEntry(
            invoice_id=inv.id,
            date=date(2026, 6, 2),
            account_code="6100",
            account_name="Office Expenses",
            debit=Decimal("50.00"),
            credit=Decimal("0"),
            entry_type=EntryType.DEBIT,
        )
    )
    await db_session.commit()

    balance_before = load_billing_for_tenant(1).balance
    assert await publish_invoice_to_ledger(db_session, inv) is True
    await db_session.commit()
    assert await publish_invoice_to_ledger(db_session, inv) is False
    await db_session.commit()
    assert load_billing_for_tenant(1).balance == balance_before - PUBLISH_CREDIT_COST


@pytest.mark.asyncio
async def test_reprocess_invalidates_stale_publish_flag(
    db_session: AsyncSession,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path / "uploads"))
    from app.config import get_settings
    from app.services.audit_service import log_event

    get_settings.cache_clear()

    inv = Invoice(
        tenant_id=1,
        vendor="Acme",
        invoice_date=date(2026, 6, 4),
        total=Decimal("75.00"),
        status=InvoiceStatus.PROCESSED,
    )
    db_session.add(inv)
    await db_session.flush()
    db_session.add(
        JournalEntry(
            invoice_id=inv.id,
            date=date(2026, 6, 4),
            account_code="6100",
            account_name="Office Expenses",
            debit=Decimal("75.00"),
            credit=Decimal("0"),
            entry_type=EntryType.DEBIT,
        )
    )
    await db_session.commit()

    assert await publish_invoice_to_ledger(db_session, inv) is True
    await db_session.commit()
    assert await is_published_to_ledger(db_session, inv.id) is True

    await log_event(db_session, "invoice_processed", invoice_id=inv.id, detail={"status": "processed"})
    await db_session.commit()

    assert await is_published_to_ledger(db_session, inv.id) is False
    assert await publish_invoice_to_ledger(db_session, inv) is True
    await db_session.commit()
    assert await is_published_to_ledger(db_session, inv.id) is True


@pytest.mark.asyncio
async def test_manual_publish_fails_without_credits(
    db_session: AsyncSession,
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path / "uploads"))
    from app.config import get_settings

    get_settings.cache_clear()
    state = load_billing_for_tenant(1)
    state.balance = 0
    save_billing_for_tenant(1, state)

    inv = Invoice(
        tenant_id=1,
        vendor="Acme",
        invoice_date=date(2026, 6, 3),
        total=Decimal("20.00"),
        status=InvoiceStatus.PROCESSED,
    )
    db_session.add(inv)
    await db_session.flush()
    db_session.add(
        JournalEntry(
            invoice_id=inv.id,
            date=date(2026, 6, 3),
            account_code="6100",
            account_name="Office Expenses",
            debit=Decimal("20.00"),
            credit=Decimal("0"),
            entry_type=EntryType.DEBIT,
        )
    )
    await db_session.commit()

    with pytest.raises(InsufficientCreditsError):
        await publish_invoice_to_ledger(db_session, inv)
