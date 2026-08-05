"""Build invoice API responses from ORM rows."""

from __future__ import annotations

import asyncio
import json
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog
from app.models.invoice import Invoice
from app.schemas.invoice import (
    EvaluationStatus,
    InvoiceResponse,
    InvoiceStatus as InvoiceStatusSchema,
    ValidationResultItem,
    parse_evaluation_status,
)
from app.models.invoice import InvoiceStatus
from app.services.audit.audit_service import audit_logs_for_invoices
from app.services.classification.document_type_playbook_service import (
    effective_document_type_code,
    extraction_fields_for_invoice_code,
)
from app.services.extraction.field_extraction_confidence import compute_extraction_field_confidence
from app.services.shared.file_storage import (
    has_stored_path,
    repair_invoice_stored_path,
    stored_file_available,
)
from app.services.invoice.invoice_evaluation_service import (
    load_config_for_tenant,
    parse_matched_rule_ids,
)
from app.services.invoice.processing_override_catalog import normalise_processing_overrides
from app.services.invoice.pipeline_stages import (
    derive_current_stage,
    derive_list_stage,
    derive_resolution_hint,
)
from app.services.classification.document_type_validation_service import (
    display_validation_pass_percent,
    validation_pass_applicable,
)
from app.services.master_data.vendor_registration_policy import (
    persisted_vendor_confidence,
    resolve_document_type_definition,
    vendor_registration_required,
)


def parse_validation_results(raw: str | None) -> list[ValidationResultItem] | None:
    if not raw:
        return None
    try:
        from app.services.rule_book.validator import normalize_stored_validation_results

        rows = normalize_stored_validation_results(json.loads(raw))
        return [ValidationResultItem(**item) for item in rows]
    except (json.JSONDecodeError, TypeError):
        return None


def classification_review_confidence(
    inv: Invoice, detail: dict[str, object]
) -> float | None:
    if inv.llm_confidence is not None:
        try:
            return round(float(inv.llm_confidence), 4)
        except (TypeError, ValueError):
            pass
    raw = detail.get("llm_confidence")
    if raw is None:
        return None
    try:
        return round(float(raw), 4)
    except (TypeError, ValueError):
        return None


def _document_text_if_loaded(inv: Invoice) -> str | None:
    """Return document_text when already on the instance; None if deferred/expired.

    List invoices defer ``document_text``. Touching an unloaded deferred column
    under async SQLAlchemy raises MissingGreenlet — never trigger that load.
    """
    try:
        from sqlalchemy import inspect as sa_inspect

        state = sa_inspect(inv)
        # Only use the value if it is already present in the instance dict.
        if "document_text" not in state.dict:
            return None
    except Exception:
        pass
    return (getattr(inv, "document_text", None) or "") or ""


def _legacy_awaiting_maps_to_vision_vaulted(inv: Invoice) -> bool:
    """True when awaiting_classification is a vision-understood hold (not OCR classify).

    Prefer explicit vision markers. Only use empty OCR body when ``document_text``
    is already loaded — never lazy-load it.
    """
    fields = inv.extracted_fields if isinstance(inv.extracted_fields, dict) else {}
    if fields.get("vision_bundle_kind") is not None or fields.get("vision_bundle_key"):
        return True
    if fields.get("vision_header_confidence") or fields.get("canonical_document_type"):
        return True
    heading = (inv.document_heading or "").strip()
    if not heading:
        return False
    body = _document_text_if_loaded(inv)
    if body is None:
        # Deferred on list: heading + no DT is the historical understood-path shape.
        return not (inv.document_type_code or "").strip()
    return not body.strip()


def _is_vision_header_fields_contract(inv: Invoice) -> bool:
    """Vision understood path lean fields before catalogue DT is mapped."""
    from app.services.invoice.invoice_evaluation_service import VISION_UNDERSTOOD_EVAL_STATUSES

    if (inv.evaluation_status or "").strip() not in VISION_UNDERSTOOD_EVAL_STATUSES:
        return False
    body = _document_text_if_loaded(inv)
    if body is None:
        # Deferred text — still the lean contract when no catalogue DT is mapped.
        return not (inv.document_type_code or "").strip()
    return not body.strip()


