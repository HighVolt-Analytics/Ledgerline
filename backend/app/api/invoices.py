import json
from datetime import date
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import AuthContext, actor_from_context, get_auth_context, get_db, require_admin
from app.config import get_settings
from app.models.invoice import Invoice, InvoiceStatus
from app.models.organisation import Organisation
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
    ValidationResultItem,
)
from app.services.invoice_edit_service import update_invoice_fields
from app.services.invoice_evaluation_service import parse_matched_rule_ids
from app.schemas.journal import JournalEntryResponse
from app.schemas.line_item import LineItemResponse
from app.services.audit_service import log_event
from app.services.file_storage import (
    has_stored_path,
    read_invoice_file,
    store_invoice_pdf,
    stored_file_available,
)
from app.services.invoice_reset import reset_invoice_for_reprocess
from app.schemas.pipeline import PipelineStepsResponse
from app.services.pipeline_stages import (
    build_pipeline_stages,
    pipeline_steps_for_api,
)
from app.services.remap_service import remap_invoices_for_org
from app.services.vendor_resolver import UNKNOWN_SLUG
from app.utils.hashing import compute_sha256_bytes
from app.workers.tasks import process_invoice_background

router = APIRouter(prefix="/invoices", tags=["invoices"])

_MAX_UPLOAD_BYTES = 25 * 1024 * 1024


async def _read_upload_file(file: UploadFile, *, max_bytes: int = _MAX_UPLOAD_BYTES) -> bytes:
    data = await file.read()
    if len(data) > max_bytes:
        raise HTTPException(
            413,
            f"File exceeds maximum size ({max_bytes // (1024 * 1024)} MB)",
        )
    return data


async def _get_invoice_for_org(
    db: AsyncSession, invoice_id: int, org_id: int
) -> Invoice:
    inv = await db.get(Invoice, invoice_id)
    if not inv or inv.org_id != org_id:
        raise HTTPException(404, "Invoice not found")
    return inv


def _validation(raw: str | None) -> list[ValidationResultItem] | None:
    if not raw:
        return None
    try:
        return [ValidationResultItem(**item) for item in json.loads(raw)]
    except (json.JSONDecodeError, TypeError):
        return None


