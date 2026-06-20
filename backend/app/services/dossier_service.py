"""Assemble dossier hero view from invoice + related services."""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog
from app.models.invoice import Invoice, InvoiceStatus
from app.models.organisation import Organisation
from app.models.payment import Payment, PaymentStatus
from app.schemas.dossier import DossierSummaryResponse
from app.services.document_ref_service import display_document_ref
from app.services.document_type_playbook_service import resolve_definition_for_invoice
from app.services.dossier_approval_service import build_dossier_approval_chain
from app.services.dossier_linked_documents_service import build_dossier_linked_documents
from app.services.dossier_pipeline_service import build_dossier_pipeline, first_pipeline_failure
from app.services.invoice_evaluation_service import load_config_for_org
from app.services.matrix_service import derive_matrix_payment_status
from app.services.pipeline_stages import _actor_name, _latest_log, _source_label


def dossier_public_id(invoice: Invoice) -> str:
    ref = (invoice.document_ref or "").strip()
    if ref:
        return ref
    return str(invoice.id)


def dossier_capture_channel(invoice: Invoice) -> str:
    src = (invoice.capture_source or "").strip().lower()
    if src == "email":
        return "Email capture"
    if src == "whatsapp":
        return "WhatsApp capture"
    if src == "edi":
        return "EDI capture"
    if invoice.connected_mailbox_id or invoice.email_sender:
        return "Email capture"
    return "Upload"


def _money(value: Decimal | float | int | None) -> float:
    if value is None:
        return 0.0
    return float(value)


def _confidence_pct(value: float | None) -> int:
    if value is None:
        return 0
    if value <= 1:
        return int(round(value * 100))
    return int(round(value))


def _document_type_title(code: str, org_id: int) -> str:
    config = load_config_for_org(org_id)
    token = (code or "").strip().upper()
    for row in config.document_types:
        if row.code.upper() == token:
            return row.title or row.short_title or token
    return token or "Document"


def _owner_from_logs(logs: list[AuditLog]) -> str:
    for event in ("invoice_approved", "invoice_published_to_ledger", "approval_requested"):
        log = _latest_log(logs, event)
        if log:
            actor = _actor_name(log.detail if isinstance(log.detail, dict) else None)
            if actor:
                return actor
    return "System"


def _fraud_risk(invoice: Invoice) -> str:
    if invoice.status == InvoiceStatus.DUPLICATE_SKIPPED:
        return "medium"
    if invoice.evaluation_status in ("needs_review", "pending_vendor"):
        return "medium"
    return "low"


def _sla(invoice: Invoice) -> tuple[str, bool]:
    if invoice.status == InvoiceStatus.PROCESSED:
        return "Posted", False
    if invoice.status == InvoiceStatus.EXCEPTION:
        return "Blocked", True
    if invoice.status == InvoiceStatus.DUPLICATE_SKIPPED:
        return "Blocked", False
    if invoice.due_date and invoice.due_date < date.today():
        return "Overdue", True
    return "In progress", False


def _payment_status_key(invoice: Invoice, payment: Payment | None) -> tuple[str | None, str | None]:
    label = derive_matrix_payment_status(invoice, payment)
    if payment is None:
        return None, None
    if payment.status == PaymentStatus.PAID:
        return "paid", label
    if payment.status == PaymentStatus.FAILED:
        return "failed", label
    if payment.status in (PaymentStatus.AWAITING, PaymentStatus.QUEUE, PaymentStatus.SCHEDULED):
        return "awaiting", label
    return None, label


def _derive_outcome(
    invoice: Invoice,
    logs: list[AuditLog],
    pipeline_fail: bool,
    *,
    published: bool,
    payment: Payment | None,
    fail_detail: str | None,
) -> tuple[str, str]:
    if invoice.status == InvoiceStatus.DUPLICATE_SKIPPED:
        return "blocked", fail_detail or "Duplicate file skipped"
    if invoice.status == InvoiceStatus.REJECTED:
        return "blocked", "Invoice rejected"
    if pipeline_fail or invoice.status == InvoiceStatus.EXCEPTION:
        return "blocked", fail_detail or "Pipeline blocked — review required"
    if payment and payment.status == PaymentStatus.FAILED:
        return "parked", "Payment failed — parked for review"
    if payment and payment.status in (PaymentStatus.AWAITING, PaymentStatus.QUEUE) and invoice.status == InvoiceStatus.PROCESSED:
        return "parked", "Posted — awaiting payment release"
    if invoice.status == InvoiceStatus.PROCESSED:
        approved = any(log.event == "invoice_approved" for log in logs)
        if published:
            return ("manual_posted" if approved else "auto_posted"), "Posted to ledger"
        return "in_progress", "Processed — ready to publish"
    return "in_progress", "Processing"