async def document_type_extraction_fields(
    db: AsyncSession, tenant_id: uuid.UUID, inv: Invoice
) -> list[str]:
    # Pre-DT understood hold: lean type-suggest keys for new path; legacy header keys otherwise.
    if _is_vision_header_fields_contract(inv):
        fields = inv.extracted_fields if isinstance(inv.extracted_fields, dict) else {}
        if fields.get("vision_type_suggest_confidence") or not fields.get(
            "vision_header_confidence"
        ):
            from app.services.invoice.vision_type_suggest import (
                VISION_TYPE_SUGGEST_PERSISTED_FIELD_KEYS,
            )

            return list(VISION_TYPE_SUGGEST_PERSISTED_FIELD_KEYS)
        from app.services.invoice.vision_header_schema import VISION_HEADER_PERSISTED_FIELD_KEYS

        return list(VISION_HEADER_PERSISTED_FIELD_KEYS)

    config = await load_config_for_tenant(db, tenant_id)
    code = effective_document_type_code(inv, list(config.document_types))
    if not code:
        return []
    return extraction_fields_for_invoice_code(code, list(config.document_types))


def _inbox_display_fields(
    inv: Invoice,
    *,
    document_types: list | None,
    validation_items: list[ValidationResultItem] | None,
) -> tuple[float | None, int | None, EvaluationStatus | None]:
    """Normalize inbox column values for list/detail API responses."""
    definition = resolve_document_type_definition(
        inv.document_type_code,
        document_types=document_types,
    )
    registration_required = vendor_registration_required(
        route_target=inv.route_target,
        document_type=definition,
        purchase_document_type=inv.purchase_document_type,
    )
    vendor_confidence = persisted_vendor_confidence(
        confidence=float(inv.vendor_confidence or 0),
        registration_required=registration_required,
    )
    vr_applicable = validation_pass_applicable(
        route_target=inv.route_target,
        document_type=definition,
        purchase_document_type=inv.purchase_document_type,
    )
    validation_pass_rate = display_validation_pass_percent(
        validation_items,
        applicable=vr_applicable,
    )
    evaluation_status = parse_evaluation_status(inv.evaluation_status)
    if evaluation_status == EvaluationStatus.PENDING_VENDOR and vendor_confidence is None:
        vendor_confidence = 0.0
    # PROCESSED ⇒ coding review is closed. Remap / stale rows may still store
    # needs_review after a deterministic DT→GL post; never surface that as an
    # open review hold (matches frontend effectiveEvaluationStatus).
    if (
        inv.status == InvoiceStatus.PROCESSED
        and evaluation_status == EvaluationStatus.NEEDS_REVIEW
    ):
        evaluation_status = EvaluationStatus.AUTO_CODED
    # Coding finished but pipeline halted later — do not show a green Auto coded
    # badge on Upload; surface as actionable Needs review.
    if (
        inv.status == InvoiceStatus.EXCEPTION
        and evaluation_status == EvaluationStatus.AUTO_CODED
    ):
        evaluation_status = EvaluationStatus.NEEDS_REVIEW
    # Legacy understood-path rows still stored as awaiting_classification.
    if evaluation_status == EvaluationStatus.AWAITING_CLASSIFICATION:
        if _legacy_awaiting_maps_to_vision_vaulted(inv):
            evaluation_status = EvaluationStatus.VISION_VAULTED
    return vendor_confidence, validation_pass_rate, evaluation_status


