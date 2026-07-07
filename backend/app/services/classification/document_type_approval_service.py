"""Document-type approval gate after validation (before mapping / journaling)."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import Invoice, InvoiceStatus
from app.schemas.document_type import DocumentTypeDefinition
from app.services.audit.audit_service import log_event
from app.services.classification.document_type_playbook_profile_service import (
    effective_approval_policy,
    effective_match_policy,
    match_mode_requires_po,
    match_mode_requires_sales,
)
from app.services.classification.document_type_match_service import is_clean_match_message
from app.services.invoice.invoice_evaluation_service import EVAL_PENDING_APPROVAL, ROUTE_TEAM
from app.services.invoice.processing_cycle_service import latest_audit_detail_after_cycle_reset
from app.services.purchase.purchase_match_service import compute_three_way_match
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
    from app.services.invoice.processing_cycle_service import (
        has_audit_event_after_cycle_reset,
    )

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
    vr15 = _validation_result_map(results).get("VR15")
    if vr15 is None or not vr15.passed:
        return False
    return is_clean_match_message(vr15.message or "", match_mode=match_mode)


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


async def _touchless_match_satisfied(
    session: AsyncSession,
    invoice: Invoice,
    validation_results: list[ValidationResult],
    *,
    match_mode: str,
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
        if ctx.effective_mode == "three_way_po_grn" and ctx.po is not None:
            match = compute_three_way_match(ctx.po, invoice)
            if match.status == "3-Way Match" or ctx.po.variance_approved:
                return True
        elif ctx.effective_mode == "two_way_po_ses" and ctx.po is not None:
            from app.services.classification.document_type_match_service import compute_two_way_po_match

            outcome = compute_two_way_po_match(ctx.po, invoice)
            if outcome.passed or ctx.po.variance_approved:
                return True
        elif ctx.effective_mode == "two_way_grn_invoice" and ctx.grn_invoice is not None:
            from app.services.purchase.purchase_match_service import _load_grn_invoice_qty

            grn_qty = await _load_grn_invoice_qty(session, ctx.grn_invoice)
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
        if ctx.effective_mode == "three_way_so_dn" and ctx.so is not None:
            match = compute_sales_three_way_match(ctx.so, invoice)
            if match.status == "3-Way Match" or ctx.so.variance_approved:
                return True
        elif ctx.effective_mode == "two_way_so_invoice" and ctx.so is not None:
            match = compute_two_way_so_match(ctx.so, invoice)
            if match.status == "2-Way Match" or ctx.so.variance_approved:
                return True
        elif ctx.effective_mode == "two_way_dn_invoice" and ctx.dn_invoice is not None:
            from app.services.sales.sales_match_service import _load_dn_invoice_qty

            dn_qty, dn_uom = await _load_dn_invoice_qty(session, ctx.dn_invoice)
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
    extra_detail: dict[str, object] | None = None,
) -> None:
    invoice.status = InvoiceStatus.EXCEPTION
    invoice.evaluation_status = EVAL_PENDING_APPROVAL
    detail: dict[str, object] = {
        "reason": reason,
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

    if mode == "variance_workflow":
        match_mode = effective_match_policy(definition).mode
        if not match_mode_requires_po(match_mode):
            return False
        vr15 = _validation_result_map(validation_results).get("VR15")
        if vr15 is not None and vr15.passed:
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

    match_mode = effective_match_policy(definition).mode

    if mode in {"full_doa", "never_touchless", "supervisor_on_exception"}:
        if mode == "supervisor_on_exception" and await _touchless_match_satisfied(
            session,
            invoice,
            validation_results,
            match_mode=match_mode,
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
