"""Journal entry counterparty registry identity (Phase 1 subledger foundation)."""

from __future__ import annotations

import importlib.util
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import inspect
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.customer import CustomerRegistry
from app.models.invoice import Invoice, InvoiceStatus
from app.models.journal import EntryType, JournalEntry
from app.models.vendor import VendorRegistry
from app.schemas.rule_book_config import ChartOfAccountEntry, PostingDefaults, RuleBookConfigPayload
from app.services.invoice.remap_service import remap_invoices_for_tenant
from app.services.master_data.journal_counterparty_resolver import (
    resolve_counterparty_registry_ids_for_journal,
)
from app.services.payments.journal_generator import generate_entries
from app.services.payments.payment_service import ensure_payment_for_invoice
from app.services.rule_book.account_mapper import AccountMapping
from app.services.rule_book.rule_book_mapper import ROUTE_PURCHASE, ROUTE_SALES
from app.tenant_child_tables import journal_entries_for_invoice
from app.tenant_ids import TESTING_TENANT_UUID


def _purchase_config() -> RuleBookConfigPayload:
    return RuleBookConfigPayload(
        posting_defaults=PostingDefaults(
            tax_account="GST Paid",
            payable_account="Accounts Payable",
        ),
        chart_of_accounts=[
            ChartOfAccountEntry(code="6100", name="Software", type="Expense"),
            ChartOfAccountEntry(code="1400", name="GST Paid", type="Asset"),
            ChartOfAccountEntry(code="2000", name="Accounts Payable", type="Liability"),
        ],
    )


def _sales_config() -> RuleBookConfigPayload:
    return RuleBookConfigPayload(
        posting_defaults=PostingDefaults(),
        chart_of_accounts=[
            ChartOfAccountEntry(code="1200", name="Accounts Receivable", type="Asset"),
            ChartOfAccountEntry(code="4100", name="Sales Revenue", type="Revenue"),
            ChartOfAccountEntry(code="2300", name="GST Collected", type="Liability"),
        ],
    )


def _load_migration_063():
    path = (
        Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "063_journal_entry_counterparty_registry.py"
    )
    spec = importlib.util.spec_from_file_location("migration_063", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_migration_063_revision_chain() -> None:
    migration_063 = _load_migration_063()
    assert migration_063.revision == "063"
    assert migration_063.down_revision == "062"


def test_journal_entry_counterparty_columns_are_nullable_with_fk_targets() -> None:
    mapper = inspect(JournalEntry)
    vendor_col = mapper.columns["vendor_registry_id"]
    customer_col = mapper.columns["customer_registry_id"]

    assert vendor_col.nullable is True
    assert customer_col.nullable is True
    assert vendor_col.foreign_keys
    assert customer_col.foreign_keys
    assert {fk.target_fullname for fk in vendor_col.foreign_keys} == {"vendor_registry.id"}
    assert {fk.target_fullname for fk in customer_col.foreign_keys} == {"customer_registry.id"}


def test_purchase_ap_line_carries_vendor_registry_id_only() -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        invoice_date=date(2026, 3, 1),
        subtotal=Decimal("100"),
        gst=Decimal("10"),
        total=Decimal("110"),
        status=InvoiceStatus.JOURNALING,
        currency="AUD",
    )
    lines = generate_entries(
        inv,
        AccountMapping("6100", "Software"),
        config=_purchase_config(),
        vendor_registry_id=42,
    )
    ap_lines = [ln for ln in lines if ln.credit > 0]
    expense_lines = [ln for ln in lines if ln.debit > 0 and ln.account_code == "6100"]
    tax_lines = [ln for ln in lines if ln.account_code == "1400"]

    assert len(ap_lines) == 1
    assert ap_lines[0].vendor_registry_id == 42
    assert ap_lines[0].customer_registry_id is None
    assert expense_lines[0].vendor_registry_id is None
    assert expense_lines[0].customer_registry_id is None
    assert tax_lines[0].vendor_registry_id is None
    assert tax_lines[0].customer_registry_id is None


def test_purchase_ap_line_null_when_vendor_unresolvable() -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        invoice_date=date(2026, 3, 1),
        subtotal=Decimal("100"),
        gst=Decimal("10"),
        total=Decimal("110"),
        status=InvoiceStatus.JOURNALING,
        currency="AUD",
    )
    lines = generate_entries(
        inv,
        AccountMapping("6100", "Software"),
        config=_purchase_config(),
        vendor_registry_id=None,
    )
    ap_line = [ln for ln in lines if ln.credit > 0][0]
    assert ap_line.vendor_registry_id is None


