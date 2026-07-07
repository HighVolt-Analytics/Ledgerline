from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import Invoice, InvoiceStatus
from app.models.journal import EntryType, JournalEntry
from app.schemas.rule_book_config import ChartOfAccountEntry, PostingDefaults, RuleBookConfigPayload
from app.services.invoice.remap_service import remap_invoices_for_tenant
from app.services.rule_book.account_mapper import AccountMapping
from app.tenant_child_tables import journal_entries_for_invoice
from app.tenant_ids import TESTING_TENANT_UUID


@pytest.mark.asyncio
async def test_remap_regenerates_journal_entries(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = RuleBookConfigPayload(
        posting_defaults=PostingDefaults(),
        chart_of_accounts=[
            ChartOfAccountEntry(code="6100", name="Software", type="Expense"),
            ChartOfAccountEntry(code="6200", name="Supplies", type="Expense"),
            ChartOfAccountEntry(code="1400", name="GST Paid", type="Asset"),
            ChartOfAccountEntry(code="2000", name="Accounts Payable", type="Liability"),
        ],
    )
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Acme",
        invoice_no="REM-1",
        invoice_date=date(2026, 3, 1),
        subtotal=Decimal("100"),
        gst=Decimal("10"),
        total=Decimal("110"),
        status=InvoiceStatus.PROCESSED,
        currency="AUD",
        file_hash="remap-journal",
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

    monkeypatch.setattr(
        "app.services.invoice.remap_service.reclassify_invoice_document_type",
        _no_reclassify,
    )
    async def _no_eval(*_args, **_kwargs):
        return None

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
    assert inv.account_code == "6200"

    entries = (
        await db_session.execute(
            select(JournalEntry).where(
                *journal_entries_for_invoice(inv.tenant_id, inv.id),
            )
        )
    ).scalars().all()
    expense_lines = [entry for entry in entries if entry.debit > 0 and entry.account_code != "1400"]
    assert len(expense_lines) == 1
    assert expense_lines[0].account_code == "6200"
