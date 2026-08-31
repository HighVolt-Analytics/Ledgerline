"""Reset invoice rows for reprocess / approval."""

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import Invoice, InvoiceStatus
from app.models.journal import JournalEntry
from app.models.line_item import LineItem
from app.services.invoice.processing_override_catalog import (
    clear_processing_overrides,
    set_preserve_extracted_fields,
    skip_steps_for,
)
from app.tenant_child_tables import journal_entries_for_invoice, line_items_for_invoice
from app.services.payments.journal_reversal_service import reverse_batches_for_entries

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
        "seller_abn",
        "buyer_abn",
        "seller_tax_id",
        "buyer_tax_id",
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

# Header / tax-id scalars vision is expected to rewrite. OCR-only artifacts
# (di_line_items, azure_di_*, document_text, GL codes) are never restored.
_RESTORABLE_EXTRACTED_FIELD_KEYS: frozenset[str] = frozenset(
    {
        "subtotal",
        "gst",
        "gst_rate",
        "due_date",
        "abn",
        "seller_abn",
        "buyer_abn",
        "seller_tax_id",
        "buyer_tax_id",
        "cost_centre",
        "billing_address",
        "bank_bsb",
        "bank_account",
        "bank_name",
        "bank_details",
    }
)

_RESTORABLE_INVOICE_COLUMNS: tuple[str, ...] = (
    "due_date",
    "subtotal",
    "gst",
    "gst_rate",
    "abn",
    "cost_centre",
    "billing_address",
    "bank_bsb",
    "bank_account",
)

# Confidence ceiling when remapping fails and we keep the prior DT for display/posting.
_PRIOR_DT_RESTORE_CONFIDENCE = 0.35


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
    inv.team_expense_kind = None
    inv.linked_advance_invoice_id = None
    inv.matched_rule_ids = None
    inv.evaluation_status = None
    inv.so_reference = None
    inv.sales_document_type = None

    entries = (
        await session.execute(
            select(JournalEntry).where(*journal_entries_for_invoice(inv.tenant_id, inv.id))
        )
    ).scalars().all()
    await reverse_batches_for_entries(session, entries, reason="reprocess_reset")

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
    set_preserve_extracted_fields(inv)
    inv.status = InvoiceStatus.PENDING
    # Approval is the resume path for sticky pending_approval / await PO|SO holds.
    # Leaving evaluation_status set would re-stick the hold after a successful reprocess.
    inv.evaluation_status = None
    inv.validation_results = None
    inv.account_code = None
    inv.account_name = None

    with session.no_autoflush:
        entries = (
            await session.execute(
                select(JournalEntry).where(*journal_entries_for_invoice(inv.tenant_id, inv.id))
            )
        ).scalars().all()
    await reverse_batches_for_entries(session, entries, reason="approval_reset")

    await session.flush()


async def clear_invoice_posting_artifacts(session: AsyncSession, inv: Invoice) -> None:
    """Remove journal/posting data when a processed invoice is rejected."""
    inv.account_code = None
    inv.account_name = None
    inv.validation_results = None

    entries = (
        await session.execute(
            select(JournalEntry).where(*journal_entries_for_invoice(inv.tenant_id, inv.id))
        )
    ).scalars().all()
    await reverse_batches_for_entries(session, entries, reason="reject_clear_artifacts")

    for line in (
        await session.execute(select(LineItem).where(*line_items_for_invoice(inv.tenant_id, inv.id)))
    ).scalars().all():
        await session.delete(line)

    await session.flush()


_PRESERVE_REQUEUE_STATUSES = frozenset(
    {
        InvoiceStatus.EXCEPTION,
        InvoiceStatus.REJECTED,
        InvoiceStatus.DUPLICATE_SKIPPED,
    }
)


