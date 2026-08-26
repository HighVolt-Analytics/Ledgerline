from datetime import date
from pathlib import Path
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import Response
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import AuthContext, actor_from_context, get_auth_context, get_db, require_admin
from app.services.auth.privilege_service import require_bank_reveal
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
    TeamExpenseKindRequest,
    ValidationResultItem,
)
from app.schemas.classification_api import ClassificationResolveRequest, ClassificationReviewItem
from app.services.classification.classification_learning_service import record_learning_from_resolution
from app.services.classification.classification_audit_service import (
    load_citation_audit_detail,
    load_classification_audit_detail,
)
from app.services.extraction.llm_document_service import apply_document_type_to_invoice
from app.services.invoice.invoice_reset import (
    requeue_invoice_for_pipeline,
    reset_invoice_for_reprocess,
    should_preserve_extracted_on_requeue,
)
from app.services.invoice.invoice_edit_service import (
    refresh_invoice_evaluation_after_edit,
    update_invoice_fields,
)
from app.services.invoice.invoice_evaluation_service import (
    apply_invoice_evaluation,
    load_config_for_tenant,
)
from app.services.invoice.line_item_gl_service import build_line_item_responses
from app.schemas.journal import JournalEntryResponse
from app.schemas.line_item import LineItemResponse
from app.schemas.purchase import PurchaseDossierResponse
from app.schemas.sales import SalesDossierResponse
from app.services.sales.sales_dossier_service import build_sales_dossier
from app.services.audit.audit_service import audit_logs_for_invoices, log_event
from app.services.shared.file_storage import (
    ensure_invoice_stored_file,
    has_stored_path,
    read_invoice_file,
    repair_invoice_stored_path,
    store_invoice_pdf,
    stored_file_available,
)
from app.services.approval.approval_service import restore_rejected_invoice_file_if_needed
from app.schemas.pipeline import PipelineStepsResponse
from app.services.invoice.pipeline_stages import (
    build_pipeline_stages,
    derive_current_stage,
    pipeline_steps_for_api,
    resolve_pipeline_active_path,
)
from app.services.invoice.remap_service import remap_invoices_for_tenant
from app.services.master_data.vendor_resolver import UNKNOWN_SLUG
from app.utils.hashing import compute_sha256_bytes
from app.services.classification.document_type_playbook_service import (
    effective_document_type_code,
    extraction_fields_for_invoice_code,
)
from app.services.extraction.field_extraction_confidence import compute_extraction_field_confidence
from app.services.ingest.ingest_fanout_service import DuplicateUploadError, ingest_upload_file
from app.services.ingest.canonical_intake_service import IntakeValidationError
from app.services.credit_service import InsufficientCreditsError, PlanFeatureBlockedError
from app.services.purchase.purchase_dossier_service import build_purchase_dossier
from app.tenant_child_tables import journal_entries_for_invoice, line_items_for_invoice
from app.tenant_scoped import get_for_tenant
from app.workers.tasks import enqueue_invoice_pipelines
from app.services.invoice.invoice_access_service import (
    MAX_UPLOAD_BYTES as _MAX_UPLOAD_BYTES,
    get_invoice_for_tenant,
    read_upload_file,
)
from app.services.invoice.invoice_response_service import (
    classification_review_confidence as _classification_review_confidence,
    document_type_extraction_fields as _document_type_extraction_fields,
    invoice_list_load_options,
    invoice_to_response as _to_response,
    response_for_invoice as _response_for_invoice,
    responses_for_invoices as _responses_for_invoices,
)

router = APIRouter(prefix="/invoices", tags=["invoices"])


async def _load_invoice_with_details(
    db: AsyncSession,
    *,
    invoice_id: int,
    tenant_id: uuid.UUID,
) -> Invoice:
    """Load invoice with line items and journal entries for detail responses."""
    stmt = (
        select(Invoice)
        .where(Invoice.id == invoice_id, Invoice.tenant_id == tenant_id)
        .options(
            selectinload(Invoice.line_items),
            selectinload(Invoice.journal_entries),
        )
    )
    inv = (await db.execute(stmt)).scalar_one_or_none()
    if not inv:
        raise HTTPException(404, "Invoice not found")
    return inv


