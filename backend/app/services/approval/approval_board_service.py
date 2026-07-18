"""Approvals kanban column bucketing (Review / Processing / Approved / Rejected)."""

from __future__ import annotations

from typing import Literal

from app.models.invoice import Invoice, InvoiceStatus
from app.schemas.invoice import EvaluationStatus
from app.services.invoice.invoice_evaluation_service import (
    EVAL_VISION_HEADER_REVIEW,
    EVAL_VISION_VAULTED,
)

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

# Vision understood path — finished at vault (not OCR Approvals Confirm).
UNDERSTOOD_PATH_COMPLETE_EVAL = frozenset({EVAL_VISION_VAULTED})
UNDERSTOOD_PATH_REVIEW_EVAL = frozenset({EVAL_VISION_HEADER_REVIEW})
# Legacy tag written before vision_* evals existed.
_LEGACY_UNDERSTOOD_EVAL = "awaiting_classification"


def is_classification_confirmed(inv: Invoice) -> bool:
    return bool((inv.document_type_code or "").strip())


def is_pending_approval(inv: Invoice) -> bool:
    return (inv.evaluation_status or "").strip().lower() == EvaluationStatus.PENDING_APPROVAL.value


def _has_vision_bundle_snapshot(inv: Invoice) -> bool:
    fields = inv.extracted_fields if isinstance(inv.extracted_fields, dict) else {}
    return bool(fields.get("vision_bundle_kind") or fields.get("vision_bundle_key"))


def is_understood_path_complete(inv: Invoice) -> bool:
    """True when vision understood path finished (vaulted) — show under Approved."""
    token = (inv.evaluation_status or "").strip().lower()
    if token in UNDERSTOOD_PATH_COMPLETE_EVAL:
        return True
    # Legacy rows: awaiting_classification + soft-bundle snapshot = vaulted.
    if token == _LEGACY_UNDERSTOOD_EVAL and _has_vision_bundle_snapshot(inv):
        return True
    return False


def is_understood_path_not_approvable(inv: Invoice) -> bool:
    """True when Confirm must not re-queue into the OCR/posting pipeline."""
    token = (inv.evaluation_status or "").strip().lower()
    if token in UNDERSTOOD_PATH_COMPLETE_EVAL | UNDERSTOOD_PATH_REVIEW_EVAL:
        return True
    if token == _LEGACY_UNDERSTOOD_EVAL and _has_vision_bundle_snapshot(inv):
        return True
    return False


# Back-compat alias used by approve gate.
def is_understood_path_excluded_from_approvals(inv: Invoice) -> bool:
    return is_understood_path_not_approvable(inv)


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

    Review: pre-classification failure or block (incl. vision header review).
    Processing: classified, not yet approved (pipeline or post-classify exception).
    Approved: ledger-posted, or vision understood path finished at vault.
    """
    status = inv.status
    if status in REJECTED_STATUSES:
        return "rejected"
    if status == InvoiceStatus.PROCESSED:
        return "approved"

    eval_token = (inv.evaluation_status or "").strip().lower()
    if is_understood_path_complete(inv):
        return "approved"
    if eval_token in UNDERSTOOD_PATH_REVIEW_EVAL:
        return "review"

    eval_status = _parse_eval(inv.evaluation_status)
    if eval_status in PRE_CLASSIFICATION_EVAL:
        return "review"

    if status == InvoiceStatus.EXCEPTION and not is_classification_confirmed(inv):
        return "review"

    if status in PIPELINE_STATUSES:
        return "processing"

    if status == InvoiceStatus.EXCEPTION and (
        is_classification_confirmed(inv) or is_pending_approval(inv)
    ):
        return "processing"

    return "review"
