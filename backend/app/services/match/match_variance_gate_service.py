"""Hard gate: block posting when PO/SO match variance is unapproved."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.audit import AuditLog
from app.models.invoice import Invoice, InvoiceStatus
from app.schemas.rule_book_config import RuleBookConfigPayload
from app.schemas.uom_conversion import PurchaseMatchConfig
from app.services.audit.audit_service import log_event
from app.services.classification.document_type_match_service import (
    DocumentMatchOutcome,
    PRICE_MATCH_CAP_AUD,
    PRICE_MATCH_PCT,
    resolve_match_mode,
)
from app.services.classification.document_type_playbook_profile_service import (
    gl_posting_applicable_for_invoice,
    match_mode_requires_po,
    match_mode_requires_sales,
)
from app.services.invoice.invoice_evaluation_service import ROUTE_PURCHASE, ROUTE_SALES
from app.services.invoice.invoice_reset import reset_invoice_for_approval
from app.services.purchase.purchase_match_service import (
    execute_purchase_document_match,
    load_purchase_order_for_invoice,
)
from app.services.sales.sales_match_service import (
    execute_ar_document_match,
    load_sales_order_for_invoice,
)

VARIANCE_BLOCKING_STATUSES = frozenset(
    {
        "Qty Variance",
        "Price Variance",
        "Amount Variance",
    }
)

POSTING_BLOCKING_STATUSES = VARIANCE_BLOCKING_STATUSES | frozenset(
    {
        "No GRN",
        "No DN",
    }
)

MATCH_FAIL_STATUSES = POSTING_BLOCKING_STATUSES | frozenset(
    {
        "Routed for Approval",
    }
)


@dataclass(frozen=True)
class MatchVarianceGateResult:
    blocked: bool
    outcome: DocumentMatchOutcome | None
    variance_approved: bool
    anchor_number: str | None
    anchor_type: str | None
    qty_tolerance_pct: float
    match_mode: str | None = None


def _outcome_blocks_variance(
    outcome: DocumentMatchOutcome,
    *,
    variance_approved: bool,
) -> bool:
    if outcome.passed:
        return False
    # Missing receipt is not cleared by PO/SO variance approval.
    if outcome.status in {"No GRN", "No DN"}:
        return True
    if outcome.status in VARIANCE_BLOCKING_STATUSES:
        return not variance_approved
    return False


def build_variance_gate_audit_detail(
    gate: MatchVarianceGateResult,
) -> dict[str, object]:
    outcome = gate.outcome
    detail: dict[str, object] = {
        "variance_approved": gate.variance_approved,
        "anchor_number": gate.anchor_number,
        "anchor_type": gate.anchor_type,
        "qty_tolerance_pct": gate.qty_tolerance_pct,
        "price_tolerance_pct": float(PRICE_MATCH_PCT),
        "price_tolerance_cap": float(PRICE_MATCH_CAP_AUD),
        "match_mode": gate.match_mode,
    }
    if outcome is not None:
        detail.update(
            {
                "match_status": outcome.status,
                "match_message": outcome.message,
                "qty_variance_value": outcome.detail.get("qty_variance_value"),
                "price_variance_value": outcome.detail.get("price_variance_value"),
                "total_deviation": outcome.detail.get("total_deviation"),
            }
        )
    return detail


async def evaluate_match_variance_gate(
    session: AsyncSession,
    invoice: Invoice,
    *,
    config: RuleBookConfigPayload,
) -> MatchVarianceGateResult:
    """Return blocked=True when match variance exists and PO/SO variance_approved is false."""
    match_cfg = config.purchase_match
    qty_tolerance = float(match_cfg.qty_tolerance_pct)

    if not gl_posting_applicable_for_invoice(
        invoice,
        document_types=list(config.document_types),
    ):
        return MatchVarianceGateResult(
            blocked=False,
            outcome=None,
            variance_approved=False,
            anchor_number=None,
            anchor_type=None,
            qty_tolerance_pct=qty_tolerance,
        )

    route = (invoice.route_target or "").strip()
    if route not in {ROUTE_PURCHASE, ROUTE_SALES}:
        return MatchVarianceGateResult(
            blocked=False,
            outcome=None,
            variance_approved=False,
            anchor_number=None,
            anchor_type=None,
            qty_tolerance_pct=qty_tolerance,
        )

    match_mode = resolve_match_mode(
        document_type_code=invoice.document_type_code,
        document_types=list(config.document_types),
        tenant_id=invoice.tenant_id,
    )
    if match_mode == "none" or (
        not match_mode_requires_po(match_mode) and not match_mode_requires_sales(match_mode)
    ):
        return MatchVarianceGateResult(
            blocked=False,
            outcome=None,
            variance_approved=False,
            anchor_number=None,
            anchor_type=None,
            qty_tolerance_pct=qty_tolerance,
            match_mode=match_mode,
        )

    anchor_number: str | None = None
    anchor_type: str | None = None
    variance_approved = False

    if route == ROUTE_PURCHASE:
        po = await load_purchase_order_for_invoice(session, invoice)
        if po is not None:
            anchor_number = po.po_number
            anchor_type = "purchase"
            variance_approved = bool(po.variance_approved)
        outcome_raw = await execute_purchase_document_match(
            match_mode,
            session=session,
            invoice=invoice,
            match_config=match_cfg,
        )
    else:
        so = await load_sales_order_for_invoice(session, invoice)
        if so is not None:
            anchor_number = so.so_number
            anchor_type = "sales"
            variance_approved = bool(so.variance_approved)
        outcome_raw = await execute_ar_document_match(
            match_mode,
            session=session,
            invoice=invoice,
            match_config=match_cfg,
        )

    outcome = outcome_raw if isinstance(outcome_raw, DocumentMatchOutcome) else None
    blocked = outcome is not None and _outcome_blocks_variance(
        outcome,
        variance_approved=variance_approved,
    )
    return MatchVarianceGateResult(
        blocked=blocked,
        outcome=outcome,
        variance_approved=variance_approved,
        anchor_number=anchor_number,
        anchor_type=anchor_type,
        qty_tolerance_pct=qty_tolerance,
        match_mode=match_mode,
    )


async def _latest_variance_hold_log(
    session: AsyncSession,
    invoice_id: int,
) -> AuditLog | None:
    return (
        await session.execute(
            select(AuditLog)
            .where(
                AuditLog.invoice_id == invoice_id,
                AuditLog.event == "three_way_match_variance_unapproved",
            )
            .order_by(AuditLog.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def resume_invoice_posting_after_variance_approval(
    session: AsyncSession,
    invoice: Invoice,
    *,
    config: RuleBookConfigPayload | None = None,
) -> bool:
    """Resume mapping→journal→post without OCR/LLM/extract. Returns True when run."""
    from app.services.invoice.invoice_evaluation_service import load_config_for_tenant
    from app.services.invoice.pipeline import resume_invoice_posting_pipeline

    if invoice.status != InvoiceStatus.EXCEPTION:
        return False

    hold_log = await _latest_variance_hold_log(session, invoice.id)
    if hold_log is None:
        return False

    cfg = config or await load_config_for_tenant(session, invoice.tenant_id)
    gate = await evaluate_match_variance_gate(session, invoice, config=cfg)
    if gate.blocked:
        return False

    await log_event(
        session,
        "variance_approval_reprocess_queued",
        invoice_id=invoice.id,
        tenant_id=invoice.tenant_id,
        detail={
            "anchor_number": gate.anchor_number,
            "anchor_type": gate.anchor_type,
        },
    )
    await reset_invoice_for_approval(session, invoice)
    await session.flush()
    await resume_invoice_posting_pipeline(session, invoice, config=cfg)
    await log_event(
        session,
        "variance_approval_posting_resumed",
        invoice_id=invoice.id,
        tenant_id=invoice.tenant_id,
        detail={
            "anchor_number": gate.anchor_number,
            "anchor_type": gate.anchor_type,
            "status": invoice.status.value,
        },
    )
    return True
