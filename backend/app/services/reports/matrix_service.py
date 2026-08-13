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
from app.services.invoice.invoice_related_query_service import (
    audit_logs_for_invoice_ids,
    payments_for_invoice_ids,
)
from app.services.invoice.invoice_response_service import (
    invoice_list_load_options,
    invoice_to_response,
)
from app.services.invoice.pipeline_stages import build_matrix_cells, exception_hold_reason
from app.services.integration.publish_service import published_invoice_ids

# Cap audit rows per invoice for matrix stages (latest-first). Full OCR text is never needed.
_MATRIX_AUDIT_PER_INVOICE = 60


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


def _apply_capture_source(query, capture_source: str | None):
    if not capture_source or not capture_source.strip():
        return query
    src = capture_source.strip().lower()
    if src not in {"upload", "email", "whatsapp", "viber"}:
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


def _apply_matrix_filter(query, matrix_filter: str | None, *, tenant_id: uuid.UUID):
    token = (matrix_filter or "all").strip().lower()
    if token in {"", "all"}:
        return query
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
        token = params.route_target.strip()
        stmt = stmt.where(Invoice.route_target == token)
        count_stmt = count_stmt.where(Invoice.route_target == token)
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
    return stmt, count_stmt


async def _matrix_summary(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    params: MatrixListRequest,
) -> tuple[int, int, int, int]:
    """KPI totals for the scoped matrix (independent of the current page)."""
    base_ids = select(Invoice.id).where(Invoice.tenant_id == tenant_id)
    base_ids = _apply_capture_source(base_ids, params.capture_source)

    flagged_stmt = select(func.count(Invoice.id)).where(
        Invoice.tenant_id == tenant_id,
        Invoice.id.in_(base_ids),
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
        ),
    )
    duplicates_stmt = select(func.count(Invoice.id)).where(
        Invoice.tenant_id == tenant_id,
        Invoice.id.in_(base_ids),
        Invoice.status == InvoiceStatus.DUPLICATE_SKIPPED,
    )
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
    flagged = (await db.execute(flagged_stmt)).scalar() or 0
    duplicates = (await db.execute(duplicates_stmt)).scalar() or 0
    awaiting = (await db.execute(awaiting_stmt)).scalar() or 0
    paid = (await db.execute(paid_stmt)).scalar() or 0
    return int(flagged), int(duplicates), int(awaiting), int(paid)


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
    )
    payments_by_id = await payments_for_invoice_ids(db, tenant_id, invoice_ids)
    published_ids = await published_invoice_ids(db, invoice_ids, tenant_id=tenant_id)
    conflicts = await duplicate_conflicts_for_invoices(db, tenant_id, list(invoices))
    flagged, duplicates, awaiting, paid = await _matrix_summary(
        db, tenant_id=tenant_id, params=params
    )

    unfiltered_count_stmt = select(func.count(Invoice.id)).where(
        Invoice.tenant_id == tenant_id
    )
    unfiltered_count_stmt = _apply_capture_source(
        unfiltered_count_stmt, params.capture_source
    )
    document_count = (await db.execute(unfiltered_count_stmt)).scalar() or 0

    from app.services.invoice.invoice_evaluation_service import load_config_for_tenant

    config = await load_config_for_tenant(db, tenant_id)
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
                    for_list=True,
                ),
                stages=build_matrix_cells(inv, audit_by_id.get(inv.id, [])),
                flag=flag,
                flag_reason=flag_reason,
                payment_status=derive_matrix_payment_status(inv, payment),
                paid_date=paid_date,
                conflict_with=conflict_with,
                conflict_detail=conflict_detail or None,
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
    )
