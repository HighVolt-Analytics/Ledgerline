"""Approvals kanban column bucketing (Review / Processing / Approved / Rejected)."""

from __future__ import annotations

from typing import Literal

from sqlalchemy import and_, case, func, or_

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
    from app.services.invoice.invoice_response_service import _extracted_fields_if_loaded

    fields = _extracted_fields_if_loaded(inv)
    return bool(fields.get("vision_bundle_kind") or fields.get("vision_bundle_key"))


def is_understood_path_complete(inv: Invoice) -> bool:
    """True when vision understood path finished (vaulted) — show under Approved."""
    return is_understood_path_vault_terminal(inv)


def is_understood_path_vault_terminal(inv: Invoice) -> bool:
    """True when understood path ended at vault — no posting from Approvals."""
    token = (inv.evaluation_status or "").strip().lower()
    if token in UNDERSTOOD_PATH_COMPLETE_EVAL:
        return True
    # Legacy rows: awaiting_classification + soft-bundle snapshot = vaulted.
    if token == _LEGACY_UNDERSTOOD_EVAL and _has_vision_bundle_snapshot(inv):
        return True
    return False


def is_understood_path_not_approvable(inv: Invoice) -> bool:
    """True when Confirm must not resume posting (vault-terminal holds only)."""
    return is_understood_path_vault_terminal(inv)


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
        if is_classification_confirmed(inv):
            return "processing"
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


def approval_board_column_expr():
    """SQL CASE matching approval_board_column() (without extracted-field legacy)."""
    eval_l = func.lower(func.coalesce(Invoice.evaluation_status, ""))
    classified = and_(
        Invoice.document_type_code.isnot(None),
        func.trim(Invoice.document_type_code) != "",
    )
    rejected = Invoice.status.in_(tuple(REJECTED_STATUSES))
    processed = Invoice.status == InvoiceStatus.PROCESSED
    vaulted = eval_l == EVAL_VISION_VAULTED
    header = eval_l == EVAL_VISION_HEADER_REVIEW
    pre_class = eval_l.in_(
        (
            EvaluationStatus.AWAITING_CLASSIFICATION.value,
            EvaluationStatus.NEEDS_RESCAN.value,
        )
    )
    pipeline = Invoice.status.in_(tuple(PIPELINE_STATUSES))
    pending_appr = eval_l == EvaluationStatus.PENDING_APPROVAL.value
    exception = Invoice.status == InvoiceStatus.EXCEPTION
    return case(
        (rejected, "rejected"),
        (processed, "approved"),
        (vaulted, "approved"),
        (and_(header, classified), "processing"),
        (header, "review"),
        (pre_class, "review"),
        (and_(exception, ~classified), "review"),
        (pipeline, "processing"),
        (and_(exception, or_(classified, pending_appr)), "processing"),
        else_="review",
    )


def apply_approval_board_column(query, column: str | None):
    valid = {"review", "processing", "approved", "rejected"}
    tokens = [
        part.strip().lower()
        for part in (column or "").split(",")
        if part.strip()
    ]
    tokens = [token for token in tokens if token in valid]
    if not tokens or set(tokens) == valid:
        return query
    expr = approval_board_column_expr()
    if len(tokens) == 1:
        return query.where(expr == tokens[0])
    return query.where(expr.in_(tokens))