async def should_preserve_extracted_on_requeue(
    session: AsyncSession,
    inv: Invoice,
    *,
    manual_edits: bool | None = None,
) -> bool:
    """Keep clerk-corrected header fields when re-queuing from the review queue.

    Rejected / duplicate-skipped rows only preserve after a clerk edit in this
    cycle. Reprocess-without-edit still does a full re-extract.
    """
    if inv.status not in _PRESERVE_REQUEUE_STATUSES:
        return False
    from app.services.approval.approval_pipeline_service import (
        document_type_definition_for_invoice,
        payable_fields_complete,
    )
    from app.services.invoice.invoice_edit_service import invoice_has_manual_field_edits

    if manual_edits is None:
        manual_edits = await invoice_has_manual_field_edits(
            session,
            inv.id,
            tenant_id=inv.tenant_id,
        )
    if inv.status in {InvoiceStatus.REJECTED, InvoiceStatus.DUPLICATE_SKIPPED}:
        return bool(manual_edits)
    definition = await document_type_definition_for_invoice(session, inv)
    return manual_edits or payable_fields_complete(inv, definition)


def _column_empty(value: object) -> bool:
    if value is None:
        return True
    if isinstance(value, str) and not value.strip():
        return True
    return False


def _extracted_value_empty(value: object) -> bool:
    if value is None:
        return True
    if isinstance(value, str) and not value.strip():
        return True
    return False