def invoice_to_response(
    inv: Invoice,
    *,
    has_stored_file: bool | None = None,
    document_type_extraction_fields: list[str] | None = None,
    include_extraction_field_confidence: bool = False,
    published_to_ledger: bool = False,
    audit_logs: list[AuditLog] | None = None,
    current_stage: str | None = None,
    current_stage_state: str | None = None,
    document_types: list | None = None,
    for_list: bool = False,
) -> InvoiceResponse:
    stored_ok = (
        has_stored_file
        if has_stored_file is not None
        else has_stored_path(inv.raw_file_path)
    )
    logs = list(audit_logs or [])
    if current_stage is None or current_stage_state is None:
        # Prefer audit-backed stage whenever logs are available (Upload list
        # now hydrates audits so Stage matches the document drawer).
        if logs:
            stage_label, stage_state = derive_current_stage(inv, logs)
        elif for_list:
            stage_label, stage_state = derive_list_stage(inv)
        else:
            stage_label, stage_state = derive_current_stage(inv, [])
        current_stage = current_stage or stage_label
        current_stage_state = current_stage_state or stage_state
    validation_items = parse_validation_results(inv.validation_results)
    vendor_confidence, validation_pass_rate, evaluation_status = _inbox_display_fields(
        inv,
        document_types=document_types,
        validation_items=validation_items,
    )
    resolution_hint = derive_resolution_hint(inv, logs)
    if (
        inv.status == InvoiceStatus.EXCEPTION
        and evaluation_status == EvaluationStatus.NEEDS_REVIEW
        and not resolution_hint
    ):
        resolution_hint = "Open document drawer — check Fields, Audit, or Lines tabs"
    from app.services.classification.document_type_playbook_profile_service import (
        gl_posting_applicable_for_invoice,
    )

    gl_posting_applicable = gl_posting_applicable_for_invoice(
        inv,
        document_types=document_types,
    )
    display_account_code = inv.account_code if gl_posting_applicable else None
    display_account_name = inv.account_name if gl_posting_applicable else None
    return InvoiceResponse(
        id=inv.id,
        document_ref=inv.document_ref,
        vendor=inv.vendor,
        abn=inv.abn,
        invoice_no=inv.invoice_no,
        po_reference=inv.po_reference,
        so_reference=inv.so_reference,
        sales_document_type=inv.sales_document_type,
        cost_centre=inv.cost_centre,
        invoice_date=inv.invoice_date,
        due_date=inv.due_date,
        currency=inv.currency,
        subtotal=inv.subtotal,
        gst=inv.gst,
        gst_rate=inv.gst_rate,
        total=inv.total,
        status=InvoiceStatusSchema(inv.status.value),
        file_hash=inv.file_hash,
        raw_file_path=inv.raw_file_path,
        email_sender=inv.email_sender,
        capture_source=inv.capture_source,
        connected_mailbox_id=inv.connected_mailbox_id,
        storage_vendor_slug=inv.storage_vendor_slug,
        account_code=display_account_code,
        account_name=display_account_name,
        route_target=inv.route_target,
        team_expense_kind=getattr(inv, "team_expense_kind", None),
        linked_advance_invoice_id=getattr(inv, "linked_advance_invoice_id", None),
        matched_rule_ids=parse_matched_rule_ids(inv.matched_rule_ids) or None,
        vendor_confidence=vendor_confidence,
        evaluation_status=evaluation_status,
        duplicate_review_suggested=bool(getattr(inv, "duplicate_review_suggested", False)),
        purchase_document_type=inv.purchase_document_type,
        document_type_code=inv.document_type_code,
        document_type_confidence=inv.document_type_confidence,
        llm_suggested_dt=getattr(inv, "llm_suggested_dt", None),
        llm_confidence=getattr(inv, "llm_confidence", None),
        bank_bsb=inv.bank_bsb,
        bank_account=inv.bank_account,
        email_attachment_name=inv.email_attachment_name,
        billing_address=inv.billing_address,
        email_subject=inv.email_subject if not for_list else None,
        document_text=inv.document_text if not for_list else None,
        document_heading=getattr(inv, "document_heading", None),
        extracted_fields=getattr(inv, "extracted_fields", None) or None,
        validation_results=validation_items,
        validation_pass_rate=validation_pass_rate,
        extraction_field_confidence=(
            compute_extraction_field_confidence(inv)
            if include_extraction_field_confidence
            else None
        ),
        created_at=inv.created_at,
        has_stored_file=stored_ok,
        published_to_ledger=published_to_ledger,
        gl_posting_applicable=gl_posting_applicable,
        current_stage=current_stage,
        current_stage_state=current_stage_state,
        resolution_hint=resolution_hint,
        processing_overrides=(
            normalise_processing_overrides(getattr(inv, "processing_overrides", None))
            if not for_list
            else None
        ),
        approval_chain=getattr(inv, "approval_chain", None) or None,
        document_type_extraction_fields=(
            document_type_extraction_fields if not for_list else None
        ),
    )