def test_sales_ar_line_carries_customer_registry_id_only() -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        invoice_date=date(2026, 3, 1),
        subtotal=Decimal("200"),
        gst=Decimal("20"),
        total=Decimal("220"),
        status=InvoiceStatus.JOURNALING,
        currency="AUD",
        route_target=ROUTE_SALES,
    )
    lines = generate_entries(
        inv,
        AccountMapping("4100", "Sales Revenue"),
        config=_sales_config(),
        customer_registry_id=99,
    )
    ar_lines = [ln for ln in lines if ln.debit > 0]
    revenue_lines = [ln for ln in lines if ln.credit > 0 and ln.account_code == "4100"]
    tax_lines = [ln for ln in lines if ln.credit > 0 and ln.account_code != "4100"]

    assert len(ar_lines) == 1
    assert ar_lines[0].customer_registry_id == 99
    assert ar_lines[0].vendor_registry_id is None
    assert revenue_lines[0].customer_registry_id is None
    assert revenue_lines[0].vendor_registry_id is None
    assert len(tax_lines) == 1
    assert tax_lines[0].customer_registry_id is None
    assert tax_lines[0].vendor_registry_id is None


def test_sales_ar_line_null_when_customer_unresolvable() -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        invoice_date=date(2026, 3, 1),
        subtotal=Decimal("200"),
        gst=Decimal("20"),
        total=Decimal("220"),
        status=InvoiceStatus.JOURNALING,
        currency="AUD",
        route_target=ROUTE_SALES,
    )
    lines = generate_entries(
        inv,
        AccountMapping("4100", "Sales Revenue"),
        config=_sales_config(),
        customer_registry_id=None,
    )
    ar_line = [ln for ln in lines if ln.debit > 0][0]
    assert ar_line.customer_registry_id is None


@pytest.mark.asyncio
async def test_resolver_finds_vendor_registry_for_purchase_invoice(
    db_session: AsyncSession,
) -> None:
    vendor = VendorRegistry(
        tenant_id=TESTING_TENANT_UUID,
        vendor_name="Acme Supplies",
        vendor_slug="acme-supplies",
        sender_pattern="acme@example.com",
    )
    db_session.add(vendor)
    await db_session.flush()

    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Acme Supplies",
        storage_vendor_slug="acme-supplies",
        invoice_date=date(2026, 3, 1),
        subtotal=Decimal("100"),
        gst=Decimal("10"),
        total=Decimal("110"),
        status=InvoiceStatus.JOURNALING,
        currency="AUD",
        file_hash="resolver-vendor",
    )
    vendor_id, customer_id = await resolve_counterparty_registry_ids_for_journal(
        db_session, inv
    )
    assert vendor_id == vendor.id
    assert customer_id is None


@pytest.mark.asyncio
async def test_resolver_returns_null_vendor_when_unmatched(
    db_session: AsyncSession,
) -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Unknown Vendor Pty Ltd",
        storage_vendor_slug="unknown",
        invoice_date=date(2026, 3, 1),
        subtotal=Decimal("100"),
        gst=Decimal("10"),
        total=Decimal("110"),
        status=InvoiceStatus.JOURNALING,
        currency="AUD",
        file_hash="resolver-vendor-miss",
    )
    vendor_id, customer_id = await resolve_counterparty_registry_ids_for_journal(
        db_session, inv
    )
    assert vendor_id is None
    assert customer_id is None


@pytest.mark.asyncio
async def test_resolver_finds_customer_registry_for_sales_invoice(
    db_session: AsyncSession,
) -> None:
    customer = CustomerRegistry(
        tenant_id=TESTING_TENANT_UUID,
        customer_name="Harbour View Hotel",
        customer_slug="harbour-view",
        sender_pattern="harbour@example.com",
    )
    db_session.add(customer)
    await db_session.flush()

    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Harbour View Hotel",
        storage_vendor_slug="harbour-view",
        invoice_date=date(2026, 3, 1),
        subtotal=Decimal("200"),
        gst=Decimal("20"),
        total=Decimal("220"),
        status=InvoiceStatus.JOURNALING,
        currency="AUD",
        route_target=ROUTE_SALES,
        file_hash="resolver-customer",
    )
    vendor_id, customer_id = await resolve_counterparty_registry_ids_for_journal(
        db_session, inv
    )
    assert vendor_id is None
    assert customer_id == customer.id