async def clear_stale_not_understood_for_understood_path(
    session: AsyncSession,
    inv: Invoice,
    *,
    preserve_document_type: bool = False,
) -> dict[str, object]:
    """Drop not-understood leftovers before vision header extract on understood path.

    Reprocess defers ``reset_invoice_for_reprocess`` until OCR quality gates pass.
    Call this *before* vision header persist so prior OCR line items, DT-XX
    classification, and full-extract scalars do not mix with the new header
    (e.g. ₹79k OCR lines vs ₹9.8k vision total). Vision header then rewrites
    posting fields (subtotal/gst/abn/line_items) that stick through vault.

    Returns a snapshot of cleared header scalars / DT so the pipeline can restore
    anything vision did not refill (and re-apply prior DT when remap yields nothing).
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

    column_snapshot: dict[str, object] = {}
    for attr in _RESTORABLE_INVOICE_COLUMNS:
        value = getattr(inv, attr, None)
        if not _column_empty(value):
            column_snapshot[attr] = value

    prior_document_type_code = (inv.document_type_code or "").strip().upper() or None
    prior_document_type_confidence = inv.document_type_confidence
    prior_llm_suggested_dt = (inv.llm_suggested_dt or "").strip().upper() or None
    prior_llm_confidence = inv.llm_confidence

    # Clear OCR leftovers; vision header extract rewrites posting columns next.
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
    inv.team_expense_kind = None
    inv.linked_advance_invoice_id = None

    dt_cleared = False
    if not preserve_document_type:
        if inv.document_type_code or inv.document_type_confidence is not None:
            dt_cleared = True
        inv.document_type_code = None
        inv.document_type_confidence = None
        inv.llm_suggested_dt = None
        inv.llm_confidence = None

    stripped_keys: list[str] = []
    extracted_snapshot: dict[str, object] = {}
    fields = inv.extracted_fields if isinstance(inv.extracted_fields, dict) else None
    if fields:
        for key, value in fields.items():
            if (
                key in _RESTORABLE_EXTRACTED_FIELD_KEYS
                and not _extracted_value_empty(value)
            ):
                extracted_snapshot[key] = value
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
        "prior_document_type_code": prior_document_type_code,
        "prior_document_type_confidence": prior_document_type_confidence,
        "prior_llm_suggested_dt": prior_llm_suggested_dt,
        "prior_llm_confidence": prior_llm_confidence,
        "column_snapshot": column_snapshot,
        "extracted_snapshot": extracted_snapshot,
    }


_AMOUNT_EPS = Decimal("0.05")


def _money_restore_would_disagree(
    inv: Invoice,
    *,
    attr: str,
    prior: object,
) -> bool:
    """Skip stale restore when re-applying subtotal/gst would break header math."""
    if attr not in {"subtotal", "gst"}:
        return False
    total = inv.total
    if total is None:
        return False
    try:
        restored = Decimal(str(prior))
    except Exception:
        return False
    subtotal = restored if attr == "subtotal" else inv.subtotal
    gst = restored if attr == "gst" else inv.gst
    if subtotal is None:
        return False
    tax = gst if gst is not None else Decimal("0")
    return (subtotal + tax - total).copy_abs() > _AMOUNT_EPS


def restore_unrefilled_vision_stale_snapshot(
    inv: Invoice,
    stale_clear: dict[str, object] | None,
) -> dict[str, object]:
    """Re-apply prior header values for keys vision extract left empty.

    Call after ``persist_vision_header_to_invoice`` / ``phase_vision_header_extract``.
    Does not overwrite non-empty vision results.
    """
    if not stale_clear:
        return {"restored_columns": [], "restored_extracted_keys": []}

    restored_columns: list[str] = []
    column_snapshot = stale_clear.get("column_snapshot")
    if isinstance(column_snapshot, dict):
        for attr, prior in column_snapshot.items():
            if attr not in _RESTORABLE_INVOICE_COLUMNS:
                continue
            if _money_restore_would_disagree(inv, attr=attr, prior=prior):
                continue
            if _column_empty(getattr(inv, attr, None)) and not _column_empty(prior):
                setattr(inv, attr, prior)
                restored_columns.append(str(attr))

    restored_extracted: list[str] = []
    extracted_snapshot = stale_clear.get("extracted_snapshot")
    if isinstance(extracted_snapshot, dict) and extracted_snapshot:
        fields = dict(inv.extracted_fields or {})
        changed = False
        for key, prior in extracted_snapshot.items():
            if key not in _RESTORABLE_EXTRACTED_FIELD_KEYS:
                continue
            if key in {"subtotal", "gst"} and _money_restore_would_disagree(
                inv, attr=key, prior=prior
            ):
                continue
            if _extracted_value_empty(fields.get(key)) and not _extracted_value_empty(prior):
                fields[key] = prior
                restored_extracted.append(str(key))
                changed = True
        if changed:
            inv.extracted_fields = fields

    restored_columns.sort()
    restored_extracted.sort()
    return {
        "restored_columns": restored_columns,
        "restored_extracted_keys": restored_extracted,
    }


def restore_prior_document_type_if_unmapped(
    inv: Invoice,
    stale_clear: dict[str, object] | None,
    *,
    preserve_document_type: bool = False,
) -> dict[str, object]:
    """When vision DT remap yields nothing, put the cleared prior DT back.

    Keeps Fields-tab / posting config from going blank. Caps confidence so the
    UI can still treat the code as needing review when appropriate.
    """
    if preserve_document_type:
        return {"restored": False, "reason": "human_locked"}
    if (inv.document_type_code or "").strip():
        return {"restored": False, "reason": "already_mapped"}
    if not stale_clear:
        return {"restored": False, "reason": "no_snapshot"}

    prior_code = stale_clear.get("prior_document_type_code")
    token = str(prior_code or "").strip().upper()
    if not token:
        return {"restored": False, "reason": "no_prior_dt"}

    prior_conf = stale_clear.get("prior_document_type_confidence")
    try:
        conf = float(prior_conf) if prior_conf is not None else _PRIOR_DT_RESTORE_CONFIDENCE
    except (TypeError, ValueError):
        conf = _PRIOR_DT_RESTORE_CONFIDENCE
    conf = min(max(conf, 0.0), _PRIOR_DT_RESTORE_CONFIDENCE)

    from app.services.extraction.llm_document_service import apply_document_type_to_invoice

    prior_llm = stale_clear.get("prior_llm_suggested_dt")
    prior_llm_conf = stale_clear.get("prior_llm_confidence")
    apply_document_type_to_invoice(
        inv,
        code=token,
        confidence=conf,
        llm_suggested_dt=str(prior_llm).strip().upper() if prior_llm else None,
        llm_confidence=float(prior_llm_conf)
        if isinstance(prior_llm_conf, (int, float))
        else None,
    )
    return {
        "restored": True,
        "code": token,
        "confidence": conf,
        "reason": "prior_dt_after_unmap",
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

    entries = (
        await session.execute(
            select(JournalEntry).where(*journal_entries_for_invoice(inv.tenant_id, inv.id))
        )
    ).scalars().all()
    await reverse_batches_for_entries(session, entries, reason="requeue_pipeline")

    # Clear before pipeline so phase_ocr cannot reuse pre-filter table_line_items
    await clear_ocr_artifacts_for_invoice(
        session,
        tenant_id=inv.tenant_id,
        invoice_id=inv.id,
    )
    set_deferred_full_reset(inv)
    await session.flush()
