"""Document matrix — flags, payment readiness, and stage metadata."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import Invoice, InvoiceStatus
from app.models.payment import Payment, PaymentStatus
from app.schemas.matrix_api import MatrixListRequest
from app.schemas.pipeline import MatrixConflictRow, MatrixRowResponse
from app.services.approval.approval_board_service import (
    apply_approval_board_column,
    approval_board_column_expr,
)
from app.services.invoice.invoice_related_query_service import (
    audit_logs_for_invoice_ids,
    payments_for_invoice_ids,
)
from app.services.invoice.invoice_response_service import (
    invoice_list_load_options,
    invoice_to_response,
)
from app.services.invoice.pipeline_stages import build_matrix_cells, exception_hold_reason
from app.services.invoice.invoice_evaluation_service import load_posting_config_for_tenant
from app.services.invoice.processing_cycle_service import CYCLE_RESET_EVENTS
from app.services.integration.publish_service import published_invoice_ids

# Stage-relevant audit only. Newest-N of *all* events was mostly OCR/noise.
_MATRIX_AUDIT_PER_INVOICE = 24
_MATRIX_LIST_AUDIT_EVENTS: frozenset[str] = frozenset(
    {
        "email_ingested",
        "invoice_uploaded",
        "invoice_file_attached",
        "parse_completed",
        "invoice_parsed",
        "parsing_failed",
        "validation_passed",
        "validation_failed",
        "validation_bypassed_after_human_approval",
        "mapping_applied",
        "invoice_approved",
        "approval_required",
        "approval_requested",
        "invoice_published_to_ledger",
        "invoice_processed",
        "vault_stored",
        "purchase_document_processed",
        "sales_document_processed",
        "supporting_document_processed",
        "vendor_registration_hold",
        "customer_registration_hold",
        "storage_verified",
        "file_validity_passed",
        "file_validity_failed",
        "vision_understand_passed",
        "vision_understand_failed",
        "vision_header_extracted",
        "vision_header_extract_failed",
        "vision_type_suggested",
        "vision_type_suggest_failed",
        "vision_dt_fields_extracted",
        "vision_dt_fields_extract_failed",
        "vision_path_pending",
        "image_quality_passed",
        "image_quality_failed",
        "image_quality_gate_passed",
        "image_quality_gate_failed",
        "layout_readiness_evaluated",
        "ocr_completed",
        "ocr_quality_confirm_passed",
        "ocr_quality_confirm_failed",
        "llm_classified",
        "classification_gate_passed",
        "classification_gate_failed",
        "classification_resolved",
        "vision_document_type_mapped",
        "vision_bundle_linked",
        "vision_bundle_standalone",
        "blob_relocated",
        "vault_layout_sync_skipped",
        "vision_posting_continued",
        "vision_posting_skipped",
        "three_way_match_evaluated",
        "match_phase_evaluated",
        "three_way_match_variance_unapproved",
        "purchase_variance_approved",
        "sales_variance_approved",
        "journal_unbalanced",
        "journal_control_account_unresolved",
        "reconciliation_halted",
        "reconciliation_skipped",
        "invoice_rejected",
        "duplicate_in_progress",
        "duplicate_skipped",
        "mapping_review_required",
        "routing_review_required",
        *CYCLE_RESET_EVENTS,
    }
)


def _parse_validation_results(raw: str | list | None) -> list[dict[str, Any]]:
    from app.services.rule_book.validator import normalize_stored_validation_results

    if not raw:
        return []
    if isinstance(raw, list):
        return normalize_stored_validation_results(raw)
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return []
    if not isinstance(parsed, list):
        return []
    return normalize_stored_validation_results(parsed)


def _first_validation_failure(inv: Invoice) -> str | None:
    for rule in _parse_validation_results(inv.validation_results):
        if rule.get("skipped"):
            continue
        if not rule.get("passed"):
            message = str(rule.get("message", "")).strip()
            if message:
                return message
            rule_id = str(rule.get("rule", "")).strip()
            return f"Validation rule {rule_id} failed" if rule_id else "Validation failed"
    return None


def derive_matrix_flag(
    inv: Invoice, document_types: list | None = None
) -> tuple[str, str | None]:
    """Return matrix flag label and optional human-readable reason."""
    if inv.status == InvoiceStatus.DUPLICATE_SKIPPED:
        return "Duplicate Suspected", _first_validation_failure(inv) or "Duplicate document skipped"
    if inv.status == InvoiceStatus.REJECTED:
        return "Quarantined", "Invoice rejected and quarantined"
    if inv.status == InvoiceStatus.EXCEPTION:
        eval_status = (inv.evaluation_status or "").strip().lower()
        if eval_status == "pending_approval":
            return "Awaiting approval", "Document-type policy requires approver sign-off"
        if eval_status in {"awaiting_po", "awaiting_so"}:
            label = "Awaiting PO linkage" if eval_status == "awaiting_po" else "Awaiting SO linkage"
            return "Awaiting linkage", label
        if eval_status == "vision_vaulted":
            return "Clean", "Understood path — bundled and stored in vault"
        if eval_status == "vision_header_review":
            return (
                "Anomaly Detected",
                exception_hold_reason(inv, document_types=document_types),
            )
        return "Anomaly Detected", exception_hold_reason(inv, document_types=document_types)
    if inv.evaluation_status == "needs_rescan":
        return "Anomaly Detected", "Poor image quality — rescan required"
    if inv.evaluation_status == "awaiting_classification":
        from app.services.invoice.invoice_response_service import _extracted_fields_if_loaded

        fields = _extracted_fields_if_loaded(inv)
        if fields.get("vision_bundle_kind") is not None or fields.get("vision_bundle_key"):
            return "Clean", "Understood path — bundled and stored in vault"
        return "Anomaly Detected", "Document type not classified — review required"
    if inv.evaluation_status == "pending_vendor":
        return "Anomaly Detected", "Vendor could not be matched confidently"
    if inv.evaluation_status == "unmatched_expense_vendor":
        if inv.status == InvoiceStatus.PROCESSED:
            return "Clean", None
        return "Anomaly Detected", "Unknown expense vendor under registration threshold"
    if inv.evaluation_status == "needs_review":
        route = (inv.route_target or "").strip()
        # Vault is storage-only; routing review is not an actionable anomaly.
        if route == "Vault":
            return "Clean", None
        return "Anomaly Detected", f"Rule book routing needs review ({route or 'review'})"
    failure = _first_validation_failure(inv)
    if failure:
        return "Anomaly Detected", failure
    from app.services.classification.document_type_playbook_profile_service import (
        gl_posting_applicable_for_invoice,
    )

    if not gl_posting_applicable_for_invoice(inv):
        return "Clean", None
    account = (inv.account_name or "").lower()
    if "suspense" in account:
        return "Anomaly Detected", "GL mapping unresolved — routed to suspense"
    return "Clean", None


def derive_matrix_payment_status(inv: Invoice, payment: Payment | None) -> str:
    """Map invoice + payment row to matrix payment badge label."""
    if payment is not None:
        if payment.status == PaymentStatus.PAID:
            return "Paid"
        if payment.status == PaymentStatus.FAILED:
            return "Failed"
        if payment.status == PaymentStatus.AWAITING:
            approvers = payment.approvers or []
            if approvers and all(a.get("state") == "approved" for a in approvers):
                return "Payment Approved"
            return "Awaiting Payment"
        if payment.status in (PaymentStatus.QUEUE, PaymentStatus.SCHEDULED):
            return "Awaiting Payment"

    if inv.status in (
        InvoiceStatus.EXCEPTION,
        InvoiceStatus.DUPLICATE_SKIPPED,
        InvoiceStatus.REJECTED,
    ):
        return "On Hold"
    if inv.evaluation_status in (
        "needs_review",
        "pending_vendor",
        "unmatched_expense_vendor",
        "awaiting_classification",
        "vision_header_review",
        "needs_rescan",
    ):
        if inv.status != InvoiceStatus.PROCESSED:
            return "On Hold"
    if inv.evaluation_status in ("pending_approval", "awaiting_po", "awaiting_so"):
        if inv.status != InvoiceStatus.PROCESSED:
            return "On Hold"
    if inv.status == InvoiceStatus.PROCESSED and inv.due_date is not None:
        return "Awaiting Payment"
    return "—"


AUTH_NA = "—"
AUTH_DONE = "Done"
AUTH_PENDING = "Pending"
AUTH_FAILED = "Failed"
SYNC_NA = "—"
SYNC_SYNCED = "Synced"
SYNC_FAILED = "Failed"
SYNC_PENDING = "Pending"


def _parse_validation_rows(inv: Invoice) -> list[dict[str, Any]]:
    raw = getattr(inv, "validation_results", None)
    if not raw:
        return []
    if isinstance(raw, list):
        return [row for row in raw if isinstance(row, dict)]
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    if not isinstance(parsed, list):
        return []
    return [row for row in parsed if isinstance(row, dict)]


def _vr_te08_row(inv: Invoice) -> dict[str, Any] | None:
    for row in _parse_validation_rows(inv):
        if row.get("rule") == "VR-TE08":
            return row
    return None


def derive_matrix_advance_auth(
    inv: Invoice,
    *,
    document_types: list | None = None,
) -> str:
    """Advance Auth for All Documents Detailed — TE / advance paths only."""
    from app.schemas.rule_book_config import (
        TEAM_EXPENSE_KIND_ADVANCE,
        normalize_team_expense_kind,
    )
    from app.services.invoice.invoice_evaluation_service import ROUTE_TEAM
    from app.services.purchase.team_expense_validator import document_type_spend_controls
    from app.schemas.rule_book_config import RuleBookConfigPayload

    if (inv.route_target or "").strip() != ROUTE_TEAM:
        return AUTH_NA

    config = RuleBookConfigPayload(document_types=list(document_types or []))
    _budget_control, advance_control = document_type_spend_controls(
        config, inv.document_type_code
    )
    kind = normalize_team_expense_kind(getattr(inv, "team_expense_kind", None))
    advance_related = kind == TEAM_EXPENSE_KIND_ADVANCE
    if not advance_control and not advance_related:
        return AUTH_NA

    if inv.status == InvoiceStatus.REJECTED:
        return AUTH_FAILED
    eval_status = (inv.evaluation_status or "").strip().lower()
    if eval_status == "pending_approval":
        return AUTH_PENDING
    if inv.status == InvoiceStatus.EXCEPTION and eval_status in {
        "needs_review",
        "pending_vendor",
        "unmatched_expense_vendor",
    }:
        return AUTH_FAILED
    if inv.status == InvoiceStatus.PROCESSED:
        return AUTH_DONE
    if inv.status in (
        InvoiceStatus.PENDING,
        InvoiceStatus.PARSING,
        InvoiceStatus.VALIDATING,
        InvoiceStatus.MAPPING,
        InvoiceStatus.JOURNALING,
        InvoiceStatus.RECONCILING,
    ):
        return AUTH_PENDING
    return AUTH_PENDING


def derive_matrix_budget_auth(
    inv: Invoice,
    *,
    document_types: list | None = None,
) -> str:
    """Budget Auth from DT budget_control + VR-TE08 validation outcome."""
    from app.schemas.rule_book_config import RuleBookConfigPayload
    from app.services.invoice.invoice_evaluation_service import ROUTE_TEAM
    from app.services.purchase.team_expense_approval import has_soft_budget_overrun
    from app.services.purchase.team_expense_validator import document_type_spend_controls

    if (inv.route_target or "").strip() != ROUTE_TEAM:
        return AUTH_NA

    config = RuleBookConfigPayload(document_types=list(document_types or []))
    budget_control, _advance_control = document_type_spend_controls(
        config, inv.document_type_code
    )
    if not budget_control:
        return AUTH_NA

    te08 = _vr_te08_row(inv)
    if te08 is None:
        # Not validated yet or TE08 never ran.
        if inv.status in (
            InvoiceStatus.PENDING,
            InvoiceStatus.PARSING,
            InvoiceStatus.VALIDATING,
        ):
            return AUTH_PENDING
        return AUTH_NA
    if te08.get("skipped"):
        return AUTH_NA
    if not te08.get("passed"):
        severity = (te08.get("severity") or "block").strip().lower()
        if severity == "warn" or has_soft_budget_overrun(inv):
            eval_status = (inv.evaluation_status or "").strip().lower()
            if inv.status == InvoiceStatus.PROCESSED:
                return AUTH_DONE
            if eval_status == "pending_approval" or inv.status == InvoiceStatus.EXCEPTION:
                return AUTH_PENDING
            return AUTH_PENDING
        return AUTH_FAILED
    return AUTH_DONE


def derive_matrix_acc_sync(
    inv: Invoice,
    *,
    ledger_status: str | None,
    ref_status: str | None,
    document_types: list | None = None,
) -> str:
    """Accounting sync (Xero export) status for the matrix Acc Sync column."""
    from app.models.accounting_export_ledger import (
        STATUS_FAILED_TERMINAL,
        STATUS_HUMAN_REVIEW,
        STATUS_IN_FLIGHT,
        STATUS_READY,
        STATUS_RETRY_PENDING,
        STATUS_SUCCESS,
    )
    from app.services.classification.document_type_playbook_profile_service import (
        gl_posting_applicable_for_invoice,
    )

    if not gl_posting_applicable_for_invoice(inv, document_types=document_types):
        return SYNC_NA

    status = (ledger_status or "").strip().upper()
    if status == STATUS_SUCCESS:
        return SYNC_SYNCED
    if status in {STATUS_FAILED_TERMINAL, STATUS_HUMAN_REVIEW}:
        return SYNC_FAILED
    if status in {STATUS_READY, STATUS_IN_FLIGHT, STATUS_RETRY_PENDING}:
        return SYNC_PENDING

    ref = (ref_status or "").strip().lower()
    if ref in {"synced", "success"}:
        return SYNC_SYNCED
    if ref in {"failed", "error"}:
        return SYNC_FAILED
    if ref in {"pushing", "pending", "queued"}:
        return SYNC_PENDING
    return SYNC_PENDING


async def line_item_counts_for_invoice_ids(
    db: AsyncSession,
    invoice_ids: list[int],
) -> dict[int, int]:
    if not invoice_ids:
        return {}
    from app.models.line_item import LineItem

    rows = (
        await db.execute(
            select(LineItem.invoice_id, func.count(LineItem.id))
            .where(LineItem.invoice_id.in_(invoice_ids))
            .group_by(LineItem.invoice_id)
        )
    ).all()
    return {int(invoice_id): int(count) for invoice_id, count in rows}


async def accounting_sync_status_for_invoice_ids(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    invoice_ids: list[int],
) -> tuple[dict[int, str], dict[int, str]]:
    """Return (ledger_status_by_id, ref_status_by_id) for Acc Sync enrichment."""
    ledger_by_id: dict[int, str] = {}
    ref_by_id: dict[int, str] = {}
    if not invoice_ids:
        return ledger_by_id, ref_by_id

    from app.models.accounting_export_ledger import AccountingExportLedger, PROVIDER_XERO
    from app.models.external_accounting_ref import ExternalAccountingRef

    ledger_rows = (
        await db.execute(
            select(AccountingExportLedger)
            .where(
                AccountingExportLedger.tenant_id == tenant_id,
                AccountingExportLedger.provider == PROVIDER_XERO,
                AccountingExportLedger.source_invoice_id.in_(invoice_ids),
            )
            .order_by(
                AccountingExportLedger.source_invoice_id.asc(),
                AccountingExportLedger.id.desc(),
            )
        )
    ).scalars().all()
    for row in ledger_rows:
        iid = int(row.source_invoice_id)
        if iid not in ledger_by_id:
            ledger_by_id[iid] = row.status or ""

    id_tokens = [str(i) for i in invoice_ids]
    ref_rows = (
        await db.execute(
            select(ExternalAccountingRef).where(
                ExternalAccountingRef.tenant_id == tenant_id,
                ExternalAccountingRef.provider == PROVIDER_XERO,
                ExternalAccountingRef.entity_type == "invoice",
                ExternalAccountingRef.internal_entity_id.in_(id_tokens),
            )
        )
    ).scalars().all()
    for ref in ref_rows:
        try:
            iid = int(ref.internal_entity_id)
        except (TypeError, ValueError):
            continue
        if iid not in ref_by_id:
            ref_by_id[iid] = (ref.sync_status or "") if hasattr(ref, "sync_status") else ""
    return ledger_by_id, ref_by_id


from app.services.dossier.document_ref_service import display_document_ref


def _document_ref(invoice: Invoice) -> str:
    return display_document_ref(invoice)


def _conflict_detail(inv: Invoice, other: Invoice) -> list[MatrixConflictRow]:
    return [
        MatrixConflictRow(
            field="Vendor",
            this_doc=(inv.vendor or "—").strip() or "—",
            other_doc=(other.vendor or "—").strip() or "—",
        ),
        MatrixConflictRow(
            field="Invoice number",
            this_doc=(inv.invoice_no or "—").strip() or "—",
            other_doc=(other.invoice_no or "—").strip() or "—",
        ),
        MatrixConflictRow(
            field="Total",
            this_doc=str(inv.total or "—"),
            other_doc=str(other.total or "—"),
        ),
        MatrixConflictRow(
            field="Status",
            this_doc=inv.status.value if inv.status else "—",
            other_doc=other.status.value if other.status else "—",
        ),
    ]


_PIPELINE_STATUSES = (
    InvoiceStatus.PENDING,
    InvoiceStatus.PARSING,
    InvoiceStatus.VALIDATING,
    InvoiceStatus.MAPPING,
    InvoiceStatus.JOURNALING,
    InvoiceStatus.RECONCILING,
)

_FLAGGED_EVAL = (
    "needs_review",
    "pending_vendor",
    "awaiting_classification",
    "vision_header_review",
    "needs_rescan",
    "unmatched_expense_vendor",
    "pending_approval",
    "awaiting_po",
    "awaiting_so",
)


def _apply_route_target(query, route_target: str | None):
    tokens = parse_route_target_filter(route_target)
    if not tokens:
        return query
    if len(tokens) == 1:
        return query.where(Invoice.route_target == tokens[0])
    return query.where(Invoice.route_target.in_(tokens))


def _apply_capture_source(query, capture_source: str | None):
    if not capture_source or not capture_source.strip():
        return query
    src = capture_source.strip().lower()
    if src in {"app", "mobile", "mob"}:
        src = "app"
    if src not in {"upload", "email", "whatsapp", "viber", "slack", "app"}:
        return query
    unset_capture = or_(Invoice.capture_source.is_(None), Invoice.capture_source == "")
    if src == "upload":
        return query.where(
            or_(
                func.lower(Invoice.capture_source) == "upload",
                and_(
                    unset_capture,
                    Invoice.connected_mailbox_id.is_(None),
                    Invoice.whatsapp_connection_id.is_(None),
                    Invoice.viber_connection_id.is_(None),
                    Invoice.slack_connection_id.is_(None),
                ),
            )
        )
    if src == "email":
        return query.where(
            or_(
                func.lower(Invoice.capture_source) == "email",
                and_(unset_capture, Invoice.connected_mailbox_id.isnot(None)),
            )
        )
    if src == "whatsapp":
        return query.where(
            or_(
                func.lower(Invoice.capture_source) == "whatsapp",
                and_(unset_capture, Invoice.whatsapp_connection_id.isnot(None)),
            )
        )
    if src == "slack":
        return query.where(
            or_(
                func.lower(Invoice.capture_source) == "slack",
                and_(unset_capture, Invoice.slack_connection_id.isnot(None)),
            )
        )
    if src == "app":
        return query.where(func.lower(Invoice.capture_source).in_(("app", "mobile", "mob")))
    return query.where(
        or_(
            func.lower(Invoice.capture_source) == "viber",
            and_(unset_capture, Invoice.viber_connection_id.isnot(None)),
        )
    )


def _apply_search(query, q: str | None):
    if not q or not q.strip():
        return query
    term = f"%{q.strip()}%"
    clauses = [
        Invoice.vendor.ilike(term),
        Invoice.invoice_no.ilike(term),
        Invoice.po_reference.ilike(term),
        Invoice.document_ref.ilike(term),
        Invoice.route_target.ilike(term),
    ]
    raw = q.strip()
    if raw.isdigit():
        clauses.append(Invoice.id == int(raw))
    return query.where(or_(*clauses))


def _duplicate_notification_predicate():
    """Hard skips + weak T4 review suggestions — Upload notifications queue."""
    return or_(
        Invoice.status == InvoiceStatus.DUPLICATE_SKIPPED,
        Invoice.duplicate_review_suggested.is_(True),
    )


def _apply_matrix_filter(query, matrix_filter: str | None, *, tenant_id: uuid.UUID):
    token = (matrix_filter or "all").strip().lower()
    if token in {"", "all"}:
        return query
    if token == "duplicates":
        return query.where(_duplicate_notification_predicate())
    if token in {"exclude_duplicates", "no_duplicates"}:
        return query.where(~_duplicate_notification_predicate())
    if token == "anomalies":
        return query.where(
            or_(
                Invoice.status.in_(
                    (
                        InvoiceStatus.EXCEPTION,
                        InvoiceStatus.DUPLICATE_SKIPPED,
                        InvoiceStatus.REJECTED,
                    )
                ),
                and_(
                    Invoice.evaluation_status.in_(_FLAGGED_EVAL),
                    Invoice.status != InvoiceStatus.PROCESSED,
                ),
            )
        )
    if token == "pending":
        return query.where(Invoice.status.in_(_PIPELINE_STATUSES))
    if token == "failed":
        return query.where(
            Invoice.status.in_((InvoiceStatus.EXCEPTION, InvoiceStatus.REJECTED))
        )
    if token == "awaiting":
        pay_ids = (
            select(Payment.invoice_id).where(
                Payment.tenant_id == tenant_id,
                Payment.invoice_id.isnot(None),
                Payment.status.in_(
                    (PaymentStatus.AWAITING, PaymentStatus.QUEUE, PaymentStatus.SCHEDULED)
                ),
            )
        )
        return query.where(
            or_(
                Invoice.id.in_(pay_ids),
                and_(
                    Invoice.status == InvoiceStatus.PROCESSED,
                    Invoice.due_date.isnot(None),
                ),
            )
        )
    if token == "paid":
        today = func.current_date()
        paid_ids = (
            select(Payment.invoice_id).where(
                Payment.tenant_id == tenant_id,
                Payment.invoice_id.isnot(None),
                Payment.status == PaymentStatus.PAID,
                Payment.paid_date.isnot(None),
                func.extract("year", Payment.paid_date) == func.extract("year", today),
                func.extract("month", Payment.paid_date) == func.extract("month", today),
            )
        )
        return query.where(Invoice.id.in_(paid_ids))
    return query


async def duplicate_conflict_for_invoice(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    inv: Invoice,
) -> tuple[str | None, list[MatrixConflictRow]]:
    mapping = await duplicate_conflicts_for_invoices(db, tenant_id, [inv])
    return mapping.get(inv.id, (None, []))


async def duplicate_conflicts_for_invoices(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    invoices: list[Invoice],
) -> dict[int, tuple[str | None, list[MatrixConflictRow]]]:
    """Batch duplicate-conflict lookups for a matrix page."""
    out: dict[int, tuple[str | None, list[MatrixConflictRow]]] = {
        inv.id: (None, []) for inv in invoices
    }
    dupes = [inv for inv in invoices if inv.status == InvoiceStatus.DUPLICATE_SKIPPED]
    if not dupes:
        return out

    from app.models.audit import AuditLog

    dupe_ids = [inv.id for inv in dupes]
    audit_rows = (
        await db.execute(
            select(AuditLog)
            .where(
                AuditLog.invoice_id.in_(dupe_ids),
                AuditLog.event == "duplicate_skipped",
            )
            .order_by(AuditLog.created_at.desc())
        )
    ).scalars().all()
    original_by_invoice: dict[int, int] = {}
    hash_by_invoice: dict[int, str] = {}
    for row in audit_rows:
        iid = row.invoice_id
        if iid is None or iid in original_by_invoice or iid in hash_by_invoice:
            continue
        if isinstance(row.detail, dict):
            raw_id = row.detail.get("original_invoice_id")
            if isinstance(raw_id, int):
                original_by_invoice[iid] = raw_id
            raw_hash = row.detail.get("file_hash")
            if isinstance(raw_hash, str):
                hash_by_invoice[iid] = raw_hash

    original_ids = list(original_by_invoice.values())
    others_by_id: dict[int, Invoice] = {}
    if original_ids:
        others = (
            await db.execute(
                select(Invoice).where(
                    Invoice.tenant_id == tenant_id,
                    Invoice.id.in_(original_ids),
                )
            )
        ).scalars().all()
        others_by_id = {row.id: row for row in others}

    unresolved: list[Invoice] = []
    for inv in dupes:
        original_id = original_by_invoice.get(inv.id)
        if original_id is not None:
            other = others_by_id.get(original_id)
            if other is not None:
                out[inv.id] = (_document_ref(other), _conflict_detail(inv, other))
                continue
        unresolved.append(inv)

    for inv in unresolved:
        file_hash = hash_by_invoice.get(inv.id) or inv.file_hash
        stmt = (
            select(Invoice)
            .where(
                Invoice.tenant_id == tenant_id,
                Invoice.id != inv.id,
                Invoice.status != InvoiceStatus.DUPLICATE_SKIPPED,
            )
            .order_by(Invoice.created_at.desc())
        )
        if inv.invoice_no and inv.vendor:
            stmt = stmt.where(
                Invoice.invoice_no == inv.invoice_no,
                Invoice.vendor == inv.vendor,
            )
        elif file_hash:
            stmt = stmt.where(Invoice.file_hash == file_hash)
        else:
            continue
        other = (await db.execute(stmt.limit(1))).scalar_one_or_none()
        if other is not None:
            out[inv.id] = (_document_ref(other), _conflict_detail(inv, other))
    return out


@dataclass(frozen=True)
class MatrixListResult:
    rows: list[MatrixRowResponse]
    page: int
    total: int
    pages: int
    document_count: int = 0
    flagged: int = 0
    duplicates: int = 0
    awaiting: int = 0
    paid_this_month: int = 0
    review_count: int = 0
    processing_count: int = 0
    approved_count: int = 0
    rejected_count: int = 0


def parse_route_target_filter(raw: str | None) -> list[str]:
    """Comma-separated route targets; order preserved, blanks dropped."""
    tokens: list[str] = []
    for part in (raw or "").split(","):
        token = part.strip()
        if token and token not in tokens:
            tokens.append(token)
    return tokens


def _scoped_invoice_query(tenant_id: uuid.UUID, params: MatrixListRequest):
    stmt = select(Invoice).where(Invoice.tenant_id == tenant_id)
    count_stmt = select(func.count(Invoice.id)).where(Invoice.tenant_id == tenant_id)
    if params.status:
        try:
            status_enum = InvoiceStatus(params.status)
            stmt = stmt.where(Invoice.status == status_enum)
            count_stmt = count_stmt.where(Invoice.status == status_enum)
        except ValueError:
            pass
    if params.route_target and params.route_target.strip():
        stmt = _apply_route_target(stmt, params.route_target)
        count_stmt = _apply_route_target(count_stmt, params.route_target)
    if params.evaluation_status and params.evaluation_status.strip():
        token = params.evaluation_status.strip()
        stmt = stmt.where(Invoice.evaluation_status == token)
        count_stmt = count_stmt.where(Invoice.evaluation_status == token)
    stmt = _apply_capture_source(stmt, params.capture_source)
    count_stmt = _apply_capture_source(count_stmt, params.capture_source)
    stmt = _apply_search(stmt, params.q)
    count_stmt = _apply_search(count_stmt, params.q)
    stmt = _apply_matrix_filter(stmt, params.matrix_filter, tenant_id=tenant_id)
    count_stmt = _apply_matrix_filter(count_stmt, params.matrix_filter, tenant_id=tenant_id)
    stmt = apply_approval_board_column(stmt, params.approval_board_column)
    count_stmt = apply_approval_board_column(count_stmt, params.approval_board_column)
    return stmt, count_stmt


def _params_have_list_filters(params: MatrixListRequest) -> bool:
    return bool(
        (params.status or "").strip()
        or (params.route_target or "").strip()
        or (params.evaluation_status or "").strip()
        or (params.q or "").strip()
        or (params.matrix_filter or "").strip()
        or (params.approval_board_column or "").strip()
    )


async def _matrix_summary(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    params: MatrixListRequest,
) -> tuple[int, int, int, int]:
    """KPI totals for the scoped matrix (independent of the current page)."""
    base_ids = select(Invoice.id).where(Invoice.tenant_id == tenant_id)
    base_ids = _apply_capture_source(base_ids, params.capture_source)
    base_ids = _apply_route_target(base_ids, params.route_target)

    flagged_or_dup = (
        await db.execute(
            select(
                func.count(Invoice.id).filter(
                    or_(
                        Invoice.status.in_(
                            (
                                InvoiceStatus.EXCEPTION,
                                InvoiceStatus.DUPLICATE_SKIPPED,
                                InvoiceStatus.REJECTED,
                            )
                        ),
                        and_(
                            Invoice.evaluation_status.in_(_FLAGGED_EVAL),
                            Invoice.status != InvoiceStatus.PROCESSED,
                        ),
                    )
                ),
                func.count(Invoice.id).filter(
                    Invoice.status == InvoiceStatus.DUPLICATE_SKIPPED
                ),
            ).where(
                Invoice.tenant_id == tenant_id,
                Invoice.id.in_(base_ids),
            )
        )
    ).one()
    flagged = int(flagged_or_dup[0] or 0)
    duplicates = int(flagged_or_dup[1] or 0)
    today = func.current_date()
    paid_stmt = select(func.count(func.distinct(Payment.invoice_id))).where(
        Payment.tenant_id == tenant_id,
        Payment.invoice_id.in_(base_ids),
        Payment.status == PaymentStatus.PAID,
        Payment.paid_date.isnot(None),
        func.extract("year", Payment.paid_date) == func.extract("year", today),
        func.extract("month", Payment.paid_date) == func.extract("month", today),
    )
    awaiting_pay_ids = select(Payment.invoice_id).where(
        Payment.tenant_id == tenant_id,
        Payment.invoice_id.in_(base_ids),
        Payment.status.in_(
            (PaymentStatus.AWAITING, PaymentStatus.QUEUE, PaymentStatus.SCHEDULED)
        ),
    )
    awaiting_stmt = select(func.count(Invoice.id)).where(
        Invoice.tenant_id == tenant_id,
        Invoice.id.in_(base_ids),
        or_(
            Invoice.id.in_(awaiting_pay_ids),
            and_(
                Invoice.status == InvoiceStatus.PROCESSED,
                Invoice.due_date.isnot(None),
            ),
        ),
    )
    awaiting = (await db.execute(awaiting_stmt)).scalar() or 0
    paid = (await db.execute(paid_stmt)).scalar() or 0
    return flagged, int(duplicates), int(awaiting), int(paid)


async def _approval_board_counts(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    params: MatrixListRequest,
) -> dict[str, int]:
    col = approval_board_column_expr()
    stmt = select(col.label("board"), func.count(Invoice.id)).where(
        Invoice.tenant_id == tenant_id
    )
    stmt = _apply_capture_source(stmt, params.capture_source)
    stmt = _apply_route_target(stmt, params.route_target)
    stmt = _apply_search(stmt, params.q)
    stmt = stmt.group_by(col)
    counts = {"review": 0, "processing": 0, "approved": 0, "rejected": 0}
    for board, n in (await db.execute(stmt)).all():
        key = str(board or "")
        if key in counts:
            counts[key] = int(n or 0)
    return counts


async def fetch_document_matrix(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    params: MatrixListRequest,
) -> MatrixListResult:
    stmt, count_stmt = _scoped_invoice_query(tenant_id, params)
    stmt = (
        stmt.options(*invoice_list_load_options())
        .order_by(Invoice.created_at.desc(), Invoice.id.desc())
    )

    total = (await db.execute(count_stmt)).scalar() or 0
    pages = max(1, (total + params.page_size - 1) // params.page_size)
    invoices = (
        await db.execute(
            stmt.offset((params.page - 1) * params.page_size).limit(params.page_size)
        )
    ).scalars().all()

    invoice_ids = [inv.id for inv in invoices]
    audit_by_id = await audit_logs_for_invoice_ids(
        db,
        invoice_ids,
        tenant_id=tenant_id,
        per_invoice_limit=_MATRIX_AUDIT_PER_INVOICE,
        events=_MATRIX_LIST_AUDIT_EVENTS,
    )
    payments_by_id = await payments_for_invoice_ids(db, tenant_id, invoice_ids)
    published_ids = await published_invoice_ids(db, invoice_ids, tenant_id=tenant_id)
    conflicts = await duplicate_conflicts_for_invoices(db, tenant_id, list(invoices))
    line_counts = await line_item_counts_for_invoice_ids(db, invoice_ids)
    ledger_status_by_id, ref_status_by_id = await accounting_sync_status_for_invoice_ids(
        db, tenant_id, invoice_ids
    )
    flagged, duplicates, awaiting, paid = await _matrix_summary(
        db, tenant_id=tenant_id, params=params
    )
    board_counts = await _approval_board_counts(
        db, tenant_id=tenant_id, params=params
    )

    if _params_have_list_filters(params):
        unfiltered_count_stmt = select(func.count(Invoice.id)).where(
            Invoice.tenant_id == tenant_id
        )
        unfiltered_count_stmt = _apply_capture_source(
            unfiltered_count_stmt, params.capture_source
        )
        document_count = (await db.execute(unfiltered_count_stmt)).scalar() or 0
    else:
        document_count = int(total)

    config = await load_posting_config_for_tenant(db, tenant_id)
    document_types = list(config.document_types or [])

    rows: list[MatrixRowResponse] = []
    for inv in invoices:
        flag, flag_reason = derive_matrix_flag(inv, document_types=document_types)
        payment = payments_by_id.get(inv.id)
        conflict_with, conflict_detail = conflicts.get(inv.id, (None, []))
        paid_date = None
        if payment is not None and payment.paid_date is not None:
            paid_date = payment.paid_date.isoformat()

        rows.append(
            MatrixRowResponse(
                invoice=invoice_to_response(
                    inv,
                    published_to_ledger=inv.id in published_ids,
                    audit_logs=audit_by_id.get(inv.id, []),
                    document_types=document_types,
                    for_list=True,
                ),
                stages=build_matrix_cells(inv, audit_by_id.get(inv.id, [])),
                flag=flag,
                flag_reason=flag_reason,
                payment_status=derive_matrix_payment_status(inv, payment),
                paid_date=paid_date,
                conflict_with=conflict_with,
                conflict_detail=conflict_detail or None,
                line_item_count=line_counts.get(inv.id, 0),
                advance_auth=derive_matrix_advance_auth(
                    inv, document_types=document_types
                ),
                budget_auth=derive_matrix_budget_auth(
                    inv, document_types=document_types
                ),
                acc_sync=derive_matrix_acc_sync(
                    inv,
                    ledger_status=ledger_status_by_id.get(inv.id),
                    ref_status=ref_status_by_id.get(inv.id),
                    document_types=document_types,
                ),
            )
        )
    return MatrixListResult(
        rows=rows,
        page=params.page,
        total=total,
        pages=pages,
        document_count=int(document_count),
        flagged=flagged,
        duplicates=duplicates,
        awaiting=awaiting,
        paid_this_month=paid,
        review_count=board_counts["review"],
        processing_count=board_counts["processing"],
        approved_count=board_counts["approved"],
        rejected_count=board_counts["rejected"],
    )
