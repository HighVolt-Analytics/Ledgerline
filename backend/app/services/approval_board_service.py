"""Approvals kanban column bucketing (Review / Processing / Approved / Rejected)."""

from __future__ import annotations

from typing import Literal

from app.models.invoice import Invoice, InvoiceStatus
from app.schemas.invoice import EvaluationStatus

ApprovalBoardColumn = Literal["review", "processing", "approved", "rejected"]

REJECTED_STATUSES = frozenset(
    {InvoiceStatus.REJECTED, InvoiceStatus.DUPLICATE_SKIPPED}
)

PIPELINE_STATUSES = frozenset(
    {
        InvoiceStatus.PENDING,
        InvoiceStatus.PARSING,
        InvoiceStatus.VALIDATING,
        InvoiceStatus.MAPPING,
        InvoiceStatus.JOURNALING,
        InvoiceStatus.RECONCILING,
    }
)

PRE_CLASSIFICATION_EVAL = frozenset(
    {
        EvaluationStatus.AWAITING_CLASSIFICATION,
        EvaluationStatus.NEEDS_RESCAN,
    }
)


def is_classification_confirmed(inv: Invoice) -> bool:
    return bool((inv.document_type_code or "").strip())


def _parse_eval(raw: str | None) -> EvaluationStatus | None:
    if not raw:
        return None
    token = raw.strip().lower()
    for member in EvaluationStatus:
        if member.value == token:
            return member
    return None


def approval_board_column(inv: Invoice) -> ApprovalBoardColumn:
    """
    Map invoice state to kanban column.

    Review: pre-classification failure or block.
    Processing: classified, not yet approved (pipeline or post-classify exception).
    """
    status = inv.status
    if status in REJECTED_STATUSES:
        return "rejected"
    if status == InvoiceStatus.PROCESSED:
        return "approved"

    eval_status = _parse_eval(inv.evaluation_status)
    if eval_status in PRE_CLASSIFICATION_EVAL:
        return "review"

    if status == InvoiceStatus.EXCEPTION and not is_classification_confirmed(inv):
        return "review"

    if status in PIPELINE_STATUSES:
        return "processing"

    if status == InvoiceStatus.EXCEPTION and is_classification_confirmed(inv):
        return "processing"

    return "review"
