"""Integration: accrual → remap (reverse+repost) → reject (reverse) preserves history."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import Invoice, InvoiceStatus
from app.models.journal import EntryType, JournalEntry, JournalEntryKind
from app.models.journal_batch import JournalBatch, JournalBatchStatus
from app.schemas.rule_book_config import ChartOfAccountEntry, PostingDefaults, RuleBookConfigPayload
from app.services.invoice.invoice_reset import clear_invoice_posting_artifacts
from app.services.invoice.remap_service import remap_invoices_for_tenant
from app.services.payments.journal_generator import generate_entries
from app.services.payments.journal_persist_service import persist_journal_lines
from app.services.rule_book.account_mapper import AccountMapping
from app.tenant_child_tables import journal_entries_for_invoice
from app.tenant_ids import TESTING_TENANT_UUID


def _config() -> RuleBookConfigPayload:
    return RuleBookConfigPayload(
        posting_defaults=PostingDefaults(
            tax_account="GST Paid",
            payable_account="Accounts Payable",
        ),
        chart_of_accounts=[
            ChartOfAccountEntry(code="6100", name="Software", type="Expense"),
            ChartOfAccountEntry(code="6200", name="Supplies", type="Expense"),
            ChartOfAccountEntry(code="1400", name="GST Paid", type="Asset"),
            ChartOfAccountEntry(code="2000", name="Accounts Payable", type="Liability"),
        ],
    )


def _net_by_account(entries: list[JournalEntry]) -> dict[str, Decimal]:
    """Txn-currency net (debit − credit) per account — mirrors delete/rewrite net."""
    nets: dict[str, Decimal] = {}
    for entry in entries:
        nets[entry.account_code] = nets.get(entry.account_code, Decimal("0")) + (
            Decimal(str(entry.debit or 0)) - Decimal(str(entry.credit or 0))
        )
    return {k: v for k, v in nets.items() if v != 0}


@pytest.mark.asyncio
async def test_accrual_remap_reject_reversal_chain(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _config()
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Acme",
        invoice_no="REV-CHAIN-1",
        invoice_date=date(2026, 6, 1),
        subtotal=Decimal("100"),
        gst=Decimal("10"),
        total=Decimal("110"),
        status=InvoiceStatus.PROCESSED,
        currency="AUD",
        file_hash="rev-chain",
        account_code="6100",
        account_name="Software",
    )
    db_session.add(inv)
    await db_session.flush()

    # --- 1. Post accrual ---
    lines = generate_entries(
        inv, AccountMapping("6100", "Software"), config=config
    )
    await persist_journal_lines(db_session, inv, lines)
    await db_session.flush()

    batches_after_post = (
        await db_session.execute(
            select(JournalBatch).where(JournalBatch.invoice_id == inv.id)
        )
    ).scalars().all()
    assert len(batches_after_post) == 1
    original_batch = batches_after_post[0]
    assert original_batch.status == JournalBatchStatus.POSTED.value
    assert original_batch.reversed_by_batch_id is None

    entries_after_post = (
        await db_session.execute(
            select(JournalEntry).where(*journal_entries_for_invoice(inv.tenant_id, inv.id))
        )
    ).scalars().all()
    assert len(entries_after_post) == 3
    expected_live_net = _net_by_account(entries_after_post)

    # --- 2. Remap → reverse original + post new accrual ---
    async def _load_config(_session, _tenant_id):
        return config

    monkeypatch.setattr(
        "app.services.invoice.remap_service.load_config_for_tenant",
        _load_config,
    )
    monkeypatch.setattr(
        "app.services.invoice.remap_service.map_invoice_to_account",
        lambda _invoice, *, config=None: AccountMapping("6200", "Supplies"),
    )

    async def _noop(*_a, **_k):
        return False if _a else None

    monkeypatch.setattr(
        "app.services.invoice.remap_service.reclassify_invoice_document_type",
        _noop,
    )
    monkeypatch.setattr(
        "app.services.invoice.remap_service.apply_invoice_evaluation",
        _noop,
    )
    monkeypatch.setattr(
        "app.services.invoice.remap_service.sync_invoice_blob_path",
        lambda *_a, **_k: None,
    )

    result = await remap_invoices_for_tenant(db_session, tenant_id=TESTING_TENANT_UUID)
    assert result.journals_regenerated == 1
    await db_session.refresh(original_batch)

    assert original_batch.status == JournalBatchStatus.REVERSED.value
    assert original_batch.reversed_by_batch_id is not None
    reversal_batch = await db_session.get(JournalBatch, original_batch.reversed_by_batch_id)
    assert reversal_batch is not None
    assert reversal_batch.reversal_reason == "remap_regenerate"
    assert reversal_batch.status == JournalBatchStatus.POSTED.value

    all_after_remap = (
        await db_session.execute(
            select(JournalEntry).where(*journal_entries_for_invoice(inv.tenant_id, inv.id))
        )
    ).scalars().all()
    # 3 original + 3 reverse + 3 new
    assert len(all_after_remap) == 9

    live_after_remap = (
        await db_session.execute(
            select(JournalEntry)
            .join(JournalBatch, JournalBatch.id == JournalEntry.batch_id)
            .where(
                *journal_entries_for_invoice(inv.tenant_id, inv.id),
                JournalBatch.status == JournalBatchStatus.POSTED.value,
                JournalBatch.reversal_reason.is_(None),
            )
        )
    ).scalars().all()
    live_net = _net_by_account(live_after_remap)
    # Same shape as delete/rewrite would leave: Dr Supplies 100, Dr GST 10, Cr AP 110
    assert live_net.get("6200") == Decimal("100")
    assert live_net.get("1400") == Decimal("10")
    assert live_net.get("2000") == Decimal("-110")
    assert "6100" not in live_net

    # --- 3. Reject → reverse live accrual; history retained ---
    await clear_invoice_posting_artifacts(db_session, inv)
    await db_session.flush()

    live_after_reject = (
        await db_session.execute(
            select(JournalEntry)
            .join(JournalBatch, JournalBatch.id == JournalEntry.batch_id)
            .where(
                *journal_entries_for_invoice(inv.tenant_id, inv.id),
                JournalBatch.status == JournalBatchStatus.POSTED.value,
                JournalBatch.reversal_reason.is_(None),
            )
        )
    ).scalars().all()
    assert live_after_reject == []
    assert _net_by_account(
        (
            await db_session.execute(
                select(JournalEntry).where(
                    *journal_entries_for_invoice(inv.tenant_id, inv.id)
                )
            )
        ).scalars().all()
    ) == {}

    total_rows = (
        await db_session.execute(
            select(func.count())
            .select_from(JournalEntry)
            .where(*journal_entries_for_invoice(inv.tenant_id, inv.id))
        )
    ).scalar_one()
    # 9 after remap + 3 reject reversal
    assert total_rows == 12

    # Chain: original → remap_reversal; remapped_accrual → reject_reversal
    remapped = (
        await db_session.execute(
            select(JournalBatch).where(
                JournalBatch.invoice_id == inv.id,
                JournalBatch.reversal_reason.is_(None),
                JournalBatch.id != original_batch.id,
            )
        )
    ).scalars().all()
    assert len(remapped) == 1
    remapped_batch = remapped[0]
    assert remapped_batch.status == JournalBatchStatus.REVERSED.value
    assert remapped_batch.reversed_by_batch_id is not None
    reject_rev = await db_session.get(JournalBatch, remapped_batch.reversed_by_batch_id)
    assert reject_rev is not None
    assert reject_rev.reversal_reason == "reject_clear_artifacts"

    # Sanity: expected_live_net from first post still describes the *pre-remap* world
    assert expected_live_net.get("6100") == Decimal("100")
