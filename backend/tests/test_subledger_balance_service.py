"""Subledger balance reporting tests (Phase 2)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.customer import CustomerRegistry
from app.models.invoice import Invoice, InvoiceStatus
from app.models.journal import EntryType, JournalEntry, JournalEntryKind
from app.models.vendor import VendorRegistry
from app.services.invoice.invoice_evaluation_service import ROUTE_PURCHASE, ROUTE_SALES
from app.services.reports.subledger_balance_service import fetch_ap_balances, fetch_ar_balances
from app.tenant_ids import TESTING_TENANT_UUID


@pytest.mark.asyncio
async def test_ap_balance_nets_accrual_and_payment_settlement(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.schemas.rule_book_config import ChartOfAccountEntry, PostingDefaults, RuleBookConfigPayload

    config = RuleBookConfigPayload(
        posting_defaults=PostingDefaults(
            payable_account="Accounts Payable",
            bank_account="Bank Account",
        ),
        chart_of_accounts=[
            ChartOfAccountEntry(code="1000", name="Bank Account", type="Asset"),
            ChartOfAccountEntry(code="2000", name="Accounts Payable", type="Liability"),
        ],
    )

    async def _load_config(_session, _tenant_id):
        return config

    monkeypatch.setattr(
        "app.services.reports.subledger_balance_service.load_config_for_tenant",
        _load_config,
    )

    vendor = VendorRegistry(
        tenant_id=TESTING_TENANT_UUID,
        vendor_name="Acme",
        vendor_slug="acme-bal",
        sender_pattern="acme@example.com",
    )
    db_session.add(vendor)
    await db_session.flush()

    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Acme",
        route_target=ROUTE_PURCHASE,
        invoice_date=date(2026, 3, 1),
        total=Decimal("100"),
        status=InvoiceStatus.PROCESSED,
        currency="AUD",
        file_hash="ap-bal",
    )
    db_session.add(inv)
    await db_session.flush()

    db_session.add_all(
        [
            JournalEntry(
                tenant_id=inv.tenant_id,
                invoice_id=inv.id,
                date=date(2026, 3, 1),
                account_code="2000",
                account_name="Accounts Payable",
                debit=Decimal("0"),
                credit=Decimal("100"),
                entry_type=EntryType.CREDIT,
                vendor_registry_id=vendor.id,
                entry_kind=JournalEntryKind.INVOICE_ACCRUAL,
            ),
            JournalEntry(
                tenant_id=inv.tenant_id,
                invoice_id=inv.id,
                date=date(2026, 3, 10),
                account_code="2000",
                account_name="Accounts Payable",
                debit=Decimal("100"),
                credit=Decimal("0"),
                entry_type=EntryType.DEBIT,
                vendor_registry_id=vendor.id,
                entry_kind=JournalEntryKind.PAYMENT_SETTLEMENT,
                payment_id=99,
            ),
        ]
    )
    await db_session.flush()

    result = await fetch_ap_balances(db_session, TESTING_TENANT_UUID, as_of=date(2026, 3, 31))
    assert len(result.rows) == 0
    assert result.totals.balance == Decimal("0")


@pytest.mark.asyncio
async def test_ap_balance_shows_open_amount_before_payment(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.schemas.rule_book_config import ChartOfAccountEntry, PostingDefaults, RuleBookConfigPayload

    config = RuleBookConfigPayload(
        posting_defaults=PostingDefaults(payable_account="Accounts Payable"),
        chart_of_accounts=[
            ChartOfAccountEntry(code="2000", name="Accounts Payable", type="Liability"),
        ],
    )

    async def _load_config(_session, _tenant_id):
        return config

    monkeypatch.setattr(
        "app.services.reports.subledger_balance_service.load_config_for_tenant",
        _load_config,
    )

    vendor = VendorRegistry(
        tenant_id=TESTING_TENANT_UUID,
        vendor_name="Beta Co",
        vendor_slug="beta-bal",
        sender_pattern="beta@example.com",
    )
    db_session.add(vendor)
    await db_session.flush()

    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Beta Co",
        route_target=ROUTE_PURCHASE,
        invoice_date=date(2026, 3, 1),
        total=Decimal("250"),
        status=InvoiceStatus.PROCESSED,
        currency="AUD",
        file_hash="ap-open",
    )
    db_session.add(inv)
    await db_session.flush()

    db_session.add(
        JournalEntry(
            tenant_id=inv.tenant_id,
            invoice_id=inv.id,
            date=date(2026, 3, 1),
            account_code="2000",
            account_name="Accounts Payable",
            debit=Decimal("0"),
            credit=Decimal("250"),
            entry_type=EntryType.CREDIT,
            vendor_registry_id=vendor.id,
            entry_kind=JournalEntryKind.INVOICE_ACCRUAL,
        )
    )
    await db_session.flush()

    result = await fetch_ap_balances(db_session, TESTING_TENANT_UUID, as_of=date(2026, 3, 31))
    assert len(result.rows) == 1
    assert result.rows[0].registry_id == vendor.id
    assert result.rows[0].balance == Decimal("250")


@pytest.mark.asyncio
async def test_ap_unregistered_bucket(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.schemas.rule_book_config import ChartOfAccountEntry, PostingDefaults, RuleBookConfigPayload

    config = RuleBookConfigPayload(
        posting_defaults=PostingDefaults(payable_account="Accounts Payable"),
        chart_of_accounts=[
            ChartOfAccountEntry(code="2000", name="Accounts Payable", type="Liability"),
        ],
    )

    async def _load_config(_session, _tenant_id):
        return config

    monkeypatch.setattr(
        "app.services.reports.subledger_balance_service.load_config_for_tenant",
        _load_config,
    )

    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Unknown Vendor",
        route_target=ROUTE_PURCHASE,
        invoice_date=date(2026, 3, 1),
        total=Decimal("80"),
        status=InvoiceStatus.PROCESSED,
        currency="AUD",
        file_hash="ap-unreg",
    )
    db_session.add(inv)
    await db_session.flush()

    db_session.add(
        JournalEntry(
            tenant_id=inv.tenant_id,
            invoice_id=inv.id,
            date=date(2026, 3, 1),
            account_code="2000",
            account_name="Accounts Payable",
            debit=Decimal("0"),
            credit=Decimal("80"),
            entry_type=EntryType.CREDIT,
            entry_kind=JournalEntryKind.INVOICE_ACCRUAL,
        )
    )
    await db_session.flush()

    result = await fetch_ap_balances(db_session, TESTING_TENANT_UUID, as_of=date(2026, 3, 31))
    assert result.unregistered.balance == Decimal("80")
    assert result.unregistered.document_count == 1


@pytest.mark.asyncio
async def test_ar_balance_nets_accrual_and_collection_settlement(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.schemas.rule_book_config import ChartOfAccountEntry, PostingDefaults, RuleBookConfigPayload

    config = RuleBookConfigPayload(
        posting_defaults=PostingDefaults(),
        chart_of_accounts=[
            ChartOfAccountEntry(code="1200", name="Accounts Receivable", type="Asset"),
            ChartOfAccountEntry(code="1000", name="Bank Account", type="Asset"),
        ],
    )

    async def _load_config(_session, _tenant_id):
        return config

    monkeypatch.setattr(
        "app.services.reports.subledger_balance_service.load_config_for_tenant",
        _load_config,
    )

    customer = CustomerRegistry(
        tenant_id=TESTING_TENANT_UUID,
        customer_name="Hotel",
        customer_slug="hotel-bal",
        sender_pattern="hotel@example.com",
    )
    db_session.add(customer)
    await db_session.flush()

    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Hotel",
        route_target=ROUTE_SALES,
        invoice_date=date(2026, 3, 1),
        total=Decimal("300"),
        status=InvoiceStatus.PROCESSED,
        currency="AUD",
        file_hash="ar-bal",
    )
    db_session.add(inv)
    await db_session.flush()

    db_session.add_all(
        [
            JournalEntry(
                tenant_id=inv.tenant_id,
                invoice_id=inv.id,
                date=date(2026, 3, 1),
                account_code="1200",
                account_name="Accounts Receivable",
                debit=Decimal("300"),
                credit=Decimal("0"),
                entry_type=EntryType.DEBIT,
                customer_registry_id=customer.id,
                entry_kind=JournalEntryKind.INVOICE_ACCRUAL,
            ),
            JournalEntry(
                tenant_id=inv.tenant_id,
                invoice_id=inv.id,
                date=date(2026, 3, 12),
                account_code="1200",
                account_name="Accounts Receivable",
                debit=Decimal("0"),
                credit=Decimal("300"),
                entry_type=EntryType.CREDIT,
                customer_registry_id=customer.id,
                entry_kind=JournalEntryKind.COLLECTION_SETTLEMENT,
                collection_id=55,
            ),
        ]
    )
    await db_session.flush()

    result = await fetch_ar_balances(db_session, TESTING_TENANT_UUID, as_of=date(2026, 3, 31))
    assert len(result.rows) == 0
    assert result.totals.balance == Decimal("0")


@pytest.mark.asyncio
async def test_subledger_ap_balances_api(client) -> None:
    response = await client.get("/api/reports/subledger/ap-balances")
    assert response.status_code == 200
    body = response.json()
    assert "data" in body
    assert "rows" in body["data"]
    assert "totals" in body["data"]
