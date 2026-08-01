"""Approval queue and kanban API orchestration."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

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
    approve_invoice_for_reprocess,
    permanently_delete_invoice,
    reject_invoice,
    request_approval,
    resolution_for_review_action,
)
from app.services.audit.audit_service import log_event
from app.services.shared.file_storage import ensure_stored_file_for_approval
from app.services.invoice.invoice_access_service import get_invoice_for_tenant
from app.services.invoice.invoice_evaluation_service import (
    EVAL_PENDING_APPROVAL,
    EVAL_VISION_HEADER_REVIEW,
    ROUTE_TEAM,
    load_config_for_tenant,
)
from app.services.invoice.invoice_reset import reset_invoice_for_approval
from app.services.invoice.invoice_response_service import (
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

_BOARD_PROCESSED_LIMIT = 100


@dataclass(frozen=True)
class ApprovalListResult:
    rows: list[InvoiceResponse]
    meta: ResponseMeta | None = None


@dataclass(frozen=True)
class ApproveInvoiceResult:
    response: InvoiceResponse
    enqueue_pipeline: bool = True


async def list_approvals_board(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
) -> list[InvoiceResponse]:
    active_statuses = _QUEUE_STATUSES + _BOARD_PIPELINE_STATUSES
    active_rows = (
        await db.execute(
            select(Invoice)
            .where(
                Invoice.tenant_id == tenant_id,
                Invoice.status.in_(active_statuses),
            )
            .order_by(Invoice.created_at.desc(), Invoice.id.desc())
        )
    ).scalars().all()
    processed_rows = (
        await db.execute(
            select(Invoice)
            .where(
                Invoice.tenant_id == tenant_id,
                Invoice.status == InvoiceStatus.PROCESSED,
            )
            .order_by(Invoice.created_at.desc(), Invoice.id.desc())
            .limit(_BOARD_PROCESSED_LIMIT)
        )
    ).scalars().all()
    by_id: dict[int, Invoice] = {}
    for row in (*active_rows, *processed_rows):
        by_id[row.id] = row
    rows = sorted(
        by_id.values(),
        key=lambda inv: (inv.created_at, inv.id),
        reverse=True,
    )
    responses = await responses_for_approval_board(db, list(rows), tenant_id=tenant_id)
    by_id_inv = {inv.id: inv for inv in rows}
    enriched: list[InvoiceResponse] = []
    for resp in responses:
        inv = by_id_inv.get(resp.id)
        column = approval_board_column(inv) if inv is not None else None
        enriched.append(resp.model_copy(update={"approval_board_column": column}))
    return enriched


async def list_approvals_queue(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    params: ApprovalListRequest,
) -> ApprovalListResult:
    stmt = (
        select(Invoice)
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
    rows = (
        await db.execute(
            stmt.offset((params.page - 1) * params.page_size).limit(params.page_size)
        )
    ).scalars().all()

    return ApprovalListResult(
        rows=await responses_for_invoices(db, list(rows), tenant_id=tenant_id),
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


def _is_team_expense_approval_hold(inv: Invoice) -> bool:
    return (
        (inv.route_target or "").strip() == ROUTE_TEAM
        and (inv.evaluation_status or "").strip().lower() == EVAL_PENDING_APPROVAL
    )


async def _approve_team_expense_for_posting(
    db: AsyncSession,
    inv: Invoice,
    *,
    actor_name: str | None,
    actor_email: str | None,
) -> None:
    """Resume mapping→journal after manager approval — do not re-run vision/OCR."""
    from app.services.invoice.pipeline import resume_invoice_posting_pipeline

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
    if payable_fields_complete(loaded):
        apply_human_approval_processing_defaults(loaded)

    previous_status = loaded.status.value
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
            "team_expense_posting_resume": True,
        },
        actor_name=actor_name,
        actor_email=actor_email,
    )
    # Clears sticky pending_approval so the gate lets the claim through.
    await reset_invoice_for_approval(db, loaded)
    await resume_invoice_posting_pipeline(db, loaded, config=config)

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


async def _approve_vision_header_review_for_posting(
    db: AsyncSession,
    inv: Invoice,
    *,
    actor_name: str | None,
    actor_email: str | None,
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
    if payable_fields_complete(loaded):
        apply_human_approval_processing_defaults(loaded)

    previous_status = loaded.status.value
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
            "vision_posting_resume": True,
        },
        actor_name=actor_name,
        actor_email=actor_email,
    )

    tenant_row = await db.get(Tenant, loaded.tenant_id)
    org = org_context_from_config(config, tenant_row)
    assert definition is not None

    from app.config import get_settings

    if get_settings().vision_dt_scoped_extract and (loaded.document_type_code or "").strip():
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

    if _is_vision_header_review_hold(inv):
        await _approve_vision_header_review_for_posting(
            db,
            inv,
            actor_name=actor_name,
            actor_email=actor_email,
        )
        response = await response_for_invoice(db, inv, tenant_id=ctx.tenant_id)
        return ApproveInvoiceResult(response=response, enqueue_pipeline=False)

    if _is_team_expense_approval_hold(inv):
        await _approve_team_expense_for_posting(
            db,
            inv,
            actor_name=actor_name,
            actor_email=actor_email,
        )
        response = await response_for_invoice(db, inv, tenant_id=ctx.tenant_id)
        return ApproveInvoiceResult(response=response, enqueue_pipeline=False)

    await approve_invoice_for_reprocess(
        db, inv, actor_name=actor_name, actor_email=actor_email
    )
    response = await response_for_invoice(db, inv, tenant_id=ctx.tenant_id)
    return ApproveInvoiceResult(response=response, enqueue_pipeline=True)


async def reject_invoice_action(
    db: AsyncSession,
    ctx: AuthContext,
    *,
    invoice_id: int,
) -> InvoiceResponse:
    inv = await get_invoice_for_tenant(db, invoice_id, ctx.tenant_id)
    actor_name, actor_email = await actor_from_context(db, ctx)
    await reject_invoice(db, inv, actor_name=actor_name, actor_email=actor_email)
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
