import json
from datetime import date
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import Response
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import AuthContext, actor_from_context, get_auth_context, get_db, require_admin
from app.config import get_settings
from app.models.invoice import Invoice, InvoiceStatus
from app.models.tenant import Tenant
from app.models.audit import AuditLog
from app.models.journal import JournalEntry
from app.models.line_item import LineItem
from app.schemas.common import ApiEnvelope, ResponseMeta
from app.schemas.invoice import (
    EvaluationStatus,
    InvoiceResponse,
    InvoiceStatus as InvoiceStatusSchema,
    InvoiceUpdateRequest,
    InvoiceWithDetails,
    parse_evaluation_status,
    ProcessInvoicesBatchRequest,
    ValidationResultItem,
)
from app.schemas.classification_api import ClassificationResolveRequest, ClassificationReviewItem
from app.services.classification_learning_service import record_learning_from_resolution
from app.services.llm_document_service import apply_document_type_to_invoice
from app.services.invoice_reset import reset_invoice_for_reprocess
from app.services.invoice_edit_service import update_invoice_fields
from app.services.invoice_evaluation_service import (
    apply_invoice_evaluation,
    load_config_for_tenant,
    parse_matched_rule_ids,
)
from app.schemas.journal import JournalEntryResponse
from app.schemas.line_item import LineItemResponse
from app.schemas.purchase import PurchaseDossierResponse
from app.services.audit_service import audit_logs_for_invoices, log_event
from app.services.file_storage import (
    ensure_invoice_stored_file,
    has_stored_path,
    read_invoice_file,
    repair_invoice_stored_path,
    store_invoice_pdf,
    stored_file_available,
)
from app.services.approval_service import restore_rejected_invoice_file_if_needed
from app.schemas.pipeline import PipelineStepsResponse
from app.services.pipeline_stages import (
    build_pipeline_stages,
    derive_current_stage,
    pipeline_steps_for_api,
)
from app.services.remap_service import remap_invoices_for_tenant
from app.services.vendor_resolver import UNKNOWN_SLUG
from app.utils.hashing import compute_sha256_bytes
from app.services.document_type_playbook_service import (
    effective_document_type_code,
    extraction_fields_for_invoice_code,
)
from app.services.field_extraction_confidence import compute_extraction_field_confidence
from app.services.ingest_fanout_service import DuplicateUploadError, ingest_upload_file
from app.services.purchase_dossier_service import build_purchase_dossier
from app.tenant_child_tables import journal_entries_for_invoice, line_items_for_invoice
from app.tenant_scoped import get_for_tenant
from app.workers.tasks import process_invoice_background, process_invoices_batch_background

router = APIRouter(prefix="/invoices", tags=["invoices"])


def _classification_review_confidence(inv: Invoice, detail: dict[str, object]) -> float | None:
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

_MAX_UPLOAD_BYTES = 25 * 1024 * 1024


async def _document_type_extraction_fields(
    db: AsyncSession, tenant_id: int, inv: Invoice
) -> list[str]:
    config = await load_config_for_tenant(db, tenant_id)
    code = effective_document_type_code(inv, list(config.document_types))
    if not code:
        return []
    return extraction_fields_for_invoice_code(code, list(config.document_types))


async def _read_upload_file(file: UploadFile, *, max_bytes: int = _MAX_UPLOAD_BYTES) -> bytes:
    data = await file.read()
    if len(data) > max_bytes:
        raise HTTPException(
            413,
            f"File exceeds maximum size ({max_bytes // (1024 * 1024)} MB)",
        )
    return data


async def _get_invoice_for_tenant(
    db: AsyncSession, invoice_id: int, tenant_id
) -> Invoice:
    inv = await get_for_tenant(db, Invoice, invoice_id, tenant_id)
    if not inv:
        raise HTTPException(404, "Invoice not found")
    return inv


def _validation(raw: str | None) -> list[ValidationResultItem] | None:
    if not raw:
        return None
    try:
        return [ValidationResultItem(**item) for item in json.loads(raw)]
    except (json.JSONDecodeError, TypeError):
        return None


