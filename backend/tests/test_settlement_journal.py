"""Settlement journal posting tests (Phase 3)."""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.collection import Collection, CollectionStatus
from app.models.invoice import Invoice, InvoiceStatus
from app.models.journal import EntryType, JournalEntry, JournalEntryKind
from app.models.payment import Payment, PaymentStatus
from app.models.vendor import VendorRegistry
from app.schemas.rule_book_config import ChartOfAccountEntry, PostingDefaults, RuleBookConfigPayload
from app.services.integration.collection_service import mark_collection_received
from app.services.invoice.invoice_evaluation_service import ROUTE_PURCHASE, ROUTE_SALES
from app.services.payments.journal_generator import is_balanced
from app.services.payments.settlement_journal_service import (
    generate_collection_settlement_entries,
    generate_payment_settlement_entries,
)
from app.services.payments.settlement_service import (
    post_collection_settlement_journal,
    post_payment_settlement_journal,
)
from app.tenant_ids import TESTING_TENANT_UUID


def _config() -> RuleBookConfigPayload:
    return RuleBookConfigPayload(
        posting_defaults=PostingDefaults(
            tax_account="GST Paid",
            payable_account="Accounts Payable",
            bank_account="Bank Account",
        ),
        chart_of_accounts=[
            ChartOfAccountEntry(code="1000", name="Bank Account", type="Asset"),
            ChartOfAccountEntry(code="1200", name="Accounts Receivable", type="Asset"),
            ChartOfAccountEntry(code="1400", name="GST Paid", type="Asset"),
            ChartOfAccountEntry(code="2000", name="Accounts Payable", type="Liability"),
        ],
    )


def test_payment_settlement_lines_balanced_with_vendor_on_ap_debit() -> None:
    payment = Payment(
        tenant_id=TESTING_TENANT_UUID,
        invoice_id=1,
        vendor_registry_id=7,
        amount=Decimal("110"),
        paid_date=datetime(2026, 3, 15, tzinfo=timezone.utc),
    )
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        invoice_date=date(2026, 3, 1),
        total=Decimal("110"),
        status=InvoiceStatus.PROCESSED,
        currency="AUD",
    )
    lines = generate_payment_settlement_entries(payment, inv, _config())
    assert is_balanced(lines)
    ap = [ln for ln in lines if ln.debit > 0][0]
    bank = [ln for ln in lines if ln.credit > 0][0]
    assert ap.account_code == "2000"
    assert ap.vendor_registry_id == 7
    assert bank.account_code == "1000"
    assert bank.vendor_registry_id is None


def test_collection_settlement_lines_balanced_with_customer_on_ar_credit() -> None:
    collection = Collection(
        tenant_id=TESTING_TENANT_UUID,
        invoice_id=1,
        customer_registry_id=9,
        amount=Decimal("220"),
        received_date=datetime(2026, 3, 20, tzinfo=timezone.utc),
    )
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        invoice_date=date(2026, 3, 1),
        total=Decimal("220"),
        status=InvoiceStatus.PROCESSED,
        currency="AUD",
        route_target=ROUTE_SALES,
    )
    lines = generate_collection_settlement_entries(collection, inv, _config())
    assert is_balanced(lines)
    bank = [ln for ln in lines if ln.debit > 0][0]
    ar = [ln for ln in lines if ln.credit > 0][0]
    assert bank.account_code == "1000"
    assert ar.account_code == "1200"
    assert ar.customer_registry_id == 9
    assert bank.customer_registry_id is None


@pytest.mark.asyncio
async def test_post_payment_settlement_journal_is_idempotent(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _load_config(_session, _tenant_id):
        return _config()

    monkeypatch.setattr(
        "app.services.payments.settlement_service.load_config_for_tenant",
        _load_config,
    )

    vendor = VendorRegistry(
        tenant_id=TESTING_TENANT_UUID,
        vendor_name="Acme",
        vendor_slug="acme-settle",
        sender_pattern="acme@example.com",
    )
    db_session.add(vendor)
    await db_session.flush()

    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Acme",
        route_target=ROUTE_PURCHASE,
        purchase_document_type="invoice",
        invoice_date=date(2026, 3, 1),
        due_date=date(2026, 4, 1),
        total=Decimal("110"),
        status=InvoiceStatus.PROCESSED,
        currency="AUD",
        file_hash="settle-pay",
    )
    db_session.add(inv)
    await db_session.flush()

    payment = Payment(
        tenant_id=TESTING_TENANT_UUID,
        invoice_id=inv.id,
        vendor_registry_id=vendor.id,
        vendor="Acme",
        amount=Decimal("110"),
        currency="AUD",
        status=PaymentStatus.PAID,
        paid_date=datetime(2026, 3, 15, tzinfo=timezone.utc),
    )
    db_session.add(payment)
    await db_session.flush()

    assert await post_payment_settlement_journal(db_session, payment) is True
    assert await post_payment_settlement_journal(db_session, payment) is False

    count = (
        await db_session.execute(
            select(func.count())
            .select_from(JournalEntry)
            .where(
                JournalEntry.payment_id == payment.id,
                JournalEntry.entry_kind == JournalEntryKind.PAYMENT_SETTLEMENT,
            )
        )
    ).scalar()
    assert count == 2


@pytest.mark.asyncio
async def test_mark_collection_received_posts_settlement_journal(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.models.customer import CustomerRegistry

    async def _load_config(_session, _tenant_id):
        return _config()

    monkeypatch.setattr(
        "app.services.payments.settlement_service.load_config_for_tenant",
        _load_config,
    )

    customer = CustomerRegistry(
        tenant_id=TESTING_TENANT_UUID,
        customer_name="Harbour Hotel",
        customer_slug="harbour-settle",
        sender_pattern="harbour@example.com",
    )
    db_session.add(customer)
    await db_session.flush()

    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Harbour Hotel",
        route_target=ROUTE_SALES,
        sales_document_type="invoice",
        invoice_date=date(2026, 3, 1),
        due_date=date(2026, 4, 1),
        total=Decimal("220"),
        status=InvoiceStatus.PROCESSED,
        currency="AUD",
        file_hash="settle-col",
    )
    db_session.add(inv)
    await db_session.flush()

    collection = Collection(
        tenant_id=TESTING_TENANT_UUID,
        invoice_id=inv.id,
        customer_registry_id=customer.id,
        customer="Harbour Hotel",
        amount=Decimal("220"),
        currency="AUD",
        status=CollectionStatus.QUEUE,
        due_date=date(2026, 4, 1),
    )
    db_session.add(collection)
    await db_session.flush()

    await mark_collection_received(db_session, TESTING_TENANT_UUID, collection.id)

    entries = (
        await db_session.execute(
            select(JournalEntry).where(
                JournalEntry.collection_id == collection.id,
                JournalEntry.entry_kind == JournalEntryKind.COLLECTION_SETTLEMENT,
            )
        )
    ).scalars().all()
    assert len(entries) == 2
    ar_line = [row for row in entries if row.credit > 0][0]
    # Control account may be the parent AR code or the party child Sub-GL.
    from app.services.master_data.party_coa_subledger_service import party_sub_ledger_code

    assert ar_line.account_code in {
        "1200",
        party_sub_ledger_code(customer.customer_slug),
    }
    assert ar_line.customer_registry_id == customer.id
    assert ar_line.entry_type == EntryType.CREDIT