class InvoiceTenantScopeError(ValueError):
    """Invoice row tenant_id does not match the authenticated tenant scope."""


async def _ensure_invoice_attached(db: AsyncSession, inv: Invoice) -> Invoice:
    """Re-bind invoice rows after session.invalidate() from transient DB retries."""
    from sqlalchemy import inspect as sa_inspect

    if sa_inspect(inv).session is db:
        return inv
    if inv.id is not None:
        attached = await db.get(Invoice, inv.id)
        if attached is not None:
            return attached
    return await db.merge(inv)


def assert_invoice_tenant_scope(rows: list[Invoice], tenant_id: uuid.UUID) -> None:
    for row in rows:
        if row.tenant_id != tenant_id:
            raise InvoiceTenantScopeError(
                f"Invoice {row.id} belongs to tenant {row.tenant_id}, expected {tenant_id}"
            )


async def _responses_for_invoices_once(
    db: AsyncSession,
    rows: list[Invoice],
    *,
    tenant_id: uuid.UUID,
    published_ids: set[int] | None,
    for_list: bool = False,
) -> list[InvoiceResponse]:
    if not rows:
        return []
    rows = [await _ensure_invoice_attached(db, row) for row in rows]
    assert_invoice_tenant_scope(rows, tenant_id)
    invoice_ids = [row.id for row in rows]
    if for_list:
        from app.services.invoice.invoice_evaluation_service import load_posting_config_for_tenant

        config = await load_posting_config_for_tenant(db, tenant_id)
        document_types = list(config.document_types)
        # Hydrate audits so Upload Stage/Evaluation match the document drawer.
        audit_by_id = await audit_logs_for_invoices(
            db, invoice_ids, tenant_id=tenant_id
        )
        return [
            invoice_to_response(
                row,
                published_to_ledger=False,
                audit_logs=audit_by_id.get(row.id, []),
                document_types=document_types,
                for_list=True,
            )
            for row in rows
        ]
    if published_ids is None:
        from app.services.integration.publish_service import published_invoice_ids

        published_ids = await published_invoice_ids(db, invoice_ids, tenant_id=tenant_id)
    audit_by_id = await audit_logs_for_invoices(db, invoice_ids, tenant_id=tenant_id)
    config = await load_config_for_tenant(db, tenant_id)
    document_types = list(config.document_types)
    return [
        invoice_to_response(
            row,
            published_to_ledger=row.id in published_ids,
            audit_logs=audit_by_id.get(row.id, []),
            document_types=document_types,
            for_list=for_list,
        )
        for row in rows
    ]


async def responses_for_invoices(
    db: AsyncSession,
    rows: list[Invoice],
    *,
    tenant_id: uuid.UUID,
    published_ids: set[int] | None = None,
    for_list: bool = False,
) -> list[InvoiceResponse]:
    if not rows:
        return []
    from app.db_transient import run_with_transient_db_retry

    invoice_ids = [row.id for row in rows]

    async def _run() -> list[InvoiceResponse]:
        attached = []
        for invoice_id in invoice_ids:
            row = await db.get(Invoice, invoice_id)
            if row is not None:
                attached.append(row)
        return await _responses_for_invoices_once(
            db,
            attached,
            tenant_id=tenant_id,
            published_ids=published_ids,
            for_list=for_list,
        )

    return await run_with_transient_db_retry(db, _run)


