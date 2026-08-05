"""Document-type approval gate after validation (before mapping / journaling)."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import Invoice, InvoiceStatus
from app.schemas.document_type import DocumentTypeDefinition
from app.schemas.playbook_policy import ApprovalPolicy
from app.services.audit.audit_service import log_event
from app.services.classification.document_type_playbook_profile_service import (
    effective_approval_policy,
    effective_match_policy,
    match_mode_requires_po,
    match_mode_requires_sales,
)
from app.services.classification.document_type_match_service import is_clean_match_message
from app.services.invoice.invoice_evaluation_service import (
    EVAL_PENDING_APPROVAL,
    ROUTE_PURCHASE,
    ROUTE_SALES,
    ROUTE_TEAM,
)
from app.services.invoice.processing_cycle_service import latest_audit_detail_after_cycle_reset
from app.services.master_data.counterparty_trust_service import counterparty_requires_registration
from app.services.purchase.purchase_match_service import (
    compute_three_way_match,
    load_purchase_order_for_invoice,
)
from app.services.sales.sales_match_service import compute_three_way_match as compute_sales_three_way_match
from app.services.rule_book.validator import ValidationResult

_CLEAN_MATCH_STATUSES = frozenset(
    {
        "3-Way Match",
        "2-Way Match",
        "Reference Match",
        "Shipment Match",
        "Receipt Match",
    }
)


async def has_document_approval(session: AsyncSession, invoice_id: int) -> bool:
    from app.models.invoice import Invoice
    from app.services.approval.approval_quorum_service import quorum_met
    from app.services.invoice.processing_cycle_service import (
        has_audit_event_after_cycle_reset,
    )

    invoice = await session.get(Invoice, invoice_id)
    if invoice is not None and isinstance(getattr(invoice, "approval_chain", None), dict):
        return quorum_met(invoice.approval_chain)

    return await has_audit_event_after_cycle_reset(
        session,
        invoice_id,
        event="invoice_approved",
    )


def _validation_result_map(results: list[ValidationResult]) -> dict[str, ValidationResult]:
    return {row.rule: row for row in results}


def _match_is_clean_for_touchless(
    results: list[ValidationResult],
    *,
    match_mode: str,
) -> bool:
    _ = results
    if not match_mode_requires_po(match_mode) and match_mode not in {
        "reference_invoice",
        "shipment",
        "receipt_line",
        "three_way_so_dn",
        "two_way_so_invoice",
        "two_way_dn_invoice",
        "two_way_grn_invoice",
    }:
        return True
    return False


def _audit_match_is_clean(detail: dict[str, object] | None) -> bool:
    if not detail:
        return False
    for key in ("status", "match_status", "three_way_status"):
        raw = detail.get(key)
        if raw is None:
            continue
        token = str(raw).strip()
        if token in _CLEAN_MATCH_STATUSES:
            return True
        if is_clean_match_message(token):
            return True
    return False


async def _resolve_effective_match_tier(
    session: AsyncSession,
    invoice: Invoice,
    match_mode: str,
) -> str:
    route = (invoice.route_target or "").strip()
    if route == ROUTE_PURCHASE:
        from app.services.purchase.purchase_match_service import resolve_purchase_match_context

        ctx = await resolve_purchase_match_context(session, invoice, requested_mode=match_mode)
        return ctx.effective_mode
    if route == ROUTE_SALES:
        from app.services.sales.sales_match_service import resolve_ar_match_context

        ctx = await resolve_ar_match_context(session, invoice, requested_mode=match_mode)
        return ctx.effective_mode
    return "none"


def _amount_requires_approval(invoice: Invoice, policy: ApprovalPolicy) -> bool:
    if policy.auto_approve_below is None:
        return False
    if invoice.total is None:
        return True
    return float(invoice.total) >= float(policy.auto_approve_below)


async def _collect_risk_hold_reasons(
    session: AsyncSession,
    invoice: Invoice,
    policy: ApprovalPolicy,
    *,
    match_mode: str,
    resolved_tier: str | None = None,
) -> list[str]:
    reasons: list[str] = []
    tier = resolved_tier
    if policy.require_approval_for_unmatched:
        if tier is None:
            tier = await _resolve_effective_match_tier(session, invoice, match_mode)
        if tier == "none":
            reasons.append("unmatched_document")
    if _amount_requires_approval(invoice, policy):
        reasons.append("amount_above_threshold")
    if policy.require_approval_for_unverified_counterparty:
        if await counterparty_requires_registration(session, invoice):
            reasons.append("unverified_counterparty")
    return reasons


async def _touchless_match_satisfied(
    session: AsyncSession,
    invoice: Invoice,
    validation_results: list[ValidationResult],
    *,
    match_mode: str,
    resolved_tier: str | None = None,
) -> bool:
    if _match_is_clean_for_touchless(validation_results, match_mode=match_mode):
        return True

    audit_detail = await latest_audit_detail_after_cycle_reset(
        session,
        invoice.id,
        event="three_way_match_evaluated",
        tenant_id=invoice.tenant_id,
    )
    if _audit_match_is_clean(audit_detail):
        return True

    if match_mode_requires_po(match_mode):
        from app.services.purchase.purchase_match_service import (
            compute_two_way_grn_match,
            resolve_purchase_match_context,
        )

        ctx = await resolve_purchase_match_context(session, invoice, requested_mode=match_mode)
        tier = resolved_tier or ctx.effective_mode
        po = ctx.po
        grn_invoice = ctx.grn_invoice

        if tier == "three_way_po_grn" and po is not None:
            match = compute_three_way_match(po, invoice)
            if match.status == "3-Way Match" or po.variance_approved:
                return True
        elif tier == "two_way_po_ses" and po is not None:
            from app.services.classification.document_type_match_service import compute_two_way_po_match

            outcome = compute_two_way_po_match(po, invoice)
            if outcome.passed or po.variance_approved:
                return True
        elif tier == "two_way_grn_invoice" and grn_invoice is not None:
            from app.services.purchase.purchase_match_service import _load_grn_invoice_qty

            grn_qty = await _load_grn_invoice_qty(session, grn_invoice)
            match = compute_two_way_grn_match(grn_qty=grn_qty, inv=invoice)
            if match.status == "2-Way Match":
                return True
    elif match_mode_requires_sales(match_mode):
        from app.services.sales.sales_match_service import (
            compute_two_way_dn_match,
            compute_two_way_so_match,
            resolve_ar_match_context,
        )

        ctx = await resolve_ar_match_context(session, invoice, requested_mode=match_mode)
        tier = resolved_tier or ctx.effective_mode
        so = ctx.so
        dn_invoice = ctx.dn_invoice

        if tier == "three_way_so_dn" and so is not None:
            match = compute_sales_three_way_match(so, invoice)
            if match.status == "3-Way Match" or so.variance_approved:
                return True
        elif tier == "two_way_so_invoice" and so is not None:
            match = compute_two_way_so_match(so, invoice)
            if match.status == "2-Way Match" or so.variance_approved:
                return True
        elif tier == "two_way_dn_invoice" and dn_invoice is not None:
            from app.services.sales.sales_match_service import _load_dn_invoice_qty

            dn_qty, dn_uom = await _load_dn_invoice_qty(session, dn_invoice)
            match = compute_two_way_dn_match(dn_qty=dn_qty, dn_uom=dn_uom, inv=invoice)
            if match.status == "2-Way Match":
                return True
    return False


async def _hold_for_approval(
    session: AsyncSession,
    invoice: Invoice,
    *,
    definition: DocumentTypeDefinition,
    reason: str,
    reasons: list[str] | None = None,
    extra_detail: dict[str, object] | None = None,
) -> None:
    invoice.status = InvoiceStatus.EXCEPTION
    invoice.evaluation_status = EVAL_PENDING_APPROVAL
    all_reasons = reasons if reasons else [reason]
    detail: dict[str, object] = {
        "reason": all_reasons[0],
        "reasons": all_reasons,
        "document_type_code": definition.code,
        "approval_mode": effective_approval_policy(definition).mode,
    }
    if extra_detail:
        detail.update(extra_detail)
    await log_event(
        session,
        "approval_required",
        invoice_id=invoice.id,
        detail=detail,
    )


def _plausible_ref(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


async def _hold_for_missing_purchase_anchor(
    session: AsyncSession,
    invoice: Invoice,
    *,
    match_mode: str,
) -> bool:
    """Invoice/GRN before PO: hold as awaiting_po — not pending_approval."""
    if not match_mode_requires_po(match_mode):
        return False
    if (invoice.route_target or "").strip() != ROUTE_PURCHASE:
        return False

    from app.models.invoice import PurchaseDocumentType
    from app.services.purchase.po_reference import (
        effective_po_reference,
        is_plausible_po_reference,
    )
    from app.services.purchase.purchase_document_service import EVAL_AWAITING_PO

    doc_type = (invoice.purchase_document_type or "").strip().lower()
    if doc_type == PurchaseDocumentType.PO.value:
        # PO documents create the register — never wait for themselves.
        return False

    po_number = _plausible_ref(getattr(invoice, "po_reference", None))
    if po_number:
        po_number = effective_po_reference(po_number) or po_number
    if not po_number or not is_plausible_po_reference(po_number):
        return False

    po = await load_purchase_order_for_invoice(session, invoice)
    if po is not None:
        return False

    invoice.status = InvoiceStatus.EXCEPTION
    invoice.evaluation_status = EVAL_AWAITING_PO
    await log_event(
        session,
        "purchase_awaiting_po",
        invoice_id=invoice.id,
        detail={
            "po_number": po_number,
            "document_type": doc_type or PurchaseDocumentType.INVOICE.value,
            "reason": "missing_po_before_approval",
            "match_mode": match_mode,
        },
    )
    return True


async def _hold_for_missing_sales_anchor(
    session: AsyncSession,
    invoice: Invoice,
    *,
    match_mode: str,
) -> bool:
    """Invoice/DN before SO: hold as awaiting_so — not pending_approval."""
    if not match_mode_requires_sales(match_mode):
        return False
    if (invoice.route_target or "").strip() != ROUTE_SALES:
        return False

    from app.models.invoice import SalesDocumentType
    from app.services.sales.sales_document_service import EVAL_AWAITING_SO
    from app.services.sales.sales_match_service import load_sales_order_for_invoice
    from app.services.sales.so_reference import (
        effective_so_reference,
        is_plausible_so_reference,
    )

    doc_type = (invoice.sales_document_type or "").strip().lower()
    if doc_type == SalesDocumentType.SO.value:
        return False

    # Prefer the stored SO field only — avoid filename OCR helpers that break on
    # incomplete/mock invoice objects during gate evaluation.
    so_number = _plausible_ref(getattr(invoice, "so_reference", None))
    if so_number:
        so_number = effective_so_reference(so_number) or so_number
    if not so_number or not is_plausible_so_reference(so_number):
        return False

    so = await load_sales_order_for_invoice(session, invoice)
    if so is not None:
        return False

    invoice.status = InvoiceStatus.EXCEPTION
    invoice.evaluation_status = EVAL_AWAITING_SO
    await log_event(
        session,
        "sales_awaiting_so",
        invoice_id=invoice.id,
        detail={
            "so_number": so_number,
            "document_type": doc_type or SalesDocumentType.INVOICE.value,
            "reason": "missing_so_before_approval",
            "match_mode": match_mode,
        },
    )
    return True


async def apply_document_type_approval_gate(
    session: AsyncSession,
    invoice: Invoice,
    *,
    definition: DocumentTypeDefinition | None,
    validation_results: list[ValidationResult],
    human_approval_bypass: bool = False,
) -> bool:
    """
    Hold invoice for manual approval when the document-type policy requires it.

    Returns True when the invoice is held (status set to exception).
    Missing PO/SO register anchors hold as awaiting_po / awaiting_so instead of
    pending_approval (P-hold / S-hold before match approval).
    """
    if definition is None:
        return False

    if human_approval_bypass or await has_document_approval(session, invoice.id):
        return False

    policy = effective_approval_policy(definition)
    mode = policy.mode

    if mode == "no_posting":
        return False

    if mode == "manager_gate":
        return False

    match_mode = effective_match_policy(definition).mode

    # Register-anchor holds beat approval: invoice-before-PO must wait for the PO,
    # not land in Approvals as match_not_clean.
    if await _hold_for_missing_purchase_anchor(session, invoice, match_mode=match_mode):
        return True
    if await _hold_for_missing_sales_anchor(session, invoice, match_mode=match_mode):
        return True

    resolved_tier: str | None = None
    if policy.require_approval_for_unmatched:
        resolved_tier = await _resolve_effective_match_tier(session, invoice, match_mode)

    risk_reasons = await _collect_risk_hold_reasons(
        session,
        invoice,
        policy,
        match_mode=match_mode,
        resolved_tier=resolved_tier,
    )
    if risk_reasons:
        extra: dict[str, object] = {
            "match_mode": match_mode,
            "resolved_match_tier": resolved_tier,
        }
        if policy.auto_approve_below is not None:
            extra["auto_approve_below"] = policy.auto_approve_below
        if invoice.total is not None:
            extra["amount"] = float(invoice.total)
        currency = getattr(invoice, "currency", None)
        if currency:
            extra["currency"] = str(currency).strip()
        await _hold_for_approval(
            session,
            invoice,
            definition=definition,
            reason=risk_reasons[0],
            reasons=risk_reasons,
            extra_detail=extra,
        )
        return True

    if mode == "variance_workflow":
        if not match_mode_requires_po(match_mode):
            return False
        po = await load_purchase_order_for_invoice(session, invoice)
        if po is not None and po.variance_approved:
            return False
        await _hold_for_approval(
            session,
            invoice,
            definition=definition,
            reason="purchase_variance_pending",
        )
        return True

    if mode in {"full_doa", "never_touchless", "supervisor_on_exception"}:
        if mode == "supervisor_on_exception" and await _touchless_match_satisfied(
            session,
            invoice,
            validation_results,
            match_mode=match_mode,
            resolved_tier=resolved_tier,
        ):
            return False
        await _hold_for_approval(session, invoice, definition=definition, reason=mode)
        return True

    if mode == "touchless_on_clean_match":
        if match_mode in {"none", "subledger_reconcile"}:
            return False
        if await _touchless_match_satisfied(
            session,
            invoice,
            validation_results,
            match_mode=match_mode,
            resolved_tier=resolved_tier,
        ):
            return False
        await _hold_for_approval(
            session,
            invoice,
            definition=definition,
            reason="match_not_clean",
            extra_detail={"match_mode": match_mode},
        )
        return True

    if invoice.route_target == ROUTE_TEAM:
        return False

    return False
