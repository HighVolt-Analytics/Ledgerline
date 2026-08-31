"""Persist journal lines to the database."""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import Invoice
from app.models.journal import JournalEntry, JournalEntryKind
from app.models.journal_batch import JournalBatch
from app.services.payments.fiscal_period_service import ensure_period_open
from app.services.payments.journal_fx import (
    FX_SOURCE_LEGACY,
    apply_line_fx,
    invoice_currency_code,
    normalize_txn_currency,
    resolve_accrual_fx,
)
from app.services.payments.journal_generator import JournalLine


async def persist_journal_lines(
    session: AsyncSession,
    invoice: Invoice | None,
    lines: list[JournalLine],
    *,
    entry_kind: JournalEntryKind = JournalEntryKind.INVOICE_ACCRUAL,
    payment_id: int | None = None,
    collection_id: int | None = None,
    base_currency: str | None = None,
    tenant_id: uuid.UUID | None = None,
) -> JournalBatch:
    if invoice is None:
        if tenant_id is None:
            raise ValueError("tenant_id is required when invoice is None")
        resolved_tenant_id = tenant_id
        invoice_id = None
        txn_currency = normalize_txn_currency(
            next((line.txn_currency for line in lines if line.txn_currency), None)
        )
    else:
        resolved_tenant_id = invoice.tenant_id
        invoice_id = invoice.id
        txn_currency = invoice_currency_code(invoice)

    base = (base_currency or "").strip().upper()
    if lines:
        # All lines in one call share one posting date in practice
        # (see journal_generator.py / settlement_journal_service.py).
        await ensure_period_open(session, resolved_tenant_id, lines[0].date)
    # One batch per persist_journal_lines() call. Assigning entry.batch=batch
    # (rather than requiring batch.id up front) lets SQLAlchemy order the
    # insert/FK resolution at flush time, so this stays a plain sync function
    # and no caller needs to change.
    batch = JournalBatch(
        tenant_id=resolved_tenant_id,
        invoice_id=invoice_id,
        entry_kind=entry_kind,
        payment_id=payment_id,
        collection_id=collection_id,
    )
    session.add(batch)

    accrual_like = entry_kind in (
        JournalEntryKind.INVOICE_ACCRUAL,
        JournalEntryKind.BANK_CREATE,
        JournalEntryKind.BANK_TRANSFER,
    )

    for line in lines:
        line_txn = (line.txn_currency or txn_currency).strip().upper()
        line_base = (line.base_currency or base or "").strip().upper()
        fx_rate = line.fx_rate
        fx_source = (line.fx_source or "").strip()

        if not fx_source:
            if accrual_like:
                fx_rate, _, fx_source = resolve_accrual_fx(
                    txn_currency=line_txn,
                    base_currency=line_base,
                )
            else:
                fx_source = FX_SOURCE_LEGACY

        fx_fields = apply_line_fx(
            debit=Decimal(str(line.debit or 0)),
            credit=Decimal(str(line.credit or 0)),
            txn_currency=line_txn,
            base_currency=line_base,
            fx_rate=fx_rate,
            fx_source=fx_source,
        )
        if line.base_debit is not None:
            fx_fields["base_debit"] = line.base_debit
        if line.base_credit is not None:
            fx_fields["base_credit"] = line.base_credit
        if line.fx_rate is not None:
            fx_fields["fx_rate"] = line.fx_rate
        if line.fx_source:
            fx_fields["fx_source"] = line.fx_source
        if line.txn_currency:
            fx_fields["txn_currency"] = line.txn_currency.strip().upper() or None
        if line.base_currency:
            fx_fields["base_currency"] = line.base_currency.strip().upper() or None

        session.add(
            JournalEntry(
                batch=batch,
                tenant_id=resolved_tenant_id,
                invoice_id=invoice_id,
                date=line.date,
                account_code=line.account_code,
                account_name=line.account_name,
                debit=line.debit,
                credit=line.credit,
                entry_type=line.entry_type,
                vendor_registry_id=line.vendor_registry_id,
                customer_registry_id=line.customer_registry_id,
                entry_kind=entry_kind,
                payment_id=payment_id,
                collection_id=collection_id,
                txn_currency=fx_fields["txn_currency"],  # type: ignore[arg-type]
                base_currency=fx_fields["base_currency"],  # type: ignore[arg-type]
                base_debit=fx_fields["base_debit"],  # type: ignore[arg-type]
                base_credit=fx_fields["base_credit"],  # type: ignore[arg-type]
                fx_rate=fx_fields["fx_rate"],  # type: ignore[arg-type]
                fx_source=fx_fields["fx_source"],  # type: ignore[arg-type]
            )
        )
    return batch