async def _line_items_response(
    db: AsyncSession,
    inv: Invoice,
    *,
    tenant_id,
) -> list[LineItemResponse]:
    from sqlalchemy import inspect as sa_inspect

    if sa_inspect(inv).session is None:
        inv = (
            await db.execute(
                select(Invoice)
                .where(Invoice.id == inv.id, Invoice.tenant_id == tenant_id)
                .options(selectinload(Invoice.line_items))
            )
        ).scalar_one()
    config = await load_config_for_tenant(db, tenant_id)
    return build_line_item_responses(inv, config)


async def _get_invoice_for_tenant(
    db: AsyncSession, invoice_id: int, tenant_id
) -> Invoice:
    try:
        return await get_invoice_for_tenant(db, invoice_id, tenant_id)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc


async def _read_upload_file(file: UploadFile, *, max_bytes: int = _MAX_UPLOAD_BYTES) -> bytes:
    try:
        return await read_upload_file(file, max_bytes=max_bytes)
    except ValueError as exc:
        message = str(exc)
        status = 413 if "exceeds maximum size" in message.lower() else 400
        raise HTTPException(status, message) from exc


@router.get("", response_model=ApiEnvelope[list[InvoiceResponse]])
async def list_invoices(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: InvoiceStatusSchema | None = None,
    vendor: str | None = Query(None, description="Filter by vendor name (partial match)"),
    connected_mailbox_id: int | None = Query(
        None, description="Filter by connected mailbox (inbox source)"
    ),
    capture_source: str | None = Query(
        None,
        description="Filter by capture channel: upload, email, whatsapp, or viber",
    ),
    invoice_date_from: date | None = None,
    invoice_date_to: date | None = None,
    route_target: str | None = Query(None, description="Filter by rule book route target"),
    evaluation_status: EvaluationStatus | None = None,
    q: str | None = Query(
        None,
        description="Search vendor, invoice no, PO, document ref, route, GL account, or id",
    ),
    include_total: bool = Query(
        True,
        description="When false, skip COUNT(*) and set meta.pages=1 (first-page feeds).",
    ),
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[list[InvoiceResponse]]:
    stmt = (
        select(Invoice)
        .options(*invoice_list_load_options())
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
        if capture_source and capture_source.strip():
            src = capture_source.strip().lower()
            if src in {"upload", "email", "whatsapp", "viber"}:
                unset_capture = or_(
                    Invoice.capture_source.is_(None),
                    Invoice.capture_source == "",
                )
                if src == "upload":
                    # Explicit uploads plus legacy rows with no channel markers.
                    # Claimant/sender (email_sender) is identity, not channel.
                    query = query.where(
                        or_(
                            func.lower(Invoice.capture_source) == "upload",
                            and_(
                                unset_capture,
                                Invoice.connected_mailbox_id.is_(None),
                                Invoice.whatsapp_connection_id.is_(None),
                                Invoice.viber_connection_id.is_(None),
                            ),
                        )
                    )
                elif src == "email":
                    query = query.where(
                        or_(
                            func.lower(Invoice.capture_source) == "email",
                            and_(
                                unset_capture,
                                Invoice.connected_mailbox_id.isnot(None),
                            ),
                        )
                    )
                elif src == "whatsapp":
                    query = query.where(
                        or_(
                            func.lower(Invoice.capture_source) == "whatsapp",
                            and_(
                                unset_capture,
                                Invoice.whatsapp_connection_id.isnot(None),
                            ),
                        )
                    )
                else:  # viber
                    query = query.where(
                        or_(
                            func.lower(Invoice.capture_source) == "viber",
                            and_(
                                unset_capture,
                                Invoice.viber_connection_id.isnot(None),
                            ),
                        )
                    )
                # Upload / channel inbox pages hide Approvals-queue rows so page
                # totals match the Detailed list (client also filters these out).
                query = query.where(
                    Invoice.status.notin_(
                        (InvoiceStatus.REJECTED, InvoiceStatus.DUPLICATE_SKIPPED)
                    )
                )
        if route_target and route_target.strip():
            query = query.where(Invoice.route_target == route_target.strip())
            # Rejected / duplicate docs belong on Approvals, not management pages.
            query = query.where(
                Invoice.status.notin_(
                    (InvoiceStatus.REJECTED, InvoiceStatus.DUPLICATE_SKIPPED)
                )
            )
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

    rows = (
        await db.execute(stmt.offset((page - 1) * page_size).limit(page_size))
    ).scalars().all()
    if include_total:
        if page == 1 and len(rows) < page_size:
            total = len(rows)
        else:
            total = (await db.execute(count_stmt)).scalar() or 0
        pages = max(1, (total + page_size - 1) // page_size)
    else:
        total = len(rows)
        pages = 1

    return ApiEnvelope(
        data=await _responses_for_invoices(
            db, list(rows), tenant_id=ctx.tenant_id, for_list=True
        ),
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
        audit_detail = await load_classification_audit_detail(
            db,
            invoice=inv,
            tenant_id=ctx.tenant_id,
        )
        items.append(
            ClassificationReviewItem(
                invoice_id=inv.id,
                document_ref=inv.document_ref,
                status=inv.status.value if hasattr(inv.status, "value") else str(inv.status),
                evaluation_status=inv.evaluation_status,
                llm_suggested_dt=inv.llm_suggested_dt or audit_detail.get("llm_suggested_dt"),
                llm_confidence=_classification_review_confidence(inv, audit_detail),
                policy_winner_dt=str(audit_detail.get("policy_winner_dt") or ""),
                document_type_code=inv.document_type_code,
                review_reasons=[
                    str(reason) for reason in (audit_detail.get("review_reasons") or [])
                ],
                document_ai_provider=str(audit_detail.get("document_ai_provider") or "") or None,
            )
        )
    return ApiEnvelope(data=items)


@router.get("/{invoice_id:int}", response_model=ApiEnvelope[InvoiceWithDetails])
async def get_invoice(
    invoice_id: int,
    reveal_bank: bool = Query(False),
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[InvoiceWithDetails]:
    if reveal_bank:
        require_bank_reveal(ctx)
        actor_name, actor_email = await actor_from_context(db, ctx)
        await log_event(
            db,
            "bank_details_revealed",
            tenant_id=ctx.tenant_id,
            invoice_id=invoice_id,
            detail={"scope": "invoice"},
            actor_name=actor_name,
            actor_email=actor_email,
        )
    inv = await _load_invoice_with_details(
        db,
        invoice_id=invoice_id,
        tenant_id=ctx.tenant_id,
    )

    base = await _response_for_invoice(
        db,
        inv,
        tenant_id=ctx.tenant_id,
        verify_stored_file=True,
        repair_stored_path=True,
        document_type_extraction_fields=await _document_type_extraction_fields(db, ctx.tenant_id, inv),
        include_extraction_field_confidence=True,
        reveal_bank=reveal_bank,
    )
    inv = await _load_invoice_with_details(
        db,
        invoice_id=invoice_id,
        tenant_id=ctx.tenant_id,
    )
    return ApiEnvelope(
        data=InvoiceWithDetails(
            **base.model_dump(),
            line_items=await _line_items_response(db, inv, tenant_id=ctx.tenant_id),
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
        changed = await update_invoice_fields(
            db,
            inv,
            body,
            actor_name=actor_name,
            actor_email=actor_email,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    if changed:
        await refresh_invoice_evaluation_after_edit(db, inv, enqueue_pending=True)

    await db.flush()
    inv = (
        await db.execute(stmt.execution_options(populate_existing=True))
    ).scalar_one()
    base = await _response_for_invoice(
        db,
        inv,
        tenant_id=ctx.tenant_id,
        document_type_extraction_fields=await _document_type_extraction_fields(db, ctx.tenant_id, inv),
        include_extraction_field_confidence=True,
    )
    inv = await _load_invoice_with_details(
        db,
        invoice_id=invoice_id,
        tenant_id=ctx.tenant_id,
    )
    return ApiEnvelope(
        data=InvoiceWithDetails(
            **base.model_dump(),
            line_items=await _line_items_response(db, inv, tenant_id=ctx.tenant_id),
            journal_entries=[
                JournalEntryResponse.model_validate(je) for je in inv.journal_entries
            ],
        )
    )


@router.post(
    "/{invoice_id:int}/team-expense-kind",
    response_model=ApiEnvelope[InvoiceResponse],
)
async def set_team_expense_kind(
    invoice_id: int,
    body: TeamExpenseKindRequest,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[InvoiceResponse]:
    """Choose the claim kind (advance requisition or expense claim) before the journal posts."""
    from app.services.integration.publish_service import is_published_to_ledger
    from app.services.rule_book.rule_book_mapper import ROUTE_TEAM

    inv = await _get_invoice_for_tenant(db, invoice_id, ctx.tenant_id)
    if (inv.route_target or "").strip() != ROUTE_TEAM:
        raise HTTPException(400, "Claim kind applies to Team Expenses documents only")
    if await is_published_to_ledger(db, inv.id):
        raise HTTPException(409, "Claim kind cannot change after the journal is published")

    before = inv.team_expense_kind
    inv.team_expense_kind = body.team_expense_kind
    inv.linked_advance_invoice_id = body.linked_advance_invoice_id
    await db.flush()
    actor_name, actor_email = await actor_from_context(db, ctx)
    await log_event(
        db,
        "team_expense_kind_changed",
        tenant_id=ctx.tenant_id,
        invoice_id=inv.id,
        detail={"from": before, "to": inv.team_expense_kind},
        actor_name=actor_name,
        actor_email=actor_email,
    )
    return ApiEnvelope(
        data=await _response_for_invoice(db, inv, tenant_id=ctx.tenant_id)
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
    inv = await _get_invoice_for_tenant(db, invoice_id, ctx.tenant_id)
    inv = (
        await db.execute(
            select(Invoice)
            .where(Invoice.id == inv.id, Invoice.tenant_id == ctx.tenant_id)
            .options(selectinload(Invoice.line_items))
        )
    ).scalar_one()
    return ApiEnvelope(data=await _line_items_response(db, inv, tenant_id=ctx.tenant_id))


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


_PROCESS_BATCH_STATUSES = {
    InvoiceStatus.PENDING,
    InvoiceStatus.PARSING,
    InvoiceStatus.VALIDATING,
    InvoiceStatus.MAPPING,
    InvoiceStatus.JOURNALING,
    InvoiceStatus.RECONCILING,
}


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
            select(Invoice.id, Invoice.status).where(
                Invoice.id.in_(unique_ids),
                Invoice.tenant_id == ctx.tenant_id,
            )
        )
    ).all()
    found = {row[0]: row[1] for row in rows}
    if len(found) != len(unique_ids):
        raise HTTPException(404, "One or more invoices not found")
    ordered = [
        invoice_id
        for invoice_id in unique_ids
        if invoice_id in found and found[invoice_id] in _PROCESS_BATCH_STATUSES
    ]
    if ordered:
        enqueue_invoice_pipelines(
            ordered,
            tenant_id=ctx.tenant_id,
            background_tasks=background_tasks,
        )
    return ApiEnvelope(
        data={
            "queued": len(ordered),
            "status": "running" if ordered else "idle",
            "skipped": len(unique_ids) - len(ordered),
        }
    )


async def _queue_upload_processing(
    background_tasks: BackgroundTasks,
    invoice_ids: list[int],
    *,
    defer_processing: bool,
    tenant_id: uuid.UUID,
) -> None:
    if defer_processing or not invoice_ids:
        return
    enqueue_invoice_pipelines(
        invoice_ids,
        tenant_id=tenant_id,
        background_tasks=background_tasks,
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
    allowed = (".pdf", ".jpg", ".jpeg", ".png", ".docx", ".webp")
    if not file.filename or not file.filename.lower().endswith(allowed):
        raise HTTPException(400, "Accepted: PDF, JPG, PNG, DOCX, WEBP")

    data = await _read_upload_file(file)
    if not data:
        raise HTTPException(400, "Empty file")

    org = await db.get(Tenant, ctx.tenant_id)
    tenant_slug = org.slug if org else "default"
    tenant_name = org.name if org else None

    try:
        actor_name, actor_email = await actor_from_context(db, ctx)
        result = await ingest_upload_file(
            db,
            tenant_id=ctx.tenant_id,
            tenant_slug=tenant_slug,
            tenant_name=tenant_name,
            filename=Path(file.filename).name,
            data=data,
            purchase_document_type=purchase_document_type,
            actor_name=actor_name,
            actor_email=actor_email,
        )
    except IntakeValidationError as exc:
        raise HTTPException(400, str(exc)) from exc
    except DuplicateUploadError:
        raise HTTPException(409, "Duplicate file already uploaded") from None
    except InsufficientCreditsError as exc:
        raise HTTPException(
            402,
            f"Insufficient credits: need {exc.required}, balance {exc.balance}. Top up to continue.",
        ) from exc
    except PlanFeatureBlockedError as exc:
        raise HTTPException(403, str(exc)) from exc

    if not result.invoice_ids:
        if result.duplicate_handled:
            raise HTTPException(409, "Duplicate file already uploaded")
        raise HTTPException(400, "Could not ingest file")

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
        data=await _response_for_invoice(
            db, primary, tenant_id=ctx.tenant_id, has_stored_file=True
        ),
        meta=meta,
    )


_ALLOWED_ATTACH = (".pdf", ".jpg", ".jpeg", ".png", ".docx", ".webp")


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
        raise HTTPException(400, "Accepted: PDF, JPG, PNG, DOCX, WEBP")

    data = await _read_upload_file(file)
    if not data:
        raise HTTPException(400, "Empty file")

    file_hash = compute_sha256_bytes(data)
    from app.services.dossier.document_duplicate_service import find_invoice_by_file_hash

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
    from app.services.invoice.invoice_evaluation_service import load_config_for_tenant
    from app.services.vault.vault_invoice_paths import (
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
        tenant_id=ctx.tenant_id,
        invoice_id=inv.id,
        detail={"path": stored, "filename": file.filename},
    )
    return ApiEnvelope(
        data=await _response_for_invoice(db, inv, tenant_id=ctx.tenant_id, has_stored_file=True)
    )


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
    except TimeoutError as exc:
        raise HTTPException(
            503,
            "Database timed out; the invoice may be processing elsewhere. Retry in a moment.",
        ) from exc
    except Exception as exc:
        from azure.core.exceptions import ResourceNotFoundError

        if isinstance(exc, ResourceNotFoundError):
            raise HTTPException(
                400,
                "Stored PDF not found in blob storage. Re-attach the file before reprocessing.",
            ) from exc
        raise

    previous_status = inv.status.value
    preserve_fields = await should_preserve_extracted_on_requeue(db, inv)
    await requeue_invoice_for_pipeline(db, inv, preserve_extracted_fields=preserve_fields)
    await log_event(
        db,
        "invoice_requeued",
        tenant_id=ctx.tenant_id,
        invoice_id=inv.id,
        detail={
            "previous_status": previous_status,
            "preserved_extracted_fields": preserve_fields,
        },
    )
    # Commit before background task so process_invoice sees pending (not processed/rejected).
    await db.commit()
    enqueue_invoice_pipelines(
        [inv.id],
        tenant_id=ctx.tenant_id,
        background_tasks=background_tasks,
    )
    return ApiEnvelope(
        data=await _response_for_invoice(
            db, inv, tenant_id=ctx.tenant_id, verify_stored_file=True
        ),
    )


@router.post("/{invoice_id:int}/confirm-process", response_model=ApiEnvelope[InvoiceResponse])
async def confirm_and_process_invoice(
    invoice_id: int,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[InvoiceResponse]:
    """Confirm saved fields and continue the pipeline without manager approval.

    Document-type and team-expense approval gates still hold when policy requires
    a separate approver. Use POST /api/approvals/{id}/approve to sign off.
    """
    from app.services.approval.approval_api_service import confirm_and_process_action

    try:
        result = await confirm_and_process_action(db, ctx, invoice_id=invoice_id)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    await db.commit()
    if result.enqueue_pipeline:
        enqueue_invoice_pipelines(
            [invoice_id],
            tenant_id=ctx.tenant_id,
            background_tasks=background_tasks,
        )
    refreshed = await _get_invoice_for_tenant(db, invoice_id, ctx.tenant_id)
    return ApiEnvelope(
        data=await _response_for_invoice(
            db, refreshed, tenant_id=ctx.tenant_id, verify_stored_file=True
        ),
    )


@router.get("/{invoice_id:int}/pipeline", response_model=ApiEnvelope[PipelineStepsResponse])
async def invoice_pipeline(
    invoice_id: int,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[PipelineStepsResponse]:
    """Pipeline audit trail for one invoice (Understood / Not understood paths)."""
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
    log_list = list(logs)
    steps = build_pipeline_stages(inv, log_list)
    return ApiEnvelope(
        data=PipelineStepsResponse(
            steps=pipeline_steps_for_api(steps),
            active_path=resolve_pipeline_active_path(log_list),
        )
    )

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

    audit_detail = await load_classification_audit_detail(
        db,
        invoice=inv,
        tenant_id=ctx.tenant_id,
    )
    detail = dict(audit_detail)

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
            "document_heading": inv.document_heading,
        },
    )

    if body.reprocess:
        previous_status = inv.status.value
        await reset_invoice_for_reprocess(
            db,
            inv,
            preserve_document_type=True,
            clear_overrides=False,
        )
        await log_event(
            db,
            "invoice_requeued",
            tenant_id=ctx.tenant_id,
            invoice_id=invoice_id,
            detail={
                "previous_status": previous_status,
                "reason": "classification_resolved",
                "confirmed_dt": confirmed,
                "preserved_document_type": True,
            },
        )
        # Commit before enqueue so the worker always sees PENDING + locked DT.
        await db.commit()
        queue_status = enqueue_invoice_pipelines(
            [invoice_id],
            tenant_id=ctx.tenant_id,
            background_tasks=background_tasks,
        )
        if queue_status == "idle":
            raise HTTPException(500, "Failed to queue pipeline after classification resolve")
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
    merged = await load_classification_audit_detail(
        db,
        invoice=inv,
        tenant_id=ctx.tenant_id,
    )
    merged.update(
        await load_citation_audit_detail(
            db,
            invoice_id=inv.id,
            tenant_id=ctx.tenant_id,
        )
    )
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


@router.get("/{invoice_id:int}/sales-dossier", response_model=ApiEnvelope[SalesDossierResponse])
async def invoice_sales_dossier(
    invoice_id: int,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[SalesDossierResponse]:
    """SO / DN / commercial invoice members for the drawer match tab."""
    inv = await _get_invoice_for_tenant(db, invoice_id, ctx.tenant_id)
    return ApiEnvelope(data=await build_sales_dossier(db, inv))


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
    from app.services.auth.privilege_service import require_privilege
    from app.services.integration.publish_service import (
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

    return ApiEnvelope(data=await _response_for_invoice(db, inv, tenant_id=ctx.tenant_id))