@pytest.mark.asyncio
async def test_payment_and_journal_ap_line_share_vendor_registry_id(
    db_session: AsyncSession,
) -> None:
    vendor = VendorRegistry(
        tenant_id=TESTING_TENANT_UUID,
        vendor_name="Acme Supplies",
        vendor_slug="acme-pay-match",
        sender_pattern="acme@example.com",
    )
    db_session.add(vendor)
    await db_session.flush()

    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Acme Supplies",
        storage_vendor_slug="acme-pay-match",
        route_target=ROUTE_PURCHASE,
        invoice_date=date(2026, 3, 1),
        due_date=date(2026, 4, 1),
        subtotal=Decimal("100"),
        gst=Decimal("10"),
        total=Decimal("110"),
        status=InvoiceStatus.PROCESSED,
        currency="AUD",
        purchase_document_type="invoice",
        file_hash="payment-journal-match",
    )
    db_session.add(inv)
    await db_session.flush()

    vendor_reg_id, customer_reg_id = await resolve_counterparty_registry_ids_for_journal(
        db_session, inv
    )
    lines = generate_entries(
        inv,
        AccountMapping("6100", "Software"),
        config=_purchase_config(),
        vendor_registry_id=vendor_reg_id,
        customer_registry_id=customer_reg_id,
    )
    ap_line = [ln for ln in lines if ln.credit > 0][0]
    db_session.add(
        JournalEntry(
            tenant_id=inv.tenant_id,
            invoice_id=inv.id,
            date=ap_line.date,
            account_code=ap_line.account_code,
            account_name=ap_line.account_name,
            debit=ap_line.debit,
            credit=ap_line.credit,
            entry_type=ap_line.entry_type,
            vendor_registry_id=ap_line.vendor_registry_id,
            customer_registry_id=ap_line.customer_registry_id,
        )
    )
    await db_session.flush()

    payment = await ensure_payment_for_invoice(db_session, inv)
    assert payment is not None
    assert payment.vendor_registry_id == vendor.id
    assert ap_line.vendor_registry_id == vendor.id
    assert payment.vendor_registry_id == ap_line.vendor_registry_id


@pytest.mark.asyncio
async def test_remap_regenerates_journal_with_vendor_registry_id(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _purchase_config()
    config = config.model_copy(
        update={
            "chart_of_accounts": [
                *config.chart_of_accounts,
                ChartOfAccountEntry(code="6200", name="Supplies", type="Expense"),
            ]
        }
    )

    vendor = VendorRegistry(
        tenant_id=TESTING_TENANT_UUID,
        vendor_name="Acme",
        vendor_slug="acme-remap",
        sender_pattern="acme@example.com",
    )
    db_session.add(vendor)
    await db_session.flush()

    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Acme",
        storage_vendor_slug="acme-remap",
        invoice_no="REM-CP-1",
        invoice_date=date(2026, 3, 1),
        subtotal=Decimal("100"),
        gst=Decimal("10"),
        total=Decimal("110"),
        status=InvoiceStatus.PROCESSED,
        currency="AUD",
        file_hash="remap-counterparty",
        account_code="6100",
        account_name="Software",
    )
    db_session.add(inv)
    await db_session.flush()
    for code, name, dr, cr, et in [
        ("6100", "Software", Decimal("100"), Decimal("0"), EntryType.DEBIT),
        ("1400", "GST Paid", Decimal("10"), Decimal("0"), EntryType.DEBIT),
        ("2000", "Accounts Payable", Decimal("0"), Decimal("110"), EntryType.CREDIT),
    ]:
        db_session.add(
            JournalEntry(
                tenant_id=inv.tenant_id,
                invoice_id=inv.id,
                date=inv.invoice_date,
                account_code=code,
                account_name=name,
                debit=dr,
                credit=cr,
                entry_type=et,
            )
        )
    await db_session.flush()

    async def _load_config(_session, _tenant_id):
        return config

    def _map_invoice(_invoice, *, config=None):
        return AccountMapping("6200", "Supplies")

    monkeypatch.setattr(
        "app.services.invoice.remap_service.load_config_for_tenant",
        _load_config,
    )
    monkeypatch.setattr(
        "app.services.invoice.remap_service.map_invoice_to_account",
        _map_invoice,
    )
    async def _no_reclassify(*_args, **_kwargs):
        return False

    async def _no_eval(*_args, **_kwargs):
        return None

    monkeypatch.setattr(
        "app.services.invoice.remap_service.reclassify_invoice_document_type",
        _no_reclassify,
    )
    monkeypatch.setattr(
        "app.services.invoice.remap_service.apply_invoice_evaluation",
        _no_eval,
    )
    monkeypatch.setattr(
        "app.services.invoice.remap_service.sync_invoice_blob_path",
        lambda *_args, **_kwargs: None,
    )

    result = await remap_invoices_for_tenant(db_session, tenant_id=TESTING_TENANT_UUID)
    assert result.journals_regenerated == 1

    entries = (
        await db_session.execute(
            select(JournalEntry).where(
                *journal_entries_for_invoice(inv.tenant_id, inv.id),
            )
        )
    ).scalars().all()
    ap_lines = [entry for entry in entries if entry.credit > 0]
    assert len(ap_lines) == 1
    assert ap_lines[0].vendor_registry_id == vendor.id
    assert ap_lines[0].customer_registry_id is None

    non_ap = [entry for entry in entries if entry.credit == 0]
    assert all(entry.vendor_registry_id is None for entry in non_ap)
    assert all(entry.customer_registry_id is None for entry in non_ap)