def _to_response(
    inv: Invoice,
    *,
    has_stored_file: bool | None = None,
    document_type_extraction_fields: list[str] | None = None,
    include_extraction_field_confidence: bool = False,
    published_to_ledger: bool = False,
    audit_logs: list[AuditLog] | None = None,
    current_stage: str | None = None,
    current_stage_state: str | None = None,
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
        vendor_confidence=inv.vendor_confidence,
        evaluation_status=parse_evaluation_status(inv.evaluation_status),
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
        validation_results=_validation(inv.validation_results),
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
    )


async def _responses_for_invoices(
    db: AsyncSession,
    rows: list[Invoice],
    *,
    published_ids: set[int] | None = None,
) -> list[InvoiceResponse]:
    if not rows:
        return []
    invoice_ids = [row.id for row in rows]
    tenant_id = rows[0].tenant_id
    if published_ids is None:
        from app.services.publish_service import published_invoice_ids

        published_ids = await published_invoice_ids(db, invoice_ids, tenant_id=tenant_id)
    audit_by_id = await audit_logs_for_invoices(db, invoice_ids, tenant_id=tenant_id)
    return [
        _to_response(
            row,
            published_to_ledger=row.id in published_ids,
            audit_logs=audit_by_id.get(row.id, []),
        )
        for row in rows
    ]


async def _response_for_invoice(
    db: AsyncSession,
    inv: Invoice,
    *,
    verify_stored_file: bool = False,
    **kwargs,
) -> InvoiceResponse:
    if verify_stored_file:
        await repair_invoice_stored_path(db, inv)
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
    return _to_response(inv, published_to_ledger=published, audit_logs=logs, **kwargs)