async def build_dossier_summary(
    session: AsyncSession,
    invoice: Invoice,
    logs: list[AuditLog],
    *,
    payment: Payment | None = None,
    org_name: str | None = None,
    compact: bool = False,
) -> DossierSummaryResponse:
    config = load_config_for_org(invoice.org_id)
    definition = resolve_definition_for_invoice(invoice, config.document_types)
    published = any(log.event == "invoice_published_to_ledger" for log in logs)
    pay_key, pay_detail = _payment_status_key(invoice, payment)

    pipeline = build_dossier_pipeline(
        invoice,
        logs,
        payment_status=pay_key,
        payment_detail=pay_detail,
        compact=compact,
    )
    fail = first_pipeline_failure(pipeline)
    approved_human = any(log.event == "invoice_approved" for log in logs)
    outcome, banner = _derive_outcome(
        invoice,
        logs,
        fail is not None,
        published=published,
        payment=payment,
        fail_detail=fail.detail if fail else None,
    )
    if invoice.status == InvoiceStatus.PROCESSED and published and approved_human:
        outcome = "manual_posted"
        banner = banner or "Manual post — approved before ledger publish"

    linked = await build_dossier_linked_documents(session, invoice, definition=definition)
    approval = await build_dossier_approval_chain(
        session,
        invoice,
        logs,
        definition=definition,
        payment=payment,
        published=published,
    )

    code = (invoice.document_type_code or "").strip().upper()
    sla_label, sla_breached = _sla(invoice)
    inv_date = invoice.invoice_date.isoformat() if invoice.invoice_date else ""

    return DossierSummaryResponse(
        id=dossier_public_id(invoice),
        invoice_id=invoice.id,
        document_type_code=code,
        document_type_title=_document_type_title(code, invoice.org_id),
        vendor=(invoice.vendor or "Unknown vendor").strip(),
        buyer=(org_name or "Organisation").strip(),
        invoice_ref=(invoice.invoice_no or display_document_ref(invoice)).strip(),
        capture_channel=dossier_capture_channel(invoice),
        invoice_date=inv_date,
        currency=(invoice.currency or "AUD").strip() or "AUD",
        subtotal=_money(invoice.subtotal),
        tax=_money(invoice.gst),
        total=_money(invoice.total),
        classification_label=(invoice.route_target or "Transactional").replace("_", " ").title(),
        classification_confidence=_confidence_pct(invoice.document_type_confidence),
        fraud_risk=_fraud_risk(invoice),
        po_reference=(invoice.po_reference or "").strip() or None,
        sla_label=sla_label,
        sla_breached=sla_breached,
        owner=_owner_from_logs(logs),
        outcome=outcome,
        outcome_banner=banner,
        pipeline=pipeline,
        linked_documents=linked,
        approval_chain=approval,
    )


async def resolve_invoice_for_dossier(
    session: AsyncSession,
    org_id: int,
    dossier_id: str,
) -> Invoice | None:
    token = dossier_id.strip()
    if not token:
        return None

    if token.isdigit():
        inv = await session.get(Invoice, int(token))
        return inv if inv is not None and inv.org_id == org_id else None

    upper = token.upper()
    row = (
        await session.execute(
            select(Invoice).where(
                Invoice.org_id == org_id,
                Invoice.document_ref == upper,
            )
        )
    ).scalar_one_or_none()
    if row is not None:
        return row

    return (
        await session.execute(
            select(Invoice).where(
                Invoice.org_id == org_id,
                Invoice.document_ref == token,
            )
        )
    ).scalar_one_or_none()


async def list_dossier_invoices(
    session: AsyncSession,
    org_id: int,
    *,
    page: int,
    page_size: int,
    document_type_code: str | None = None,
    q: str | None = None,
) -> tuple[list[Invoice], int]:
    stmt = (
        select(Invoice)
        .where(Invoice.org_id == org_id)
        .order_by(Invoice.created_at.desc(), Invoice.id.desc())
    )
    count_stmt = select(func.count(Invoice.id)).where(Invoice.org_id == org_id)

    if document_type_code and document_type_code.strip().lower() != "all":
        code = document_type_code.strip().upper()
        stmt = stmt.where(Invoice.document_type_code == code)
        count_stmt = count_stmt.where(Invoice.document_type_code == code)

    if q and q.strip():
        needle = f"%{q.strip().lower()}%"
        filt = or_(
            Invoice.vendor.ilike(needle),
            Invoice.invoice_no.ilike(needle),
            Invoice.document_ref.ilike(needle),
            Invoice.po_reference.ilike(needle),
            Invoice.document_type_code.ilike(needle),
        )
        stmt = stmt.where(filt)
        count_stmt = count_stmt.where(filt)

    total = (await session.execute(count_stmt)).scalar() or 0
    rows = (
        await session.execute(stmt.offset((page - 1) * page_size).limit(page_size))
    ).scalars().all()
    return list(rows), total


async def org_display_name(session: AsyncSession, org_id: int) -> str:
    org = await session.get(Organisation, org_id)
    return org.name if org and org.name else "Organisation"
