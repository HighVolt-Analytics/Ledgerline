"""Reset invoice rows for reprocess / approval."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import Invoice, InvoiceStatus
from app.models.journal import JournalEntry
from app.models.line_item import LineItem
from app.services.invoice.processing_override_catalog import (
    clear_processing_overrides,
    skip_steps_for,
)
from app.tenant_child_tables import journal_entries_for_invoice, line_items_for_invoice

# Keys left by the not-understood (OCR → classify → full extract) path that must not
# mix with vision-header fields when the understood path vaults.
_NOT_UNDERSTOOD_EXTRACTED_FIELD_KEYS: frozenset[str] = frozenset(
    {
        "subtotal",
        "gst",
        "gst_rate",
        "due_date",
        "line_items",
        "abn",
        "cost_centre",
        "billing_address",
        "bank_bsb",
        "bank_account",
        "bank_name",
        "bank_details",
        "account_code",
        "account_name",
        "document_text",
        "field_confidence",
        "di_line_items",
        "table_line_items",
        "azure_di_line_items",
        "azure_di_scalar_fields",
        "grn_reference",
        "remittance_reference",
        "statement_reference",
        "statement_period",
    }
)


async def reset_invoice_for_reprocess(
    session: AsyncSession,
    inv: Invoice,
    *,
    preserve_document_type: bool = False,
    clear_overrides: bool = True,
) -> None:
    """Clear extracted data and journal lines; set status to pending."""
    if clear_overrides:
        clear_processing_overrides(inv)
    inv.status = InvoiceStatus.PENDING
    inv.vendor = None
    inv.abn = None
    inv.invoice_no = None
    inv.po_reference = None
    inv.cost_centre = None
    inv.invoice_date = None
    inv.due_date = None
    inv.subtotal = None
    inv.gst = None
    inv.gst_rate = None
    inv.total = None
    # Clear so reprocess can re-detect; do not keep a stale wrong ISO.
    inv.currency = ""
    inv.billing_address = None
    inv.bank_bsb = None
    inv.bank_account = None
    inv.validation_results = None
    inv.account_code = None
    inv.account_name = None
    inv.purchase_document_type = None
    if not preserve_document_type:
        inv.document_type_code = None
        inv.document_type_confidence = None
        inv.llm_suggested_dt = None
        inv.llm_confidence = None
    inv.document_text = None
    inv.document_heading = None
    inv.extracted_fields = None
    inv.route_target = None
    inv.matched_rule_ids = None
    inv.evaluation_status = None
    inv.so_reference = None
    inv.sales_document_type = None

    for entry in (
        await session.execute(
            select(JournalEntry).where(*journal_entries_for_invoice(inv.tenant_id, inv.id))
        )
    ).scalars().all():
        await session.delete(entry)

    for line in (
        await session.execute(select(LineItem).where(*line_items_for_invoice(inv.tenant_id, inv.id)))
    ).scalars().all():
        await session.delete(line)

    from app.services.classification.classification_learning_service import (
        clear_ocr_artifacts_for_invoice,
    )

    await clear_ocr_artifacts_for_invoice(
        session,
        tenant_id=inv.tenant_id,
        invoice_id=inv.id,
    )

    await session.flush()


async def reset_invoice_for_approval(session: AsyncSession, inv: Invoice) -> None:
    """Re-queue for pipeline while preserving user-corrected extracted fields."""
    inv.status = InvoiceStatus.PENDING
    inv.validation_results = None
    inv.account_code = None
    inv.account_name = None

    with session.no_autoflush:
        entries = (
            await session.execute(
                select(JournalEntry).where(*journal_entries_for_invoice(inv.tenant_id, inv.id))
            )
        ).scalars().all()
    for entry in entries:
        await session.delete(entry)

    await session.flush()


async def clear_invoice_posting_artifacts(session: AsyncSession, inv: Invoice) -> None:
    """Remove journal/posting data when a processed invoice is rejected."""
    inv.account_code = None
    inv.account_name = None
    inv.validation_results = None

    for entry in (
        await session.execute(
            select(JournalEntry).where(*journal_entries_for_invoice(inv.tenant_id, inv.id))
        )
    ).scalars().all():
        await session.delete(entry)

    for line in (
        await session.execute(select(LineItem).where(*line_items_for_invoice(inv.tenant_id, inv.id)))
    ).scalars().all():
        await session.delete(line)

    await session.flush()


async def should_preserve_extracted_on_requeue(
    session: AsyncSession,
    inv: Invoice,
    *,
    manual_edits: bool | None = None,
) -> bool:
    """Keep clerk-corrected header fields when re-queuing from the review queue."""
    if inv.status != InvoiceStatus.EXCEPTION:
        return False
    from app.services.approval.approval_pipeline_service import payable_fields_complete
    from app.services.invoice.invoice_edit_service import invoice_has_manual_field_edits

    if manual_edits is None:
        manual_edits = await invoice_has_manual_field_edits(
            session,
            inv.id,
            tenant_id=inv.tenant_id,
        )
    return manual_edits or payable_fields_complete(inv)


async def clear_stale_not_understood_for_understood_path(
    session: AsyncSession,
    inv: Invoice,
    *,
    preserve_document_type: bool = False,
) -> dict[str, object]:
    """Drop not-understood leftovers when the understood (vision) path vaults.

    Reprocess defers ``reset_invoice_for_reprocess`` until OCR quality gates pass.
    The understood path returns earlier (header + vault), so prior line items,
    DT-XX classification, and full-extract scalars would otherwise remain mixed
    with the vision header (e.g. ₹79k lines vs ₹9.8k total).
    """
    from app.services.invoice.processing_override_catalog import clear_deferred_full_reset

    cleared_line_ids: list[int] = []
    for line in (
        await session.execute(
            select(LineItem).where(*line_items_for_invoice(inv.tenant_id, inv.id))
        )
    ).scalars().all():
        cleared_line_ids.append(int(line.id))
        await session.delete(line)
    # Avoid touching inv.line_items (lazy load / MissingGreenlet); expire instead.
    session.expire(inv, ["line_items"])

    # Full-extract / posting columns — not written by vision header.
    inv.due_date = None
    inv.subtotal = None
    inv.gst = None
    inv.gst_rate = None
    inv.abn = None
    inv.cost_centre = None
    inv.billing_address = None
    inv.bank_bsb = None
    inv.bank_account = None
    inv.document_text = None
    inv.validation_results = None
    inv.account_code = None
    inv.account_name = None
    inv.purchase_document_type = None
    inv.sales_document_type = None
    inv.matched_rule_ids = None
    inv.route_target = None

    dt_cleared = False
    if not preserve_document_type:
        if inv.document_type_code or inv.document_type_confidence is not None:
            dt_cleared = True
        inv.document_type_code = None
        inv.document_type_confidence = None
        inv.llm_suggested_dt = None
        inv.llm_confidence = None

    stripped_keys: list[str] = []
    fields = inv.extracted_fields if isinstance(inv.extracted_fields, dict) else None
    if fields:
        kept = {
            key: value
            for key, value in fields.items()
            if key not in _NOT_UNDERSTOOD_EXTRACTED_FIELD_KEYS
        }
        stripped_keys = sorted(set(fields) - set(kept))
        inv.extracted_fields = kept or None

    clear_deferred_full_reset(inv)
    await session.flush()
    return {
        "cleared_line_item_ids": cleared_line_ids,
        "cleared_line_item_count": len(cleared_line_ids),
        "cleared_document_type": dt_cleared,
        "stripped_extracted_field_keys": stripped_keys,
    }


async def requeue_invoice_for_pipeline(
    session: AsyncSession,
    inv: Invoice,
    *,
    preserve_document_type: bool = False,
    preserve_extracted_fields: bool = False,
) -> None:
    """Queue for pipeline; defer destructive field wipe until OCR gates pass."""
    if preserve_extracted_fields:
        await reset_invoice_for_approval(session, inv)
        return
    from app.models.journal import JournalEntry
    from app.services.classification.classification_learning_service import (
        clear_ocr_artifacts_for_invoice,
    )
    from app.services.invoice.processing_override_catalog import set_deferred_full_reset

    inv.status = InvoiceStatus.PENDING
    inv.validation_results = None
    inv.account_code = None
    inv.account_name = None
    inv.evaluation_status = None

    for entry in (
        await session.execute(
            select(JournalEntry).where(*journal_entries_for_invoice(inv.tenant_id, inv.id))
        )
    ).scalars().all():
        await session.delete(entry)

    # Clear before pipeline so phase_ocr cannot reuse pre-filter table_line_items
    await clear_ocr_artifacts_for_invoice(
        session,
        tenant_id=inv.tenant_id,
        invoice_id=inv.id,
    )
    set_deferred_full_reset(inv)
    await session.flush()
