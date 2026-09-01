"""Batch bank-payment file export orchestration (e.g. AU ABA).

Ties together: Scheduled payments -> their vendor's trusted bank details
(the same VendorMaster data VR13 already validated at invoice-approval
time) -> the tenant's own remitter config -> a BankFileFormat writer.

This deliberately does not move money -- it only produces a file for a
human to upload into their own bank's business banking portal, consistent
with the rest of the manual payment execution flow (see
payment_execution_instruction_service.py, which carries the same
disclaimer).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import Invoice
from app.models.payment import Payment, PaymentStatus
from app.services.audit.audit_service import log_event
from app.services.master_data.vendor_detection import find_matching_vendor_master
from app.services.payments.bank_file_formats.base import (
    BankFileFormatError,
    BankFilePaymentLine,
    BankFileRemitter,
    BankFileResult,
)
from app.services.payments.bank_file_formats.registry import get_bank_file_format
from app.services.rule_book.rule_book_mapper import load_classification_config


class BankFileExportError(ValueError):
    """Batch couldn't be exported -- surfaced to the API as a 4xx."""


async def generate_batch_payment_file(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    payment_ids: list[int],
    *,
    actor_name: str | None = None,
    processing_date: date | None = None,
) -> tuple[BankFileResult, list[Payment]]:
    """Validate a set of Scheduled payments and build their batch file.

    Raises BankFileExportError for anything that should block the export
    (wrong status, already exported, missing vendor bank details, missing
    remitter config, currency mismatch, malformed data) -- callers should
    surface the message directly, it's written to be shown to the user.
    """
    if not payment_ids:
        raise BankFileExportError("Select at least one payment to export.")
    if len(set(payment_ids)) != len(payment_ids):
        raise BankFileExportError("Duplicate payment IDs in the batch selection.")

    config = await load_classification_config(db, tenant_id)
    settings = config.bank_file_settings
    format_code = (settings.format or "").strip().upper()
    if not format_code:
        raise BankFileExportError(
            "No batch payment file format is configured for this tenant. "
            "Set one up in Payments → Bank file settings first."
        )
    try:
        fmt = get_bank_file_format(format_code)
    except BankFileFormatError as exc:
        raise BankFileExportError(str(exc)) from exc

    rows = (
        (
            await db.execute(
                select(Payment).where(
                    Payment.tenant_id == tenant_id,
                    Payment.id.in_(payment_ids),
                )
            )
        )
        .scalars()
        .all()
    )
    found_ids = {p.id for p in rows}
    missing = set(payment_ids) - found_ids
    if missing:
        raise BankFileExportError(f"Payment(s) not found: {sorted(missing)}")

    for p in rows:
        if p.status != PaymentStatus.SCHEDULED:
            raise BankFileExportError(
                f"Payment {p.id} is {p.status.value}, not Scheduled -- only Scheduled "
                "payments can be included in a batch file."
            )
        if p.bank_file_batch_reference:
            raise BankFileExportError(
                f"Payment {p.id} was already exported in batch {p.bank_file_batch_reference!r}."
            )

    lines: list[BankFilePaymentLine] = []
    for p in rows:
        master = find_matching_vendor_master(p.vendor or "", None, config.vendor_masters)
        if master is None or not master.bank.bsb or not master.bank.account_number:
            raise BankFileExportError(
                f"Payment {p.id} ({p.vendor or 'unknown vendor'}): no bank details on file in "
                "the vendor master. Add BSB + account number there before exporting."
            )
        invoice = await db.get(Invoice, p.invoice_id)
        raw_reference = (invoice.invoice_no if invoice and invoice.invoice_no else "") or f"PAYMENT {p.id}"
        amount = p.bank_payment_amount if p.bank_payment_amount is not None else p.amount
        lines.append(
            BankFilePaymentLine(
                payment_id=p.id,
                vendor_name=p.vendor or master.name,
                amount=Decimal(amount),
                currency=(p.currency or "").strip().upper() or fmt.expected_currency,
                reference=raw_reference,
                bank_name=master.bank.bank_name,
                routing_code=master.bank.bsb or "",
                account_number=master.bank.account_number,
                account_name=master.bank.account_name or master.name,
            )
        )

    remitter_cfg = settings.remitter
    if not remitter_cfg.routing_code or not remitter_cfg.account_number:
        raise BankFileExportError(
            "Your own remitting bank account isn't configured -- set it in "
            "Payments → Bank file settings before exporting."
        )
    remitter = BankFileRemitter(
        legal_name=remitter_cfg.account_name,
        display_name=remitter_cfg.remittance_display_name or remitter_cfg.account_name,
        bank_name=remitter_cfg.bank_name,
        routing_code=remitter_cfg.routing_code,
        account_number=remitter_cfg.account_number,
        extra={
            "aba_user_id_number": settings.aba_user_id_number,
            "aba_financial_institution_code": settings.aba_financial_institution_code,
        },
    )

    proc_date = processing_date or datetime.now(timezone.utc).date()
    try:
        result = fmt.generate(
            lines=lines,
            remitter=remitter,
            processing_date=proc_date,
            description=settings.aba_description,
        )
    except BankFileFormatError as exc:
        raise BankFileExportError(str(exc)) from exc

    batch_reference = f"{format_code}-{proc_date.strftime('%Y%m%d')}-{uuid.uuid4().hex[:8].upper()}"
    now = datetime.now(timezone.utc)
    for p in rows:
        p.bank_file_batch_reference = batch_reference
        p.bank_file_exported_at = now
        await log_event(
            db,
            "payment_bank_file_exported",
            invoice_id=p.invoice_id,
            tenant_id=tenant_id,
            actor_name=actor_name,
            detail={
                "payment_id": p.id,
                "format": format_code,
                "batch_reference": batch_reference,
                "amount": float(p.amount) if p.amount is not None else None,
                "vendor": p.vendor,
            },
        )
    await db.flush()

    return result, rows