async def responses_for_approval_board(
    db: AsyncSession,
    rows: list[Invoice],
    *,
    tenant_id: uuid.UUID,
) -> list[InvoiceResponse]:
    """Lightweight kanban payload — no per-invoice audit hydration or refetch."""
    if not rows:
        return []
    from app.db_transient import run_with_transient_db_retry
    from app.services.integration.publish_service import published_invoice_ids
    from app.services.invoice.invoice_evaluation_service import load_posting_config_for_tenant

    invoice_ids = [row.id for row in rows]

    async def _run() -> list[InvoiceResponse]:
        attached = [await _ensure_invoice_attached(db, row) for row in rows]
        assert_invoice_tenant_scope(attached, tenant_id)
        published = await published_invoice_ids(db, invoice_ids, tenant_id=tenant_id)
        config = await load_posting_config_for_tenant(db, tenant_id)
        document_types = list(config.document_types)
        audit_by_id = await audit_logs_for_invoices(
            db, invoice_ids, tenant_id=tenant_id
        )
        return [
            invoice_to_response(
                row,
                published_to_ledger=row.id in published,
                audit_logs=audit_by_id.get(row.id, []),
                document_types=document_types,
                for_list=True,
            )
            for row in attached
        ]

    return await run_with_transient_db_retry(db, _run)


async def _response_for_invoice_once(
    db: AsyncSession,
    inv: Invoice,
    *,
    tenant_id: uuid.UUID,
    verify_stored_file: bool = False,
    repair_stored_path: bool = False,
    **kwargs,
) -> InvoiceResponse:
    inv = await _ensure_invoice_attached(db, inv)
    assert_invoice_tenant_scope([inv], tenant_id)
    if repair_stored_path:
        await repair_invoice_stored_path(db, inv)
    if verify_stored_file or repair_stored_path:
        if "has_stored_file" not in kwargs:
            kwargs["has_stored_file"] = await asyncio.to_thread(
                stored_file_available,
                inv.raw_file_path,
                tenant_id=inv.tenant_id,
            )
    logs = list(
        (
            await db.execute(
                select(AuditLog)
                .where(
                    AuditLog.invoice_id == inv.id,
                    AuditLog.tenant_id == inv.tenant_id,
                )
                .order_by(AuditLog.created_at.desc())
            )
        ).scalars().all()
    )
    published = kwargs.pop("published_to_ledger", None)
    if published is None:
        from app.services.integration.publish_service import is_published_to_ledger

        published = await is_published_to_ledger(db, inv.id)
    config = await load_config_for_tenant(db, tenant_id)
    return invoice_to_response(
        inv,
        published_to_ledger=published,
        audit_logs=logs,
        document_types=list(config.document_types),
        **kwargs,
    )


async def response_for_invoice(
    db: AsyncSession,
    inv: Invoice,
    *,
    tenant_id: uuid.UUID,
    verify_stored_file: bool = False,
    repair_stored_path: bool = False,
    **kwargs,
) -> InvoiceResponse:
    from app.db_transient import run_with_transient_db_retry

    invoice_id = inv.id

    async def _run() -> InvoiceResponse:
        row = await db.get(Invoice, invoice_id)
        if row is None:
            raise InvoiceTenantScopeError(f"Invoice {invoice_id} not found")
        return await _response_for_invoice_once(
            db,
            row,
            tenant_id=tenant_id,
            verify_stored_file=verify_stored_file,
            repair_stored_path=repair_stored_path,
            **kwargs,
        )

    return await run_with_transient_db_retry(db, _run)
