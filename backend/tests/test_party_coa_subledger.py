"""Party COA sub-ledger on register + AP/AR control posting."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import Invoice, InvoiceStatus
from app.models.journal import EntryType, JournalEntry, JournalEntryKind
from app.models.journal_batch import JournalBatch, JournalBatchStatus
from app.models.vendor import VendorRegistry
from tests.journal_test_helpers import seed_journal_batch
from app.schemas.rule_book_config import (
    ChartOfAccountEntry,
    PostingDefaults,
    RuleBookConfigPayload,
    SubLedgerEntry,
    validate_rule_book_config_payload,
)
from app.schemas.vendor import VendorCreate
from app.services.invoice.remap_service import _regenerate_journal_entries
from app.services.master_data.party_coa_subledger_service import (
    control_account_codes_for_parent,
    ensure_vendor_party_coa_sub_ledger,
    party_sub_ledger_code,
    resolve_party_child_mapping,
    _upsert_sub_ledger_on_parent,
)
from app.services.master_data.vendor_registry_service import create_vendor_registry
from app.services.payments.journal_generator import generate_entries
from app.services.reports.subledger_balance_service import fetch_ap_balances
from app.services.rule_book.account_mapper import AccountMapping
from app.services.rule_book.rule_book_config_io import load_rule_book_config_dict, save_rule_book_config
from app.services.rule_book.rule_book_mapper import (
    get_payable_account_mapping,
    get_receivable_account_mapping,
    resolve_sales_post_accounts,
)
from app.tenant_ids import TESTING_TENANT_UUID


def _config_with_ap_ar(
    *,
    ap_subs: list[SubLedgerEntry] | None = None,
) -> RuleBookConfigPayload:
    return RuleBookConfigPayload(
        posting_defaults=PostingDefaults(
            tax_account="GST Paid",
            payable_account="Accounts Payable",
            receivable_account="Accounts Receivable",
            bank_account="Bank Account",
        ),
        chart_of_accounts=[
            ChartOfAccountEntry(code="1000", name="Bank Account", type="Asset"),
            ChartOfAccountEntry(code="1200", name="Accounts Receivable", type="Asset"),
            ChartOfAccountEntry(code="1400", name="GST Paid", type="Asset"),
            ChartOfAccountEntry(
                code="2000",
                name="Accounts Payable",
                type="Liability",
                sub_ledgers=list(ap_subs or []),
            ),
            ChartOfAccountEntry(code="6100", name="Software", type="Expense"),
            ChartOfAccountEntry(code="4100", name="Sales Revenue", type="Revenue"),
            ChartOfAccountEntry(code="2300", name="GST Collected", type="Liability"),
        ],
    )


@pytest.mark.asyncio
async def test_create_vendor_registry_upserts_party_coa_child(
    db_session: AsyncSession,
) -> None:
    config = _config_with_ap_ar()
    await save_rule_book_config(db_session, config, TESTING_TENANT_UUID)

    created = await create_vendor_registry(
        db_session,
        tenant_id=TESTING_TENANT_UUID,
        body=VendorCreate(
            vendor_slug="acme-party",
            vendor_name="Acme Party Co",
            sender_pattern="acme-party@example.com",
        ),
    )
    assert created.vendor_slug == "acme-party"

    raw = await load_rule_book_config_dict(db_session, TESTING_TENANT_UUID)
    payload = validate_rule_book_config_payload(raw)
    child = resolve_party_child_mapping(
        payload,
        parent_ledger_name="Accounts Payable",
        slug="acme-party",
    )
    assert child is not None
    assert child.account_code == party_sub_ledger_code("acme-party")
    assert child.account_name == "Acme Party Co"
    ap = next(a for a in payload.chart_of_accounts if a.name == "Accounts Payable")
    party_rows = [s for s in ap.sub_ledgers if s.origin == "party"]
    assert any(s.code == child.account_code for s in party_rows)


def test_upsert_renames_with_suffix_when_name_already_used() -> None:
    """Renaming an employee to an existing party name must not 500 on unique names."""
    parent = ChartOfAccountEntry(
        code="1003",
        name="Staff Advance.",
        type="Asset",
        sub_ledgers=[
            SubLedgerEntry(code="EM-NEW-EMPLOYEE-FAD7", name="vishnu", origin="party"),
            SubLedgerEntry(
                code="EM-NEW-EMPLOYEE-94C3",
                name="New employee (EM-NEW-EMPLOYEE-94C3)",
                origin="party",
            ),
        ],
    )
    child = _upsert_sub_ledger_on_parent(
        parent,
        slug="em-new-employee-94c3a3",
        party_name="vishnu",
    )
    assert child.code == "EM-NEW-EMPLOYEE-94C3"
    assert child.name == "vishnu (EM-NEW-EMPLOYEE-94C3)"
    ChartOfAccountEntry.model_validate(parent.model_dump())


def test_generate_entries_posts_to_party_coa_child() -> None:
    config = _config_with_ap_ar(
        ap_subs=[SubLedgerEntry(code="ACME-PARTY", name="Acme Party Co", origin="party")]
    )
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Acme Party Co",
        route_target="Purchase Management",
        invoice_date=date(2026, 4, 1),
        subtotal=Decimal("100"),
        gst=Decimal("10"),
        total=Decimal("110"),
        status=InvoiceStatus.PROCESSED,
        currency="AUD",
        file_hash="party-je",
    )
    lines = generate_entries(
        inv,
        AccountMapping("6100", "Software"),
        config=config,
        vendor_registry_id=7,
        control_mapping=AccountMapping("ACME-PARTY", "Acme Party Co"),
    )
    ap_line = next(ln for ln in lines if ln.credit > 0)
    assert ap_line.account_code == "ACME-PARTY"
    assert ap_line.account_name == "Acme Party Co"
    assert ap_line.vendor_registry_id == 7


def test_receivable_mapping_uses_posting_defaults() -> None:
    config = RuleBookConfigPayload(
        posting_defaults=PostingDefaults(receivable_account="Trade Debtors"),
        chart_of_accounts=[
            ChartOfAccountEntry(code="1210", name="Trade Debtors", type="Asset"),
            ChartOfAccountEntry(code="4100", name="Sales Revenue", type="Revenue"),
            ChartOfAccountEntry(code="2300", name="GST Collected", type="Liability"),
        ],
    )
    mapping = get_receivable_account_mapping(config)
    assert mapping.account_name == "Trade Debtors"
    assert mapping.account_code == "1210"

    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Buyer",
        route_target="Sales Management",
        document_type_code="TAX_INVOICE",
        invoice_date=date(2026, 4, 1),
        total=Decimal("50"),
        status=InvoiceStatus.PROCESSED,
        currency="AUD",
        file_hash="recv-default",
    )
    recv, _tax = resolve_sales_post_accounts(inv, config)
    assert recv == "Trade Debtors"


@pytest.mark.asyncio
async def test_remap_preserves_settlement_journals(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _config_with_ap_ar()
    await save_rule_book_config(db_session, config, TESTING_TENANT_UUID)

    vendor = VendorRegistry(
        tenant_id=TESTING_TENANT_UUID,
        vendor_slug="remap-v",
        vendor_name="Remap Vendor",
        sender_pattern="remap@example.com",
    )
    db_session.add(vendor)
    await db_session.flush()
    await ensure_vendor_party_coa_sub_ledger(
        db_session,
        TESTING_TENANT_UUID,
        slug=vendor.vendor_slug,
        vendor_name=vendor.vendor_name,
    )

    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Remap Vendor",
        storage_vendor_slug="remap-v",
        route_target="Purchase Management",
        invoice_date=date(2026, 4, 1),
        subtotal=Decimal("100"),
        gst=Decimal("0"),
        total=Decimal("100"),
        status=InvoiceStatus.PROCESSED,
        currency="AUD",
        file_hash="remap-settle",
        account_code="6100",
        account_name="Software",
    )
    db_session.add(inv)
    await db_session.flush()

    child_code = party_sub_ledger_code(vendor.vendor_slug)
    await seed_journal_batch(
        db_session,
        inv,
        [
            ("6100", "Software", Decimal("100"), Decimal("0"), EntryType.DEBIT),
            (child_code, "Remap Vendor", Decimal("0"), Decimal("100"), EntryType.CREDIT),
        ],
        entry_date=date(2026, 4, 1),
        entry_kind=JournalEntryKind.INVOICE_ACCRUAL,
        vendor_registry_id=vendor.id,
    )
    await seed_journal_batch(
        db_session,
        inv,
        [
            (child_code, "Remap Vendor", Decimal("100"), Decimal("0"), EntryType.DEBIT),
            ("1000", "Bank Account", Decimal("0"), Decimal("100"), EntryType.CREDIT),
        ],
        entry_date=date(2026, 4, 5),
        entry_kind=JournalEntryKind.PAYMENT_SETTLEMENT,
        payment_id=42,
        vendor_registry_id=vendor.id,
    )

    monkeypatch.setattr(
        "app.services.invoice.remap_service.map_invoice_to_account",
        lambda invoice, config: AccountMapping("6100", "Software"),
    )

    raw = await load_rule_book_config_dict(db_session, TESTING_TENANT_UUID)
    payload = validate_rule_book_config_payload(raw)
    regenerated = await _regenerate_journal_entries(db_session, inv, config=payload)
    assert regenerated is True

    live_kinds = (
        await db_session.execute(
            select(JournalEntry.entry_kind)
            .join(JournalBatch, JournalBatch.id == JournalEntry.batch_id)
            .where(
                JournalEntry.invoice_id == inv.id,
                JournalBatch.status == JournalBatchStatus.POSTED.value,
                JournalBatch.reversal_reason.is_(None),
            )
        )
    ).scalars().all()
    assert live_kinds.count(JournalEntryKind.PAYMENT_SETTLEMENT) == 2  # Dr AP + Cr Bank
    assert JournalEntryKind.INVOICE_ACCRUAL in live_kinds
    assert JournalEntryKind.PAYMENT_SETTLEMENT in live_kinds


@pytest.mark.asyncio
async def test_ap_balance_totals_ignore_pagination(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ap_subs = [
        SubLedgerEntry(
            code=party_sub_ledger_code(f"vend-{i}"),
            name=f"Vendor {i}",
            origin="party",
        )
        for i in range(3)
    ]
    config = _config_with_ap_ar(ap_subs=ap_subs)

    async def _load_config(_session, _tenant_id):
        return config

    monkeypatch.setattr(
        "app.services.reports.subledger_balance_service.load_posting_config_for_tenant",
        _load_config,
    )

    vendors = []
    for i in range(3):
        v = VendorRegistry(
            tenant_id=TESTING_TENANT_UUID,
            vendor_slug=f"vend-{i}",
            vendor_name=f"Vendor {i}",
            sender_pattern=f"v{i}@example.com",
        )
        db_session.add(v)
        vendors.append(v)
    await db_session.flush()

    for i, vendor in enumerate(vendors):
        inv = Invoice(
            tenant_id=TESTING_TENANT_UUID,
            vendor=vendor.vendor_name,
            route_target="Purchase Management",
            invoice_date=date(2026, 5, 1),
            total=Decimal("100"),
            status=InvoiceStatus.PROCESSED,
            currency="AUD",
            file_hash=f"page-{i}",
        )
        db_session.add(inv)
        await db_session.flush()
        code = party_sub_ledger_code(vendor.vendor_slug)
        await seed_journal_batch(
            db_session,
            inv,
            [
                ("6100", "Software", Decimal("100"), Decimal("0"), EntryType.DEBIT),
                (code, vendor.vendor_name, Decimal("0"), Decimal("100"), EntryType.CREDIT),
            ],
            entry_date=date(2026, 5, 1),
            vendor_registry_id=vendor.id,
        )

    page = await fetch_ap_balances(
        db_session,
        TESTING_TENANT_UUID,
        as_of=date(2026, 5, 31),
        limit=1,
        offset=0,
    )
    assert len(page.rows) == 1
    assert page.totals.counterparty_count == 3
    assert page.totals.balance == Decimal("300")

    payable = get_payable_account_mapping(config)
    codes = control_account_codes_for_parent(config, payable)
    assert payable.account_code in codes
    assert party_sub_ledger_code("vend-0") in codes