def _to_response(inv: Invoice, *, has_stored_file: bool | None = None) -> InvoiceResponse:
    stored_ok = (
        has_stored_file
        if has_stored_file is not None
        else has_stored_path(inv.raw_file_path)
    )
    return InvoiceResponse(
        id=inv.id,
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
        connected_mailbox_id=inv.connected_mailbox_id,
        storage_vendor_slug=inv.storage_vendor_slug,
        account_code=inv.account_code,
        account_name=inv.account_name,
        route_target=inv.route_target,
        matched_rule_ids=parse_matched_rule_ids(inv.matched_rule_ids) or None,
        vendor_confidence=inv.vendor_confidence,
        evaluation_status=(
            EvaluationStatus(inv.evaluation_status)
            if inv.evaluation_status
            else None
        ),
        purchase_document_type=inv.purchase_document_type,
        validation_results=_validation(inv.validation_results),
        created_at=inv.created_at,
        has_stored_file=stored_ok,
    )


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
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[list[InvoiceResponse]]:
    stmt = (
        select(Invoice)
        .where(Invoice.org_id == ctx.org_id)
        .order_by(Invoice.created_at.desc())
    )
    count_stmt = select(func.count(Invoice.id)).where(Invoice.org_id == ctx.org_id)

    def _apply_filters(q):
        if status:
            q = q.where(Invoice.status == InvoiceStatus(status.value))
        if vendor and vendor.strip():
            q = q.where(Invoice.vendor.ilike(f"%{vendor.strip()}%"))
        if invoice_date_from is not None:
            q = q.where(Invoice.invoice_date >= invoice_date_from)
        if invoice_date_to is not None:
            q = q.where(Invoice.invoice_date <= invoice_date_to)
        if connected_mailbox_id is not None:
            q = q.where(Invoice.connected_mailbox_id == connected_mailbox_id)
        if route_target and route_target.strip():
            q = q.where(Invoice.route_target == route_target.strip())
        if evaluation_status is not None:
            q = q.where(Invoice.evaluation_status == evaluation_status.value)
        return q

    stmt = _apply_filters(stmt)
    count_stmt = _apply_filters(count_stmt)

    total = (await db.execute(count_stmt)).scalar() or 0
    pages = max(1, (total + page_size - 1) // page_size)
    rows = (
        await db.execute(stmt.offset((page - 1) * page_size).limit(page_size))
    ).scalars().all()

    return ApiEnvelope(
        data=[_to_response(r) for r in rows],
        meta=ResponseMeta(page=page, total=total, pages=pages),
    )


@router.get("/{invoice_id}", response_model=ApiEnvelope[InvoiceWithDetails])
async def get_invoice(
    invoice_id: int,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[InvoiceWithDetails]:
    stmt = (
        select(Invoice)
        .where(Invoice.id == invoice_id, Invoice.org_id == ctx.org_id)
        .options(
            selectinload(Invoice.line_items),
            selectinload(Invoice.journal_entries),
        )
    )
    inv = (await db.execute(stmt)).scalar_one_or_none()
    if not inv:
        raise HTTPException(404, "Invoice not found")

    base = _to_response(inv)
    return ApiEnvelope(
        data=InvoiceWithDetails(
            **base.model_dump(),
            line_items=[LineItemResponse.model_validate(li) for li in inv.line_items],
            journal_entries=[
                JournalEntryResponse.model_validate(je) for je in inv.journal_entries
            ],
        )
    )


@router.patch("/{invoice_id}", response_model=ApiEnvelope[InvoiceWithDetails])
async def patch_invoice(
    invoice_id: int,
    body: InvoiceUpdateRequest,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[InvoiceWithDetails]:
    """Update missing or incorrect fields on invoices in the approval review queue."""
    stmt = (
        select(Invoice)
        .where(Invoice.id == invoice_id, Invoice.org_id == ctx.org_id)
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
    base = _to_response(inv)
    return ApiEnvelope(
        data=InvoiceWithDetails(
            **base.model_dump(),
            line_items=[LineItemResponse.model_validate(li) for li in inv.line_items],
            journal_entries=[
                JournalEntryResponse.model_validate(je) for je in inv.journal_entries
            ],
        )
    )


@router.get("/{invoice_id}/file")
async def download_invoice_file(
    invoice_id: int,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> Response:
    """Download the stored invoice attachment (PDF, image, or DOCX)."""
    inv = await _get_invoice_for_org(db, invoice_id, ctx.org_id)
    if not stored_file_available(inv.raw_file_path):
        raise HTTPException(
            404,
            "Invoice has no stored file. Upload a PDF via POST /api/invoices/{id}/attach.",
        )

    try:
        data, media_type, filename = read_invoice_file(inv.raw_file_path)  # type: ignore[arg-type]
    except FileNotFoundError as exc:
        raise HTTPException(404, "Stored file not found on disk or blob") from exc

    return Response(
        content=data,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{invoice_id}/line-items", response_model=ApiEnvelope[list[LineItemResponse]])
async def get_line_items(
    invoice_id: int,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[list[LineItemResponse]]:
    await _get_invoice_for_org(db, invoice_id, ctx.org_id)
    rows = (
        await db.execute(select(LineItem).where(LineItem.invoice_id == invoice_id))
    ).scalars().all()
    return ApiEnvelope(data=[LineItemResponse.model_validate(r) for r in rows])


@router.get(
    "/{invoice_id}/journal-entries",
    response_model=ApiEnvelope[list[JournalEntryResponse]],
)
async def get_journal_entries(
    invoice_id: int,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[list[JournalEntryResponse]]:
    await _get_invoice_for_org(db, invoice_id, ctx.org_id)
    rows = (
        await db.execute(
            select(JournalEntry).where(JournalEntry.invoice_id == invoice_id)
        )
    ).scalars().all()
    return ApiEnvelope(data=[JournalEntryResponse.model_validate(r) for r in rows])


@router.post("/upload", response_model=ApiEnvelope[InvoiceResponse])
async def upload_invoice(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    purchase_document_type: str | None = Query(
        None,
        description="Purchase document type when uploading PO/GRN/invoice: po, grn, invoice",
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
    file_hash = compute_sha256_bytes(data)
    dup = (
        await db.execute(
            select(Invoice).where(
                Invoice.org_id == ctx.org_id,
                Invoice.file_hash == file_hash,
            )
        )
    ).scalar_one_or_none()
    if dup:
        raise HTTPException(409, "Duplicate file already uploaded")

    org = await db.get(Organisation, ctx.org_id)
    org_slug = org.slug if org else "default"
    org_name = org.name if org else None

    from app.services.purchase_document_service import normalize_purchase_document_type

    doc_type = normalize_purchase_document_type(purchase_document_type)

    inv = Invoice(
        org_id=ctx.org_id,
        status=InvoiceStatus.PENDING,
        file_hash=file_hash,
        currency="AUD",
        storage_vendor_slug=UNKNOWN_SLUG,
        purchase_document_type=doc_type,
    )
    db.add(inv)
    await db.flush()

    stored = store_invoice_pdf(
        data,
        org_slug,
        UNKNOWN_SLUG,
        inv.id,
        file_hash,
        Path(file.filename).name,
        org_name=org_name,
        purchase_document_type=doc_type,
    )
    inv.raw_file_path = stored

    await log_event(
        db,
        "invoice_uploaded",
        invoice_id=inv.id,
        detail={"path": stored, "vendor_slug": UNKNOWN_SLUG},
    )
    await db.flush()

    if get_settings().sync_processing:
        background_tasks.add_task(process_invoice_background, inv.id)

    return ApiEnvelope(data=_to_response(inv, has_stored_file=True))


_ALLOWED_ATTACH = (".pdf", ".jpg", ".jpeg", ".png", ".docx")


@router.post("/{invoice_id}/attach", response_model=ApiEnvelope[InvoiceResponse])
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
    inv = await _get_invoice_for_org(db, invoice_id, ctx.org_id)
    if not file.filename or not file.filename.lower().endswith(_ALLOWED_ATTACH):
        raise HTTPException(400, "Accepted: PDF, JPG, PNG, DOCX")

    data = await _read_upload_file(file)
    if not data:
        raise HTTPException(400, "Empty file")

    file_hash = compute_sha256_bytes(data)
    other = (
        await db.execute(
            select(Invoice).where(
                Invoice.org_id == ctx.org_id,
                Invoice.file_hash == file_hash,
                Invoice.id != invoice_id,
            )
        )
    ).scalar_one_or_none()
    if other:
        raise HTTPException(
            409,
            f"Duplicate of invoice {other.id}; that file is already in the system",
        )

    org = await db.get(Organisation, ctx.org_id)
    org_slug = org.slug if org else "default"
    org_name = org.name if org else None
    vendor_slug = inv.storage_vendor_slug or UNKNOWN_SLUG
    stored = store_invoice_pdf(
        data,
        org_slug,
        vendor_slug,
        inv.id,
        file_hash,
        Path(file.filename).name,
        org_name=org_name,
        vendor_name=inv.vendor,
        invoice_no=inv.invoice_no,
        invoice_date=inv.invoice_date,
        route_target=inv.route_target,
        po_reference=inv.po_reference,
        purchase_document_type=inv.purchase_document_type,
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
    return ApiEnvelope(data=_to_response(inv, has_stored_file=True))


_REPROCESSABLE = frozenset(
    {
        InvoiceStatus.EXCEPTION,
        InvoiceStatus.DUPLICATE_SKIPPED,
        InvoiceStatus.PROCESSED,
    }
)


@router.post("/{invoice_id}/reprocess", response_model=ApiEnvelope[InvoiceResponse])
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
    inv = await _get_invoice_for_org(db, invoice_id, ctx.org_id)
    if not stored_file_available(inv.raw_file_path):
        raise HTTPException(
            400,
            "Invoice has no stored file. Upload via POST /api/invoices/{id}/attach first.",
        )
    if inv.status not in _REPROCESSABLE:
        raise HTTPException(
            400,
            f"Cannot reprocess invoice in status '{inv.status.value}'",
        )

    previous_status = inv.status.value
    await reset_invoice_for_reprocess(db, inv)
    await log_event(
        db,
        "invoice_requeued",
        invoice_id=inv.id,
        detail={"previous_status": previous_status},
    )
    background_tasks.add_task(process_invoice_background, inv.id)
    return ApiEnvelope(data=_to_response(inv))


@router.get("/{invoice_id}/pipeline", response_model=ApiEnvelope[PipelineStepsResponse])
async def invoice_pipeline(
    invoice_id: int,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[PipelineStepsResponse]:
    """Six-step pipeline audit trail for one invoice."""
    inv = await _get_invoice_for_org(db, invoice_id, ctx.org_id)
    logs = (
        await db.execute(
            select(AuditLog)
            .where(AuditLog.invoice_id == invoice_id)
            .order_by(AuditLog.created_at.desc())
        )
    ).scalars().all()
    steps = build_pipeline_stages(inv, list(logs))
    return ApiEnvelope(data=PipelineStepsResponse(steps=pipeline_steps_for_api(steps)))


@router.post("/remap", response_model=ApiEnvelope[dict[str, object]])
async def remap_invoices(
    request: Request,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(require_admin),
) -> ApiEnvelope[dict[str, object]]:
    """Re-apply rule book GL mapping to all eligible invoices for this org."""
    result = await remap_invoices_for_org(db, org_id=ctx.org_id)
    if result.updated:
        actor_name, actor_email = await actor_from_context(db, ctx)
        client_ip = request.client.host if request.client else None
        await log_event(
            db,
            "invoices_remapped",
            org_id=ctx.org_id,
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


@router.post("/{invoice_id}/publish", response_model=ApiEnvelope[InvoiceResponse])
async def publish_invoice(
    invoice_id: int,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[InvoiceResponse]:
    """Record ledger publish for a processed invoice (integration hook)."""
    from app.services.privilege_service import require_privilege

    require_privilege(ctx, "Publish")
    inv = await _get_invoice_for_org(db, invoice_id, ctx.org_id)
    if inv.status != InvoiceStatus.PROCESSED:
        raise HTTPException(
            400,
            f"Only processed invoices can be published (current: {inv.status.value})",
        )
    actor_name, actor_email = await actor_from_context(db, ctx)
    await log_event(
        db,
        "invoice_published_to_ledger",
        invoice_id=inv.id,
        detail={"vendor": inv.vendor, "invoice_no": inv.invoice_no},
        actor_name=actor_name,
        actor_email=actor_email,
    )
    return ApiEnvelope(data=_to_response(inv))
