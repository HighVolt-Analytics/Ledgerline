"""Document-type approval gate after validation (before mapping / journaling)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog
from app.models.invoice import Invoice, InvoiceStatus
from app.schemas.document_type import DocumentTypeDefinition
from app.services.audit_service import log_event
from app.services.document_type_playbook_profile_service import (
    effective_approval_policy,
    effective_match_policy,
    match_mode_requires_po,
)
from app.services.invoice_evaluation_service import EVAL_NEEDS_REVIEW, ROUTE_TEAM
from app.services.purchase_match_service import compute_three_way_match, load_purchase_order_for_invoice
from app.services.validator import ValidationResult


async def has_document_approval(session: AsyncSession, invoice_id: int) -> bool:
    row = (
        await session.execute(
            select(AuditLog.id)
            .where(
                AuditLog.invoice_id == invoice_id,
                AuditLog.event == "invoice_approved",
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    return row is not None


def _validation_result_map(results: list[ValidationResult]) -> dict[str, ValidationResult]:
    return {row.rule: row for row in results}


def _match_is_clean_for_touchless(
    results: list[ValidationResult],
    *,
    match_mode: str,
) -> bool:
    if not match_mode_requires_po(match_mode):
        return True
    vr15 = _validation_result_map(results).get("VR15")
    if vr15 is None or not vr15.passed:
        return False
    message = (vr15.message or "").strip().lower()
    return "3-way match" in message or message in {"full_match", "matched"}


async def apply_document_type_approval_gate(
    session: AsyncSession,
    invoice: Invoice,
    *,
    definition: DocumentTypeDefinition | None,
    validation_results: list[ValidationResult],
) -> bool:
    """
    Hold invoice for manual approval when the document-type policy requires it.

    Returns True when the invoice is held (status set to exception).
    """
    if definition is None:
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
        invoice.status = InvoiceStatus.EXCEPTION
        invoice.evaluation_status = EVAL_NEEDS_REVIEW
        await log_event(
            session,
            "approval_required",
            invoice_id=invoice.id,
            detail={
                "reason": "purchase_variance_pending",
                "document_type_code": definition.code,
                "approval_mode": mode,
            },
        )
        return True

    if mode in {"full_doa", "never_touchless", "supervisor_on_exception"}:
        if await has_document_approval(session, invoice.id):
            return False
        if mode == "supervisor_on_exception" and _match_is_clean_for_touchless(
            validation_results,
            match_mode=effective_match_policy(definition).mode,
        ):
            return False
        invoice.status = InvoiceStatus.EXCEPTION
        invoice.evaluation_status = EVAL_NEEDS_REVIEW
        await log_event(
            session,
            "approval_required",
            invoice_id=invoice.id,
            detail={
                "reason": mode,
                "document_type_code": definition.code,
                "approval_mode": mode,
            },
        )
        return True

    if mode == "touchless_on_clean_match":
        match_mode = effective_match_policy(definition).mode
        if not match_mode_requires_po(match_mode):
            return False
        if _match_is_clean_for_touchless(validation_results, match_mode=match_mode):
            return False
        po = await load_purchase_order_for_invoice(session, invoice)
        if po is not None:
            match = compute_three_way_match(po, invoice)
            if match.status == "3-Way Match" or po.variance_approved:
                return False
        invoice.status = InvoiceStatus.EXCEPTION
        invoice.evaluation_status = EVAL_NEEDS_REVIEW
        await log_event(
            session,
            "approval_required",
            invoice_id=invoice.id,
            detail={
                "reason": "match_not_clean",
                "document_type_code": definition.code,
                "approval_mode": mode,
                "match_mode": match_mode,
            },
        )
        return True

    if invoice.route_target == ROUTE_TEAM:
        return False

    return False