@router.get("", response_model=ApiEnvelope[list[InvoiceResponse]])
async def list_invoices(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: InvoiceStatusSchema | None = None,
    vendor: str | None = Query(None, description="Filter by vendor name (partial match)"),
    connected_mailbox_id: int | None = Query(
        None, description="Filter by connected mailbox (inbox source)"
    ),
    invoice_date_from: date | None = None,
    invoice_date_to: date | None = None,
    route_target: str | None = Query(None, description="Filter by rule book route target"),
    evaluation_status: EvaluationStatus | None = None,
    q: str | None = Query(
        None,
        description="Search vendor, invoice no, PO, document ref, route, GL account, or id",
    ),
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[list[InvoiceResponse]]:
    stmt = (
        select(Invoice)
        .where(Invoice.tenant_id == ctx.tenant_id)
        .order_by(Invoice.created_at.desc(), Invoice.id.desc())
    )
    count_stmt = select(func.count(Invoice.id)).where(Invoice.tenant_id == ctx.tenant_id)

    def _apply_filters(query):
        if status:
            query = query.where(Invoice.status == InvoiceStatus(status.value))
        if vendor and vendor.strip():
            query = query.where(Invoice.vendor.ilike(f"%{vendor.strip()}%"))
        if invoice_date_from is not None:
            query = query.where(Invoice.invoice_date >= invoice_date_from)
        if invoice_date_to is not None:
            query = query.where(Invoice.invoice_date <= invoice_date_to)
        if connected_mailbox_id is not None:
            query = query.where(Invoice.connected_mailbox_id == connected_mailbox_id)
        if route_target and route_target.strip():
            query = query.where(Invoice.route_target == route_target.strip())
        if evaluation_status is not None:
            query = query.where(Invoice.evaluation_status == evaluation_status.value)
        if q and q.strip():
            term = f"%{q.strip()}%"
            clauses = [
                Invoice.vendor.ilike(term),
                Invoice.invoice_no.ilike(term),
                Invoice.po_reference.ilike(term),
                Invoice.document_ref.ilike(term),
                Invoice.route_target.ilike(term),
                Invoice.account_name.ilike(term),
                Invoice.cost_centre.ilike(term),
                Invoice.document_type_code.ilike(term),
            ]
            raw = q.strip()
            if raw.isdigit():
                clauses.append(Invoice.id == int(raw))
            query = query.where(or_(*clauses))
        return query

    stmt = _apply_filters(stmt)
    count_stmt = _apply_filters(count_stmt)

    total = (await db.execute(count_stmt)).scalar() or 0
    pages = max(1, (total + page_size - 1) // page_size)
    rows = (
        await db.execute(stmt.offset((page - 1) * page_size).limit(page_size))
    ).scalars().all()

    return ApiEnvelope(
        data=await _responses_for_invoices(db, list(rows)),
        meta=ResponseMeta(page=page, total=total, pages=pages),
    )


@router.get("/classification-review", response_model=ApiEnvelope[list[ClassificationReviewItem]])
async def classification_review_queue(
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[list[ClassificationReviewItem]]:
    """Invoices awaiting human document-type confirmation before field extraction."""
    rows = (
        await db.execute(
            select(Invoice)
            .where(
                Invoice.tenant_id == ctx.tenant_id,
                Invoice.status == InvoiceStatus.EXCEPTION,
                Invoice.evaluation_status == "awaiting_classification",
            )
            .order_by(Invoice.created_at.desc())
            .limit(limit)
        )
    ).scalars().all()
    items: list[ClassificationReviewItem] = []
    for inv in rows:
        routing_row = (
            await db.execute(
                select(AuditLog)
                .where(
                    AuditLog.invoice_id == inv.id,
                    AuditLog.tenant_id == ctx.tenant_id,
                    AuditLog.event == "routing_review_required",
                )
                .order_by(AuditLog.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        resolved_row = (
            await db.execute(
                select(AuditLog)
                .where(
                    AuditLog.invoice_id == inv.id,
                    AuditLog.tenant_id == ctx.tenant_id,
                    AuditLog.event == "classification_resolved",
                )
                .order_by(AuditLog.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if resolved_row and routing_row:
            routing_detail = (
                routing_row.detail if isinstance(routing_row.detail, dict) else {}
            )
            if str(routing_detail.get("gate") or "").strip().lower() == "classification":
                if resolved_row.created_at >= routing_row.created_at:
                    continue
        audit_row = (
            await db.execute(
                select(AuditLog)
                .where(
                    AuditLog.invoice_id == inv.id,
                    AuditLog.tenant_id == ctx.tenant_id,
                    AuditLog.event == "document_classified",
                )
                .order_by(AuditLog.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        detail = audit_row.detail if audit_row and isinstance(audit_row.detail, dict) else {}
        items.append(
            ClassificationReviewItem(
                invoice_id=inv.id,
                document_ref=inv.document_ref,
                status=inv.status.value if hasattr(inv.status, "value") else str(inv.status),
                evaluation_status=inv.evaluation_status,
                llm_suggested_dt=inv.llm_suggested_dt or detail.get("llm_suggested_dt"),
                llm_confidence=_classification_review_confidence(inv, detail),
                policy_winner_dt=str(detail.get("policy_winner_dt") or ""),
                document_type_code=inv.document_type_code,
                review_reasons=[str(reason) for reason in (detail.get("review_reasons") or [])],
                document_ai_provider=str(detail.get("document_ai_provider") or "") or None,
            )
        )
    return ApiEnvelope(data=items)


@router.get("/{invoice_id:int}", response_model=ApiEnvelope[InvoiceWithDetails])
async def get_invoice(
    invoice_id: int,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[InvoiceWithDetails]:
    stmt = (
        select(Invoice)
        .where(Invoice.id == invoice_id, Invoice.tenant_id == ctx.tenant_id)
        .options(
            selectinload(Invoice.line_items),
            selectinload(Invoice.journal_entries),
        )
    )
    inv = (await db.execute(stmt)).scalar_one_or_none()
    if not inv:
        raise HTTPException(404, "Invoice not found")

    base = await _response_for_invoice(
        db,
        inv,
        verify_stored_file=True,
        document_type_extraction_fields=await _document_type_extraction_fields(db, ctx.tenant_id, inv),
        include_extraction_field_confidence=True,
    )
    return ApiEnvelope(
        data=InvoiceWithDetails(
            **base.model_dump(),
            line_items=[LineItemResponse.model_validate(li) for li in inv.line_items],
            journal_entries=[
                JournalEntryResponse.model_validate(je) for je in inv.journal_entries
            ],
        )
    )


@router.patch("/{invoice_id:int}", response_model=ApiEnvelope[InvoiceWithDetails])
async def patch_invoice(
    invoice_id: int,
    body: InvoiceUpdateRequest,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[InvoiceWithDetails]:
    """Update missing or incorrect fields on invoices in the approval review queue."""
    stmt = (
        select(Invoice)
        .where(Invoice.id == invoice_id, Invoice.tenant_id == ctx.tenant_id)
        .options(
            selectinload(Invoice.line_items),
            selectinload(Invoice.journal_entries),
        )
    )
    inv = (await db.execute(stmt)).scalar_one_or_none()
    if not inv:
        raise HTTPException(404, "Invoice not found")

    actor_name, actor_email = await actor_from_context(db, ctx)
    try:
        await update_invoice_fields(
            db,
            inv,
            body,
            actor_name=actor_name,
            actor_email=actor_email,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    await db.flush()
    inv = (
        await db.execute(stmt.execution_options(populate_existing=True))
    ).scalar_one()
    base = await _response_for_invoice(
        db,
        inv,
        document_type_extraction_fields=await _document_type_extraction_fields(db, ctx.tenant_id, inv),
        include_extraction_field_confidence=True,
    )
    return ApiEnvelope(
        data=InvoiceWithDetails(
            **base.model_dump(),
            line_items=[LineItemResponse.model_validate(li) for li in inv.line_items],
            journal_entries=[
                JournalEntryResponse.model_validate(je) for je in inv.journal_entries
            ],
        )
    )


@router.get("/{invoice_id:int}/file")
async def download_invoice_file(
    invoice_id: int,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> Response:
    """Download the stored invoice attachment (PDF, image, or DOCX)."""
    inv = await _get_invoice_for_tenant(db, invoice_id, ctx.tenant_id)
    try:
        await ensure_invoice_stored_file(db, inv)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc

    try:
        data, media_type, filename = read_invoice_file(
            inv.raw_file_path,  # type: ignore[arg-type]
            tenant_id=ctx.tenant_id,
        )
    except FileNotFoundError as exc:
        raise HTTPException(404, "Stored file not found on disk or blob") from exc

    return Response(
        content=data,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{invoice_id:int}/line-items", response_model=ApiEnvelope[list[LineItemResponse]])
async def get_line_items(
    invoice_id: int,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[list[LineItemResponse]]:
    await _get_invoice_for_tenant(db, invoice_id, ctx.tenant_id)
    rows = (
        await db.execute(
            select(LineItem).where(*line_items_for_invoice(ctx.tenant_id, invoice_id))
        )
    ).scalars().all()
    return ApiEnvelope(data=[LineItemResponse.model_validate(r) for r in rows])


@router.get(
    "/{invoice_id:int}/journal-entries",
    response_model=ApiEnvelope[list[JournalEntryResponse]],
)
async def get_journal_entries(
    invoice_id: int,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[list[JournalEntryResponse]]:
    await _get_invoice_for_tenant(db, invoice_id, ctx.tenant_id)
    rows = (
        await db.execute(
            select(JournalEntry).where(
                *journal_entries_for_invoice(ctx.tenant_id, invoice_id),
            )
        )
    ).scalars().all()
    return ApiEnvelope(data=[JournalEntryResponse.model_validate(r) for r in rows])


@router.post("/process-batch", response_model=ApiEnvelope[dict])
async def process_invoices_batch(
    background_tasks: BackgroundTasks,
    body: ProcessInvoicesBatchRequest,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[dict]:
    """Run the pipeline sequentially for invoices uploaded with defer_processing."""
    unique_ids = list(dict.fromkeys(body.invoice_ids))
    rows = (
        await db.execute(
            select(Invoice.id).where(
                Invoice.id.in_(unique_ids),
                Invoice.tenant_id == ctx.tenant_id,
            )
        )
    ).scalars().all()
    found = set(rows)
    if len(found) != len(unique_ids):
        raise HTTPException(404, "One or more invoices not found")
    ordered = [invoice_id for invoice_id in unique_ids if invoice_id in found]
    settings = get_settings()
    if settings.sync_processing:
        background_tasks.add_task(
            process_invoices_batch_background, ordered, tenant_id=ctx.tenant_id
        )
    else:
        try:
            from app.workers.tasks import process_inbox_task

            process_inbox_task.delay(tenant_id=ctx.tenant_id)
        except Exception:
            background_tasks.add_task(
                process_invoices_batch_background, ordered, tenant_id=ctx.tenant_id
            )
    return ApiEnvelope(data={"queued": len(ordered), "status": "running"})


async def _queue_upload_processing(
    background_tasks: BackgroundTasks,
    invoice_ids: list[int],
    *,
    defer_processing: bool,
    tenant_id: int,
) -> None:
    if defer_processing or not invoice_ids:
        return
    settings = get_settings()
    if len(invoice_ids) == 1:
        if settings.sync_processing:
            background_tasks.add_task(
                process_invoice_background, invoice_ids[0], tenant_id=tenant_id
            )
        else:
            try:
                from app.workers.tasks import process_inbox_task

                process_inbox_task.delay(tenant_id=tenant_id)
            except Exception:
                background_tasks.add_task(
                    process_invoice_background, invoice_ids[0], tenant_id=tenant_id
                )
        return

    if settings.sync_processing:
        background_tasks.add_task(
            process_invoices_batch_background, invoice_ids, tenant_id=tenant_id
        )
        return
    try:
        from app.workers.tasks import process_inbox_task

        process_inbox_task.delay(tenant_id=tenant_id)
    except Exception:
        background_tasks.add_task(
            process_invoices_batch_background, invoice_ids, tenant_id=tenant_id
        )


@router.post("/upload", response_model=ApiEnvelope[InvoiceResponse])
async def upload_invoice(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    purchase_document_type: str | None = Query(
        None,
        description="Purchase document type when uploading PO/GRN/invoice: po, grn, invoice",
    ),
    defer_processing: bool = Query(
        False,
        description="Skip immediate pipeline run (use with POST /process-batch)",
    ),
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[InvoiceResponse]:
    allowed = (".pdf", ".jpg", ".jpeg", ".png", ".docx")
    if not file.filename or not file.filename.lower().endswith(allowed):
        raise HTTPException(400, "Accepted: PDF, JPG, PNG, DOCX")

    data = await _read_upload_file(file)
    if not data:
        raise HTTPException(400, "Empty file")

    org = await db.get(Tenant, ctx.tenant_id)
    tenant_slug = org.slug if org else "default"
    tenant_name = org.name if org else None

    try:
        result = await ingest_upload_file(
            db,
            tenant_id=ctx.tenant_id,
            tenant_slug=tenant_slug,
            tenant_name=tenant_name,
            filename=Path(file.filename).name,
            data=data,
            purchase_document_type=purchase_document_type,
        )
    except DuplicateUploadError:
        raise HTTPException(409, "Duplicate file already uploaded") from None

    primary = await _get_invoice_for_tenant(db, result.invoice_ids[0], ctx.tenant_id)
    if not defer_processing:
        # Commit before background task so the new row is visible to the pipeline worker.
        await db.commit()
    await _queue_upload_processing(
        background_tasks,
        result.invoice_ids,
        defer_processing=defer_processing,
        tenant_id=ctx.tenant_id,
    )

    meta = ResponseMeta(
        segment_count=result.segment_count,
        segment_invoice_ids=result.invoice_ids if result.segment_count > 1 else None,
    )
    return ApiEnvelope(
        data=await _response_for_invoice(db, primary, has_stored_file=True),
        meta=meta,
    )


_ALLOWED_ATTACH = (".pdf", ".jpg", ".jpeg", ".png", ".docx")


@router.post("/{invoice_id:int}/attach", response_model=ApiEnvelope[InvoiceResponse])
async def attach_invoice_file(
    invoice_id: int,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[InvoiceResponse]:
    """
    Attach or replace the stored PDF/image for an existing invoice.

    Use when the row has no file (e.g. seed data) or the file was lost from disk/blob.
    Then approve or POST /reprocess and run /api/process/trigger.
    """
    inv = await _get_invoice_for_tenant(db, invoice_id, ctx.tenant_id)
    if not file.filename or not file.filename.lower().endswith(_ALLOWED_ATTACH):
        raise HTTPException(400, "Accepted: PDF, JPG, PNG, DOCX")

    data = await _read_upload_file(file)
    if not data:
        raise HTTPException(400, "Empty file")

    file_hash = compute_sha256_bytes(data)
    from app.services.document_duplicate_service import find_invoice_by_file_hash

    other = await find_invoice_by_file_hash(db, file_hash, tenant_id=ctx.tenant_id)
    if other and other.id != invoice_id:
        raise HTTPException(
            409,
            f"Duplicate of invoice {other.id}; that file is already in the system",
        )

    org = await db.get(Tenant, ctx.tenant_id)
    tenant_slug = org.slug if org else "default"
    tenant_name = org.name if org else None
    vendor_slug = inv.storage_vendor_slug or UNKNOWN_SLUG
    from app.services.invoice_evaluation_service import load_config_for_tenant
    from app.services.vault_invoice_paths import (
        vault_document_type_folder_for_invoice,
        vault_document_type_titles_for_invoice,
    )

    config = await load_config_for_tenant(db, ctx.tenant_id)
    doc_types = list(config.document_types)
    short_title, title = vault_document_type_titles_for_invoice(inv, doc_types)
    dt_folder = vault_document_type_folder_for_invoice(inv, doc_types)
    stored = store_invoice_pdf(
        data,
        ctx.tenant_id,
        tenant_slug,
        vendor_slug,
        inv.id,
        file_hash,
        Path(file.filename).name,
        tenant_name=tenant_name,
        vendor_name=inv.vendor,
        invoice_no=inv.invoice_no,
        invoice_date=inv.invoice_date,
        route_target=inv.route_target,
        po_reference=inv.po_reference,
        purchase_document_type=inv.purchase_document_type,
        document_type_code=inv.document_type_code,
        document_type_short_title=short_title,
        document_type_title=title,
        document_type_folder=dt_folder,
    )
    inv.raw_file_path = stored
    inv.file_hash = file_hash
    if not inv.storage_vendor_slug:
        inv.storage_vendor_slug = vendor_slug

    await log_event(
        db,
        "invoice_file_attached",
        invoice_id=inv.id,
        detail={"path": stored, "filename": file.filename},
    )
    return ApiEnvelope(data=await _response_for_invoice(db, inv, has_stored_file=True))


_REPROCESSABLE = frozenset(
    {
        InvoiceStatus.EXCEPTION,
        InvoiceStatus.DUPLICATE_SKIPPED,
        InvoiceStatus.PROCESSED,
        InvoiceStatus.REJECTED,
    }
)


@router.post("/{invoice_id:int}/reprocess", response_model=ApiEnvelope[InvoiceResponse])
async def reprocess_invoice(
    invoice_id: int,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[InvoiceResponse]:
    """
    Queue an invoice for parsing again (e.g. after parser upgrades or blob relocate).

    Resets status to pending and clears extracted fields, then runs the pipeline.
    """
    inv = await _get_invoice_for_tenant(db, invoice_id, ctx.tenant_id)
    if inv.status not in _REPROCESSABLE:
        raise HTTPException(
            400,
            f"Cannot reprocess invoice in status '{inv.status.value}'",
        )
    try:
        await repair_invoice_stored_path(db, inv)
        await restore_rejected_invoice_file_if_needed(db, inv)
        await ensure_invoice_stored_file(db, inv)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    previous_status = inv.status.value
    await reset_invoice_for_reprocess(db, inv)
    await log_event(
        db,
        "invoice_requeued",
        invoice_id=inv.id,
        detail={"previous_status": previous_status},
    )
    # Commit before background task so process_invoice sees pending (not processed/rejected).
    await db.commit()
    background_tasks.add_task(process_invoice_background, inv.id, tenant_id=ctx.tenant_id)
    return ApiEnvelope(
        data=await _response_for_invoice(db, inv, verify_stored_file=True),
    )


@router.get("/{invoice_id:int}/pipeline", response_model=ApiEnvelope[PipelineStepsResponse])
async def invoice_pipeline(
    invoice_id: int,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[PipelineStepsResponse]:
    """Six-step pipeline audit trail for one invoice."""
    inv = await _get_invoice_for_tenant(db, invoice_id, ctx.tenant_id)
    logs = (
        await db.execute(
            select(AuditLog)
            .where(
                AuditLog.invoice_id == invoice_id,
                AuditLog.tenant_id == ctx.tenant_id,
            )
            .order_by(AuditLog.created_at.desc())
        )
    ).scalars().all()
    steps = build_pipeline_stages(inv, list(logs))
    return ApiEnvelope(data=PipelineStepsResponse(steps=pipeline_steps_for_api(steps)))


@router.post("/{invoice_id:int}/classification/resolve", response_model=ApiEnvelope[InvoiceResponse])
async def resolve_classification(
    invoice_id: int,
    body: ClassificationResolveRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[InvoiceResponse]:
    """Confirm document type after review; record learning event and optionally reprocess."""
    inv = await _get_invoice_for_tenant(db, invoice_id, ctx.tenant_id)
    confirmed = body.confirmed_dt.strip().upper()
    if not confirmed:
        raise HTTPException(400, "confirmed_dt is required")

    audit_row = (
        await db.execute(
            select(AuditLog)
            .where(
                AuditLog.invoice_id == invoice_id,
                AuditLog.tenant_id == ctx.tenant_id,
                AuditLog.event == "document_classified",
            )
            .order_by(AuditLog.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    detail = audit_row.detail if audit_row and isinstance(audit_row.detail, dict) else {}

    routing_row = (
        await db.execute(
            select(AuditLog)
            .where(
                AuditLog.invoice_id == invoice_id,
                AuditLog.tenant_id == ctx.tenant_id,
                AuditLog.event == "routing_review_required",
            )
            .order_by(AuditLog.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    routing_detail = (
        routing_row.detail if routing_row and isinstance(routing_row.detail, dict) else {}
    )
    if routing_detail.get("gate") == "classification" or not detail.get("policy_winner_dt"):
        for key in ("policy_winner_dt", "review_reasons", "llm_suggested_dt", "llm_confidence"):
            if not detail.get(key) and routing_detail.get(key) is not None:
                detail[key] = routing_detail[key]

    await record_learning_from_resolution(
        db,
        tenant_id=ctx.tenant_id,
        invoice=inv,
        human_confirmed_dt=confirmed,
        classification_detail=detail,
        reviewer_user_id=None,
    )
    apply_document_type_to_invoice(
        inv,
        code=confirmed,
        confidence=float(inv.document_type_confidence or 0.85),
        llm_suggested_dt=str(detail.get("llm_suggested_dt") or inv.llm_suggested_dt or ""),
        llm_confidence=float(detail.get("llm_confidence") or inv.llm_confidence or 0.0),
    )
    config = await load_config_for_tenant(db, ctx.tenant_id)
    await apply_invoice_evaluation(db, inv, config=config, enqueue_pending=False)
    await log_event(
        db,
        "classification_resolved",
        invoice_id=invoice_id,
        tenant_id=ctx.tenant_id,
        detail={
            "confirmed_dt": confirmed,
            "llm_suggested_dt": detail.get("llm_suggested_dt"),
            "policy_winner_dt": detail.get("policy_winner_dt"),
        },
    )

    if body.reprocess:
        await reset_invoice_for_reprocess(db, inv, preserve_document_type=True)
        await db.commit()
        background_tasks.add_task(
            process_invoice_background,
            invoice_id,
            tenant_id=ctx.tenant_id,
        )
    else:
        await db.commit()

    refreshed = await _get_invoice_for_tenant(db, invoice_id, ctx.tenant_id)
    extraction_fields = await _document_type_extraction_fields(db, ctx.tenant_id, refreshed)
    return ApiEnvelope(data=_to_response(refreshed, document_type_extraction_fields=extraction_fields))


@router.get("/{invoice_id:int}/classification-audit", response_model=ApiEnvelope[dict[str, object]])
async def invoice_classification_audit(
    invoice_id: int,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[dict[str, object]]:
    """Latest LLM + policy classification detail from the processing audit trail."""
    inv = await _get_invoice_for_tenant(db, invoice_id, ctx.tenant_id)
    row = (
        await db.execute(
            select(AuditLog)
            .where(
                AuditLog.invoice_id == invoice_id,
                AuditLog.tenant_id == ctx.tenant_id,
                AuditLog.event == "document_classified",
            )
            .order_by(AuditLog.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if row is None or not isinstance(row.detail, dict):
        return ApiEnvelope(
            data={
                "llm_suggested_dt": inv.llm_suggested_dt,
                "llm_confidence": inv.llm_confidence,
                "document_type_code": inv.document_type_code,
            }
        )
    merged = dict(row.detail)
    merged.setdefault("llm_suggested_dt", inv.llm_suggested_dt)
    merged.setdefault("llm_confidence", inv.llm_confidence)
    merged.setdefault("document_type_code", inv.document_type_code)
    return ApiEnvelope(data=merged)


@router.get("/{invoice_id:int}/purchase-dossier", response_model=ApiEnvelope[PurchaseDossierResponse])
async def invoice_purchase_dossier(
    invoice_id: int,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[PurchaseDossierResponse]:
    """PO / GRN / commercial invoice members for the drawer PO Match tab."""
    inv = await _get_invoice_for_tenant(db, invoice_id, ctx.tenant_id)
    return ApiEnvelope(data=await build_purchase_dossier(db, inv))


@router.post("/remap", response_model=ApiEnvelope[dict[str, object]])
async def remap_invoices(
    request: Request,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(require_admin),
) -> ApiEnvelope[dict[str, object]]:
    """Re-apply rule book GL mapping to all eligible invoices for this org."""
    result = await remap_invoices_for_tenant(db, tenant_id=ctx.tenant_id)
    if result.updated:
        actor_name, actor_email = await actor_from_context(db, ctx)
        client_ip = request.client.host if request.client else None
        await log_event(
            db,
            "invoices_remapped",
            tenant_id=ctx.tenant_id,
            detail={
                "updated": result.updated,
                "total": result.total,
                "invoice_ids": result.invoice_ids[:200],
                "invoice_ids_truncated": len(result.invoice_ids) > 200,
            },
            actor_name=actor_name,
            actor_email=actor_email,
            client_ip=client_ip,
        )
    return ApiEnvelope(
        data={
            "updated": result.updated,
            "invoice_ids": result.invoice_ids,
        }
    )


@router.post("/{invoice_id:int}/publish", response_model=ApiEnvelope[InvoiceResponse])
async def publish_invoice(
    invoice_id: int,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[InvoiceResponse]:
    """Export processed invoice journals to the workbook and record ledger posting."""
    from app.services.privilege_service import require_privilege
    from app.services.publish_service import (
        InsufficientCreditsError,
        publish_invoice_to_ledger,
    )

    require_privilege(ctx, "Post")
    inv = await _get_invoice_for_tenant(db, invoice_id, ctx.tenant_id)
    if inv.status != InvoiceStatus.PROCESSED:
        raise HTTPException(
            400,
            f"Only processed invoices can be posted (current: {inv.status.value})",
        )
    actor_name, actor_email = await actor_from_context(db, ctx)
    try:
        await publish_invoice_to_ledger(
            db,
            inv,
            actor_name=actor_name,
            actor_email=actor_email,
        )
    except InsufficientCreditsError as exc:
        raise HTTPException(
            402,
            f"Insufficient credits to post (need {exc.required}, balance {exc.balance})",
        ) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    return ApiEnvelope(data=await _response_for_invoice(db, inv))
