"""Build invoice API responses from ORM rows."""

from __future__ import annotations

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
from app.services.audit_service import audit_logs_for_invoices
from app.services.document_type_playbook_service import (
    effective_document_type_code,
    extraction_fields_for_invoice_code,
)
from app.services.field_extraction_confidence import compute_extraction_field_confidence
from app.services.file_storage import (
    has_stored_path,
    repair_invoice_stored_path,
    stored_file_available,
)
from app.services.invoice_evaluation_service import (
    ROUTE_VAULT,
    load_config_for_tenant,
    parse_matched_rule_ids,
)
from app.services.processing_override_catalog import normalise_processing_overrides
from app.services.pipeline_stages import derive_current_stage
from app.services.document_type_validation_service import (
    display_validation_pass_percent,
    validation_pass_applicable,
)
from app.services.vendor_registration_policy import (
    persisted_vendor_confidence,
    resolve_document_type_definition,
    vendor_registration_required,
)


def parse_validation_results(raw: str | None) -> list[ValidationResultItem] | None:
    if not raw:
        return None
    try:
        from app.services.validator import normalize_stored_validation_results

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


async def document_type_extraction_fields(
    db: AsyncSession, tenant_id: uuid.UUID, inv: Invoice
) -> list[str]:
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
    if (
        inv.status == InvoiceStatus.PROCESSED
        and (inv.route_target or "").strip() == ROUTE_VAULT
        and evaluation_status == EvaluationStatus.NEEDS_REVIEW
    ):
        evaluation_status = EvaluationStatus.AUTO_CODED
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
) -> InvoiceResponse:
    stored_ok = (
        has_stored_file
        if has_stored_file is not None
        else has_stored_path(inv.raw_file_path)
    )
    if current_stage is None or current_stage_state is None:
        stage_label, stage_state = derive_current_stage(inv, audit_logs or [])
        current_stage = current_stage or stage_label
        current_stage_state = current_stage_state or stage_state
    validation_items = parse_validation_results(inv.validation_results)
    vendor_confidence, validation_pass_rate, evaluation_status = _inbox_display_fields(
        inv,
        document_types=document_types,
        validation_items=validation_items,
    )
    return InvoiceResponse(
        id=inv.id,
        document_ref=inv.document_ref,
        vendor=inv.vendor,
        abn=inv.abn,
        invoice_no=inv.invoice_no,
        po_reference=inv.po_reference,
        cost_centre=inv.cost_centre,
        invoice_date=inv.invoice_date,
        due_date=inv.due_date,
        currency=inv.currency,
        subtotal=inv.subtotal,
        gst=inv.gst,
        total=inv.total,
        status=InvoiceStatusSchema(inv.status.value),
        file_hash=inv.file_hash,
        raw_file_path=inv.raw_file_path,
        email_sender=inv.email_sender,
        capture_source=inv.capture_source,
        connected_mailbox_id=inv.connected_mailbox_id,
        storage_vendor_slug=inv.storage_vendor_slug,
        account_code=inv.account_code,
        account_name=inv.account_name,
        route_target=inv.route_target,
        matched_rule_ids=parse_matched_rule_ids(inv.matched_rule_ids) or None,
        vendor_confidence=vendor_confidence,
        evaluation_status=evaluation_status,
        purchase_document_type=inv.purchase_document_type,
        document_type_code=inv.document_type_code,
        document_type_confidence=inv.document_type_confidence,
        llm_suggested_dt=getattr(inv, "llm_suggested_dt", None),
        llm_confidence=getattr(inv, "llm_confidence", None),
        document_type_extraction_fields=document_type_extraction_fields,
        bank_bsb=inv.bank_bsb,
        bank_account=inv.bank_account,
        email_attachment_name=inv.email_attachment_name,
        billing_address=inv.billing_address,
        email_subject=inv.email_subject,
        document_text=inv.document_text,
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
        current_stage=current_stage,
        current_stage_state=current_stage_state,
        processing_overrides=normalise_processing_overrides(
            getattr(inv, "processing_overrides", None)
        ),
    )


async def _responses_for_invoices_once(
    db: AsyncSession,
    rows: list[Invoice],
    *,
    published_ids: set[int] | None,
) -> list[InvoiceResponse]:
    invoice_ids = [row.id for row in rows]
    tenant_id = rows[0].tenant_id
    if published_ids is None:
        from app.services.publish_service import published_invoice_ids

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
        )
        for row in rows
    ]


async def responses_for_invoices(
    db: AsyncSession,
    rows: list[Invoice],
    *,
    published_ids: set[int] | None = None,
) -> list[InvoiceResponse]:
    if not rows:
        return []
    from app.db_transient import run_with_transient_db_retry

    return await run_with_transient_db_retry(
        db,
        lambda: _responses_for_invoices_once(db, rows, published_ids=published_ids),
    )


async def response_for_invoice(
    db: AsyncSession,
    inv: Invoice,
    *,
    verify_stored_file: bool = False,
    repair_stored_path: bool = False,
    **kwargs,
) -> InvoiceResponse:
    if repair_stored_path:
        await repair_invoice_stored_path(db, inv)
    if verify_stored_file or repair_stored_path:
        if "has_stored_file" not in kwargs:
            kwargs["has_stored_file"] = stored_file_available(
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
        from app.services.publish_service import is_published_to_ledger

        published = await is_published_to_ledger(db, inv.id)
    config = await load_config_for_tenant(db, inv.tenant_id)
    return invoice_to_response(
        inv,
        published_to_ledger=published,
        audit_logs=logs,
        document_types=list(config.document_types),
        **kwargs,
    )
