"""Approval queue and kanban API orchestration."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from types import SimpleNamespace

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer, selectinload

from app.api.deps import AuthContext, actor_from_context
from app.models.invoice import Invoice, InvoiceStatus
from app.models.tenant import Tenant
from app.schemas.approvals import ApprovalListRequest
from app.schemas.common import ResponseMeta
from app.schemas.invoice import InvoiceResponse
from app.services.approval.approval_board_service import (
    approval_board_column,
    is_understood_path_vault_terminal,
)
from app.services.approval.approval_pipeline_service import (
    apply_human_approval_processing_defaults,
    payable_fields_complete,
)
from app.services.approval.approval_service import (
    APPROVABLE_STATUSES,
    _assert_invoice_ready_for_approval,
    confirm_invoice_for_process,
    escalate_invoice,
    permanently_delete_invoice,
    reject_invoice,
    request_approval,
    resolution_for_review_action,
    restore_rejected_invoice_file_if_needed,
)
from app.services.audit.audit_service import log_event
from app.services.shared.file_storage import ensure_stored_file_for_approval
from app.services.invoice.invoice_access_service import get_invoice_for_tenant
from app.services.invoice.invoice_evaluation_service import (
    EVAL_VISION_HEADER_REVIEW,
    ROUTE_TEAM,
    load_config_for_tenant,
)
from app.services.invoice.invoice_reset import reset_invoice_for_approval
from app.services.invoice.invoice_response_service import (
    invoice_list_load_options,
    response_for_invoice,
    responses_for_approval_board,
    responses_for_invoices,
)
from app.services.invoice.vision_posting_continue import (
    continue_vision_understood_posting,
    resolve_vision_posting_definition,
    vision_dt_never_posts,
    vision_header_ok_from_invoice,
    vision_posting_skip_user_message,
    vision_should_continue_posting,
)
from app.services.purchase.team_expense_approval import assert_team_expense_approvable
from app.services.tenant.tenant_org_context import org_context_from_config
from app.services.approval.approval_quorum_service import (
    empty_chain,
    escalate_approval_chain,
    module_for_route_target,
    progress_from_chain,
    record_approval,
    require_actor_in_pool,
)

_VAULT_TERMINAL_MESSAGE = (
    "Supporting document — stored in vault only; posting is not applicable "
    "for this document type."
)

_QUEUE_STATUSES = (
    InvoiceStatus.EXCEPTION,
    InvoiceStatus.DUPLICATE_SKIPPED,
    InvoiceStatus.REJECTED,
)

_BOARD_PIPELINE_STATUSES = (
    InvoiceStatus.PENDING,
    InvoiceStatus.PARSING,
    InvoiceStatus.VALIDATING,
    InvoiceStatus.MAPPING,
    InvoiceStatus.JOURNALING,
    InvoiceStatus.RECONCILING,
)

_BOARD_QUEUE_LIMIT = 150
_BOARD_PIPELINE_LIMIT = 100
_BOARD_PROCESSED_LIMIT = 100


def _board_load_options() -> tuple:
    # Keep quorum JSON for card labels; skip OCR blobs.
    return (
        defer(Invoice.document_text),
        defer(Invoice.extracted_fields),
        defer(Invoice.processing_overrides),
    )


async def _board_status_rows(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    statuses: tuple[InvoiceStatus, ...],
    limit: int,
) -> list[Invoice]:
    return (
        await db.execute(
            select(Invoice)
            .options(*_board_load_options())
            .where(
                Invoice.tenant_id == tenant_id,
                Invoice.status.in_(statuses),
            )
            .order_by(Invoice.created_at.desc(), Invoice.id.desc())
            .limit(limit)
        )
    ).scalars().all()


async def _board_column_counts(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
) -> tuple[dict[str, int], int]:
    """Uncapped kanban totals from GROUP BY — cards themselves stay limited."""
    grouped = (
        await db.execute(
            select(
                Invoice.status,
                Invoice.evaluation_status,
                Invoice.document_type_code,
                func.count(Invoice.id),
            )
            .where(
                Invoice.tenant_id == tenant_id,
                Invoice.status.in_(
                    (*_QUEUE_STATUSES, *_BOARD_PIPELINE_STATUSES, InvoiceStatus.PROCESSED)
                ),
            )
            .group_by(
                Invoice.status,
                Invoice.evaluation_status,
                Invoice.document_type_code,
            )
        )
    ).all()
    counts = {"review": 0, "processing": 0, "approved": 0, "rejected": 0}
    queue_count = 0
    queue_status_values = {status.value for status in _QUEUE_STATUSES}
    for status, evaluation_status, document_type_code, n in grouped:
        amount = int(n or 0)
        status_value = status.value if hasattr(status, "value") else str(status)
        if status_value in queue_status_values or status in _QUEUE_STATUSES:
            queue_count += amount
        stub = SimpleNamespace(
            status=status,
            evaluation_status=evaluation_status,
            document_type_code=document_type_code,
            extracted_fields=None,
            document_heading=None,
            document_text=None,
        )
        column = approval_board_column(stub)  # type: ignore[arg-type]
        counts[column] = counts.get(column, 0) + amount
    return counts, queue_count


async def list_approvals_board(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
) -> tuple[list[InvoiceResponse], ResponseMeta]:
    queue_rows = await _board_status_rows(
        db,
        tenant_id=tenant_id,
        statuses=_QUEUE_STATUSES,
        limit=_BOARD_QUEUE_LIMIT,
    )
    pipeline_rows = await _board_status_rows(
        db,
        tenant_id=tenant_id,
        statuses=_BOARD_PIPELINE_STATUSES,
        limit=_BOARD_PIPELINE_LIMIT,
    )
    processed_rows = await _board_status_rows(
        db,
        tenant_id=tenant_id,
        statuses=(InvoiceStatus.PROCESSED,),
        limit=_BOARD_PROCESSED_LIMIT,
    )
    by_id: dict[int, Invoice] = {}
    for row in (*queue_rows, *pipeline_rows, *processed_rows):
        by_id[row.id] = row
    rows = sorted(
        by_id.values(),
        key=lambda inv: (inv.created_at, inv.id),
        reverse=True,
    )
    # Heal older queue items that entered Approvals before chain materialization.
    from app.services.approval.approval_quorum_service import ensure_invoice_approval_chain

    healed = False
    for inv in rows:
        if inv.status not in _QUEUE_STATUSES:
            continue
        if ensure_invoice_approval_chain(inv):
            healed = True
    if healed:
        await db.flush()
    responses = await responses_for_approval_board(db, list(rows), tenant_id=tenant_id)
    by_id_inv = {inv.id: inv for inv in rows}
    enriched: list[InvoiceResponse] = []
    for resp in responses:
        inv = by_id_inv.get(resp.id)
        column = approval_board_column(inv) if inv is not None else None
        enriched.append(resp.model_copy(update={"approval_board_column": column}))
    totals, queue_count = await _board_column_counts(db, tenant_id=tenant_id)
    meta = ResponseMeta(
        approval_queue_count=queue_count,
        approval_review_count=totals["review"],
        approval_processing_count=totals["processing"],
        approval_approved_count=totals["approved"],
        approval_rejected_count=totals["rejected"],
    )
    return enriched, meta


@dataclass(frozen=True)
class ApprovalListResult:
    rows: list[InvoiceResponse]
    meta: ResponseMeta | None = None


@dataclass(frozen=True)
class ApproveInvoiceResult:
    response: InvoiceResponse
    enqueue_pipeline: bool = True
    enqueue_posting_resume: bool = False
    quorum_met: bool = True
    quorum: dict | None = None


@dataclass(frozen=True)
class ConfirmInvoiceResult:
    response: InvoiceResponse
    enqueue_pipeline: bool = True


async def list_approvals_queue(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    params: ApprovalListRequest,
) -> ApprovalListResult:
    stmt = (
        select(Invoice)
        .options(*invoice_list_load_options())
        .where(
            Invoice.tenant_id == tenant_id,
            Invoice.status.in_(_QUEUE_STATUSES),
        )
        .order_by(Invoice.created_at.desc())
    )
    count_stmt = select(func.count(Invoice.id)).where(
        Invoice.tenant_id == tenant_id,
        Invoice.status.in_(_QUEUE_STATUSES),
    )

    total = (await db.execute(count_stmt)).scalar() or 0
    pages = max(1, (total + params.page_size - 1) // params.page_size)
    rows = list(
        (
            await db.execute(
                stmt.offset((params.page - 1) * params.page_size).limit(params.page_size)
            )
        ).scalars().all()
    )
    from app.services.approval.approval_quorum_service import ensure_invoice_approval_chain

    healed = False
    for inv in rows:
        if ensure_invoice_approval_chain(inv):
            healed = True
    if healed:
        await db.flush()

    return ApprovalListResult(
        rows=await responses_for_invoices(
            db, rows, tenant_id=tenant_id, for_list=True
        ),
        meta=ResponseMeta(page=params.page, total=total, pages=pages),
    )


async def load_approvable_invoice(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    invoice_id: int,
) -> Invoice:
    inv = await get_invoice_for_tenant(db, invoice_id, tenant_id)
    if is_understood_path_vault_terminal(inv):
        raise ValueError(_VAULT_TERMINAL_MESSAGE)
    if inv.status == InvoiceStatus.PROCESSED:
        raise ValueError(
            "This invoice is already processed. Reject it first if you need "
            "to return it to the approval queue."
        )
    if inv.status not in APPROVABLE_STATUSES:
        raise ValueError(
            f"Invoice status '{inv.status.value}' is not in the approval queue"
        )
    return inv


def _is_vision_header_review_hold(inv: Invoice) -> bool:
    return (inv.evaluation_status or "").strip().lower() == EVAL_VISION_HEADER_REVIEW


async def _approve_invoice_for_posting_resume(
    db: AsyncSession,
    inv: Invoice,
    *,
    actor_name: str | None,
    actor_email: str | None,
) -> None:
    """Mark approved and ready to continue mapping→journal→post (no full reprocess).

    Approvers review/edit while the doc waits; after quorum we resume the next
    pipeline stages from persisted fields instead of restarting OCR/extract.
    Resume is enqueued by the API route (async) so the HTTP response stays fast.
    """
    loaded = (
        await db.execute(
            select(Invoice)
            .where(Invoice.id == inv.id)
            .options(selectinload(Invoice.line_items))
        )
    ).scalar_one()

    await assert_team_expense_approvable(db, loaded)
    config = await load_config_for_tenant(db, loaded.tenant_id)
    definition = resolve_vision_posting_definition(loaded, config)
    _assert_invoice_ready_for_approval(loaded, definition=definition)
    if payable_fields_complete(loaded, definition):
        apply_human_approval_processing_defaults(loaded)

    await restore_rejected_invoice_file_if_needed(db, loaded)
    from app.services.shared.file_storage import stored_file_available

    if not stored_file_available(loaded.raw_file_path, tenant_id=loaded.tenant_id):
        raise ValueError("Invoice has no stored file to process")

    previous_status = loaded.status.value
    is_team = (loaded.route_target or "").strip() == ROUTE_TEAM
    await log_event(
        db,
        "invoice_approved",
        invoice_id=loaded.id,
        detail={
            "previous_status": previous_status,
            "resolution": resolution_for_review_action(
                action="approve",
                previous_status=previous_status,
            ),
            "posting_resume": True,
            "posting_resume_deferred": True,
            "team_expense_posting_resume": is_team,
        },
        actor_name=actor_name,
        actor_email=actor_email,
    )
    # Clears sticky pending_approval so gates let the document through on resume.
    await reset_invoice_for_approval(db, loaded)
    # Show as in-flight until background resume finishes.
    loaded.status = InvoiceStatus.MAPPING

    inv.status = loaded.status
    inv.evaluation_status = loaded.evaluation_status
    inv.route_target = loaded.route_target
    inv.vendor = loaded.vendor
    inv.raw_file_path = loaded.raw_file_path
    inv.validation_results = loaded.validation_results
    inv.document_type_code = loaded.document_type_code
    inv.account_code = loaded.account_code
    inv.account_name = loaded.account_name
    inv.team_expense_kind = loaded.team_expense_kind


async def _approve_team_expense_for_posting(
    db: AsyncSession,
    inv: Invoice,
    *,
    actor_name: str | None,
    actor_email: str | None,
) -> None:
    """Backward-compatible alias — all routes now use posting resume after approve."""
    await _approve_invoice_for_posting_resume(
        db, inv, actor_name=actor_name, actor_email=actor_email
    )

async def _approve_vision_header_review_for_posting(
    db: AsyncSession,
    inv: Invoice,
    *,
    actor_name: str | None,
    actor_email: str | None,
    record_approval: bool = True,
) -> None:
    loaded = (
        await db.execute(
            select(Invoice)
            .where(Invoice.id == inv.id)
            .options(selectinload(Invoice.line_items))
        )
    ).scalar_one()

    await assert_team_expense_approvable(db, loaded)
    config = await load_config_for_tenant(db, loaded.tenant_id)
    definition = resolve_vision_posting_definition(loaded, config)
    header_ok = vision_header_ok_from_invoice(loaded, definition)

    if vision_dt_never_posts(loaded, definition):
        raise ValueError(_VAULT_TERMINAL_MESSAGE)
    if not vision_should_continue_posting(loaded, definition, header_ok=header_ok):
        raise ValueError(
            vision_posting_skip_user_message(loaded, definition, header_ok=header_ok)
        )

    _assert_invoice_ready_for_approval(loaded, definition=definition)
    if record_approval and payable_fields_complete(loaded, definition):
        apply_human_approval_processing_defaults(loaded)
    if not record_approval:
        loaded.approval_chain = None
        inv.approval_chain = None

    previous_status = loaded.status.value
    await log_event(
        db,
        "invoice_approved" if record_approval else "invoice_confirm_processed",
        invoice_id=loaded.id,
        detail={
            "previous_status": previous_status,
            "resolution": (
                resolution_for_review_action(
                    action="approve",
                    previous_status=previous_status,
                )
                if record_approval
                else None
            ),
            "vision_posting_resume": True,
            "manager_approval": record_approval,
        },
        actor_name=actor_name,
        actor_email=actor_email,
    )

    tenant_row = await db.get(Tenant, loaded.tenant_id)
    org = org_context_from_config(config, tenant_row)
    assert definition is not None

    # Do NOT re-run vision DT extract on Confirm when DT-required fields are already
    # complete — re-extract overwrites saved header values and falsely re-raises
    # "Complete header fields…".
    from app.config import get_settings
    from app.services.invoice.invoice_edit_service import invoice_has_manual_field_edits

    header_already_ok = vision_header_ok_from_invoice(loaded, definition)
    manual_edits = await invoice_has_manual_field_edits(
        db, loaded.id, tenant_id=loaded.tenant_id
    )
    should_reextract = (
        get_settings().vision_dt_scoped_extract
        and (loaded.document_type_code or "").strip()
        and not header_already_ok
        and not manual_edits
        and not payable_fields_complete(loaded, definition)
    )
    if should_reextract:
        from app.services.extraction.document_ai_provider import DocumentAiProvider
        from app.services.invoice.invoice_pipeline_phases import phase_vision_dt_extract

        provider = DocumentAiProvider.from_config(get_settings().vision_llm_provider)
        await phase_vision_dt_extract(
            db,
            loaded,
            org=org,
            document_types=list(config.document_types or []),
            confirmed_dt=loaded.document_type_code or "",
            doc_provider=provider,
            document_ai_provider=provider.value,
            definition=definition,
        )
        await db.flush()
        # Re-check readiness after re-extract.
        header_ok = vision_header_ok_from_invoice(loaded, definition)
        if not vision_should_continue_posting(loaded, definition, header_ok=header_ok):
            raise ValueError(
                vision_posting_skip_user_message(loaded, definition, header_ok=header_ok)
            )
        _assert_invoice_ready_for_approval(loaded, definition=definition)

    await continue_vision_understood_posting(
        db,
        loaded,
        config=config,
        org=org,
        definition=definition,
    )

    inv.status = loaded.status
    inv.evaluation_status = loaded.evaluation_status
    inv.route_target = loaded.route_target
    inv.vendor = loaded.vendor
    inv.raw_file_path = loaded.raw_file_path
    inv.validation_results = loaded.validation_results
    inv.document_type_code = loaded.document_type_code


async def approve_invoice_action(
    db: AsyncSession,
    ctx: AuthContext,
    *,
    invoice_id: int,
) -> ApproveInvoiceResult:
    inv = await get_invoice_for_tenant(db, invoice_id, ctx.tenant_id)
    if is_understood_path_vault_terminal(inv):
        raise ValueError(_VAULT_TERMINAL_MESSAGE)
    if inv.status == InvoiceStatus.PROCESSED:
        raise ValueError(
            "This invoice is already processed. Reject it first if you need "
            "to return it to the approval queue."
        )
    if inv.status not in APPROVABLE_STATUSES:
        raise ValueError(
            f"Invoice status '{inv.status.value}' is not in the approval queue"
        )

    await ensure_stored_file_for_approval(db, inv)
    actor_name, actor_email = await actor_from_context(db, ctx)

    require_actor_in_pool(ctx)
    module_key = module_for_route_target(inv.route_target)
    inv.approval_chain = record_approval(
        inv.approval_chain,
        tenant_id=ctx.tenant_id,
        module_key=module_key,
        user_id=int(ctx.user_id),
        role=ctx.role or "",
        name=actor_name or actor_email or f"User {ctx.user_id}",
        amount=inv.total,
    )
    progress = progress_from_chain(inv.approval_chain)
    if progress is None or not progress.quorum_met:
        await log_event(
            db,
            "invoice_approval_recorded",
            invoice_id=inv.id,
            tenant_id=ctx.tenant_id,
            actor_name=actor_name,
            actor_email=actor_email,
            detail=progress.as_dict() if progress else None,
        )
        response = await response_for_invoice(db, inv, tenant_id=ctx.tenant_id)
        return ApproveInvoiceResult(
            response=response,
            enqueue_pipeline=False,
            quorum_met=False,
            quorum=progress.as_dict() if progress else None,
        )

    if _is_vision_header_review_hold(inv):
        await _approve_vision_header_review_for_posting(
            db,
            inv,
            actor_name=actor_name,
            actor_email=actor_email,
        )
        response = await response_for_invoice(db, inv, tenant_id=ctx.tenant_id)
        return ApproveInvoiceResult(
            response=response,
            enqueue_pipeline=False,
            quorum_met=True,
            quorum=progress.as_dict(),
        )

    # Checkpoint complete: continue mapping→journal→post (do not full-reprocess).
    await _approve_invoice_for_posting_resume(
        db,
        inv,
        actor_name=actor_name,
        actor_email=actor_email,
    )
    response = await response_for_invoice(db, inv, tenant_id=ctx.tenant_id)
    return ApproveInvoiceResult(
        response=response,
        enqueue_pipeline=False,
        enqueue_posting_resume=True,
        quorum_met=True,
        quorum=progress.as_dict(),
    )


async def confirm_and_process_action(
    db: AsyncSession,
    ctx: AuthContext,
    *,
    invoice_id: int,
) -> ConfirmInvoiceResult:
    """Continue processing after field review without recording manager approval."""
    inv = await get_invoice_for_tenant(db, invoice_id, ctx.tenant_id)
    if is_understood_path_vault_terminal(inv):
        raise ValueError(_VAULT_TERMINAL_MESSAGE)
    if inv.status == InvoiceStatus.PROCESSED:
        raise ValueError(
            "This invoice is already processed. Reject it first if you need "
            "to return it to the approval queue."
        )
    if inv.status != InvoiceStatus.EXCEPTION:
        raise ValueError(
            f"Invoice status '{inv.status.value}' cannot confirm and process"
        )

    await ensure_stored_file_for_approval(db, inv)
    actor_name, actor_email = await actor_from_context(db, ctx)

    if _is_vision_header_review_hold(inv):
        await _approve_vision_header_review_for_posting(
            db,
            inv,
            actor_name=actor_name,
            actor_email=actor_email,
            record_approval=False,
        )
        response = await response_for_invoice(db, inv, tenant_id=ctx.tenant_id)
        return ConfirmInvoiceResult(response=response, enqueue_pipeline=False)

    await confirm_invoice_for_process(
        db, inv, actor_name=actor_name, actor_email=actor_email
    )
    response = await response_for_invoice(db, inv, tenant_id=ctx.tenant_id)
    return ConfirmInvoiceResult(response=response, enqueue_pipeline=True)


async def reject_invoice_action(
    db: AsyncSession,
    ctx: AuthContext,
    *,
    invoice_id: int,
) -> InvoiceResponse:
    inv = await get_invoice_for_tenant(db, invoice_id, ctx.tenant_id)
    inv.approval_chain = None
    actor_name, actor_email = await actor_from_context(db, ctx)
    await reject_invoice(db, inv, actor_name=actor_name, actor_email=actor_email)
    return await response_for_invoice(db, inv, tenant_id=ctx.tenant_id)


async def escalate_invoice_action(
    db: AsyncSession,
    ctx: AuthContext,
    *,
    invoice_id: int,
    note: str,
) -> InvoiceResponse:
    inv = await get_invoice_for_tenant(db, invoice_id, ctx.tenant_id)
    actor_name, actor_email = await actor_from_context(db, ctx)
    require_actor_in_pool(ctx)
    module_key = module_for_route_target(inv.route_target)
    if not inv.approval_chain:
        inv.approval_chain = empty_chain(
            tenant_id=ctx.tenant_id,
            module_key=module_key,
            amount=inv.total,
        )
    inv.approval_chain = escalate_approval_chain(
        inv.approval_chain,
        note=note,
        actor_role=ctx.role or "",
        actor_name=actor_name or actor_email,
    )
    await escalate_invoice(
        db,
        inv,
        note=note,
        actor_name=actor_name,
        actor_email=actor_email,
    )
    return await response_for_invoice(db, inv, tenant_id=ctx.tenant_id)


async def request_approval_action(
    db: AsyncSession,
    ctx: AuthContext,
    *,
    invoice_id: int,
) -> InvoiceResponse:
    inv = await get_invoice_for_tenant(db, invoice_id, ctx.tenant_id)
    actor_name, actor_email = await actor_from_context(db, ctx)
    await request_approval(db, inv, actor_name=actor_name, actor_email=actor_email)
    return await response_for_invoice(db, inv, tenant_id=ctx.tenant_id)


async def permanently_delete_invoice_action(
    db: AsyncSession,
    ctx: AuthContext,
    *,
    invoice_id: int,
) -> None:
    inv = await get_invoice_for_tenant(db, invoice_id, ctx.tenant_id)
    await permanently_delete_invoice(db, inv)
