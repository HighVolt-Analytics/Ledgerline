"""Assemble dossier hero view from invoice + related services."""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog
from app.models.invoice import Invoice, InvoiceStatus
from app.models.tenant import Tenant
from app.models.payment import Payment, PaymentStatus
from app.schemas.dossier import DossierLinkedDocumentResponse, DossierLinkedDocumentsResponse, DossierSummaryResponse
from app.schemas.rule_book_config import RuleBookConfigPayload
from app.services.sales.counterparty_service import (
    counterparty_side_for_route,
    resolve_counterparty_from_invoice_context,
)
from app.services.dossier.document_ref_service import display_document_ref, dossier_public_id, parse_dossier_id_token
from app.services.classification.document_type_catalog import ROUTE_SALES
from app.services.purchase.po_reference import effective_po_reference, is_plausible_po_reference
from app.services.sales.so_reference import is_plausible_so_reference, resolve_so_reference_from_invoice
from app.services.classification.document_type_playbook_service import resolve_definition_for_invoice
from app.services.dossier.dossier_approval_service import build_dossier_approval_chain
from app.services.dossier.dossier_linked_documents_service import build_dossier_linked_documents
from app.services.dossier.dossier_match_service import enrich_match_pipeline_step
from app.services.dossier.dossier_pipeline_service import (
    build_dossier_pipeline,
    classification_review_pending,
    first_pipeline_failure,
)
from app.services.shared.file_storage import has_stored_path
from app.services.invoice.invoice_evaluation_service import load_posting_config_for_tenant
from app.services.reports.matrix_service import derive_matrix_payment_status
from app.services.invoice.pipeline_stages import _actor_name, _latest_log, _source_label
from app.services.integration.publish_service import is_published_from_audit_logs
from app.tenant_settings import tenant_today


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


def _document_type_title(code: str, document_types) -> str:
    token = (code or "").strip().upper()
    for row in document_types:
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


def _sla(invoice: Invoice, *, today: date) -> tuple[str, bool]:
    if invoice.status == InvoiceStatus.PROCESSED:
        return "Posted", False
    if invoice.status == InvoiceStatus.EXCEPTION:
        return "Blocked", True
    if invoice.status == InvoiceStatus.DUPLICATE_SKIPPED:
        return "Blocked", False
    if invoice.due_date and invoice.due_date < today:
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
    if (invoice.route_target or "").strip().lower() == "vault":
        if any(log.event == "vault_stored" for log in logs) or invoice.status == InvoiceStatus.PROCESSED:
            return "in_progress", "Stored in document vault"
    doc_type = (invoice.purchase_document_type or "").strip().lower()
    if doc_type in ("po", "grn") and invoice.status == InvoiceStatus.PROCESSED:
        return "auto_posted", "Purchase document processed"
    if invoice.status == InvoiceStatus.PROCESSED:
        approved = any(log.event == "invoice_approved" for log in logs)
        if published:
            return ("manual_posted" if approved else "auto_posted"), "Posted to ledger"
        return "in_progress", "Processed — ready to post"
    return "in_progress", "Processing"


def _linked_doc_dt_label(code: str, document_types) -> str:
    token = (code or "").strip().upper()
    for row in document_types:
        if row.code.upper() == token:
            return row.title or row.short_title or token
    return token or "Document"


async def fetch_linked_invoices_by_invoice_no(
    session: AsyncSession,
    anchor: Invoice,
) -> list[Invoice]:
    """Sibling invoices sharing the same invoice_no as the anchor dossier."""
    token = (anchor.invoice_no or "").strip()
    if not token:
        return []
    rows = (
        await session.execute(
            select(Invoice)
            .where(
                Invoice.tenant_id == anchor.tenant_id,
                Invoice.invoice_no == token,
                Invoice.id != anchor.id,
            )
            .order_by(Invoice.id.asc())
        )
    ).scalars().all()
    return list(rows)


def _linked_invoice_ids(response: DossierLinkedDocumentsResponse) -> set[int]:
    ids: set[int] = set()
    for doc in response.documents:
        if doc.invoice_id is not None:
            ids.add(doc.invoice_id)
        if doc.manual_link is not None:
            ids.add(doc.manual_link.invoice_id)
    return ids


def _invoice_no_linked_document(
    row: Invoice,
    *,
    invoice_no: str,
    document_types,
) -> DossierLinkedDocumentResponse:
    code = (row.document_type_code or "").strip().upper()
    return DossierLinkedDocumentResponse(
        id=f"invoice-no-{row.id}",
        document_type_code=code,
        label=_linked_doc_dt_label(code, document_types),
        document_ref=display_document_ref(row),
        invoice_no=(row.invoice_no or invoice_no).strip() or None,
        present=True,
        requirement="advisory",
        linked_dossier_id=dossier_public_id(row),
        invoice_id=row.id,
        is_anchor=False,
        has_file=has_stored_path(row.raw_file_path),
        linkage_detail=f"Linked on invoice no {invoice_no}",
        link_kind="invoice_no",
    )


async def append_invoice_no_linked_documents(
    session: AsyncSession,
    anchor: Invoice,
    response: DossierLinkedDocumentsResponse,
    *,
    document_types=None,
) -> DossierLinkedDocumentsResponse:
    """
    Append invoices that share anchor.invoice_no (additive; dedupe by invoice id).

    Does not replace bundle / po_reference linked docs.
    """
    invoice_no = (anchor.invoice_no or "").strip()
    if not invoice_no:
        return response

    if document_types is None:
        document_types = (
            await load_posting_config_for_tenant(session, anchor.tenant_id)
        ).document_types

    siblings = await fetch_linked_invoices_by_invoice_no(session, anchor)
    if not siblings:
        return response

    seen = _linked_invoice_ids(response)
    extra: list[DossierLinkedDocumentResponse] = []
    for row in siblings:
        if row.id in seen:
            continue
        extra.append(
            _invoice_no_linked_document(
                row,
                invoice_no=invoice_no,
                document_types=document_types,
            )
        )
        seen.add(row.id)

    if not extra:
        return response

    linkage_key = response.linkage_key or invoice_no
    linkage_label = response.linkage_label
    linkage_kind = response.linkage_kind
    if response.linkage_kind in {"standalone", "shipment_ref"}:
        linkage_kind = "invoice_no"
        linkage_label = f"Invoice no · {invoice_no}"

    return response.model_copy(
        update={
            "linkage_kind": linkage_kind,
            "linkage_key": linkage_key,
            "linkage_label": linkage_label,
            "documents": list(response.documents) + extra,
        }
    )


def dossier_counterparty_label(route_target: str | None) -> str:
    side = counterparty_side_for_route(route_target)
    if side == "customer":
        return "Customer"
    if side == "vendor":
        return "Vendor"
    return "Counterparty"


def dossier_linkage_fields(invoice: Invoice) -> tuple[str | None, str | None, str | None]:
    """Return (po_reference, so_reference, primary linkage key) for dossier summary."""
    so_ref = resolve_so_reference_from_invoice(invoice)
    raw_po = effective_po_reference(invoice.po_reference)
    route = (invoice.route_target or "").strip()
    invoice_no = (invoice.invoice_no or "").strip() or None

    if route == ROUTE_SALES:
        po_display = (
            raw_po
            if raw_po
            and is_plausible_po_reference(raw_po)
            and not is_plausible_so_reference(raw_po)
            else None
        )
        return po_display, so_ref, so_ref or invoice_no or None

    po_display = raw_po if raw_po and is_plausible_po_reference(raw_po) else None
    return po_display, so_ref, po_display or invoice_no or None


async def build_dossier_summary(
    session: AsyncSession,
    invoice: Invoice,
    logs: list[AuditLog],
    *,
    payment: Payment | None = None,
    tenant_name: str | None = None,
    compact: bool = False,
    config: RuleBookConfigPayload | None = None,
) -> DossierSummaryResponse:
    if config is None:
        config = await load_posting_config_for_tenant(session, invoice.tenant_id)
    tenant = await session.get(Tenant, invoice.tenant_id)
    institution_today = tenant_today(tenant)
    definition = resolve_definition_for_invoice(invoice, config.document_types)
    published = is_published_from_audit_logs(logs)
    pay_key, pay_detail = _payment_status_key(invoice, payment)

    pipeline = build_dossier_pipeline(
        invoice,
        logs,
        payment_status=pay_key,
        payment_detail=pay_detail,
        compact=compact,
        document_types=config.document_types,
    )
    fail = first_pipeline_failure(pipeline)

    linked, approval = await asyncio.gather(
        build_dossier_linked_documents(
            session,
            invoice,
            definition=definition,
            document_types=config.document_types,
        ),
        build_dossier_approval_chain(
            session,
            invoice,
            logs,
            definition=definition,
            payment=payment,
            published=published,
        ),
    )

    match_log = _latest_log(logs, "three_way_match_evaluated")
    match_log_detail = match_log.detail if match_log and isinstance(match_log.detail, dict) else None
    if not compact:
        pipeline = enrich_match_pipeline_step(
            pipeline,
            match_summary=linked.match_summary,
            match_log_detail=match_log_detail,
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
        banner = banner or "Manual post — approved before ledger posting"

    code = (invoice.document_type_code or "").strip().upper()
    suggested = (invoice.llm_suggested_dt or "").strip().upper()
    display_code = code or suggested
    pending_classify = classification_review_pending(logs)
    dt_title = _document_type_title(display_code, config.document_types) if display_code else ""
    if dt_title:
        classification_label = dt_title
    elif pending_classify:
        classification_label = "Needs classification review"
    else:
        classification_label = (invoice.route_target or "Unclassified").replace("_", " ").title()
    if pending_classify and not code:
        classification_confidence = _confidence_pct(invoice.llm_confidence)
    else:
        classification_confidence = _confidence_pct(invoice.document_type_confidence)
    sla_label, sla_breached = _sla(invoice, today=institution_today)
    inv_date = invoice.invoice_date.isoformat() if invoice.invoice_date else ""
    route_target = (invoice.route_target or "").strip() or None
    po_display, so_ref, linkage_ref = dossier_linkage_fields(invoice)
    counterparty = (
        resolve_counterparty_from_invoice_context(invoice, config=config)
        or (invoice.vendor or "").strip()
        or "Unknown counterparty"
    )

    return DossierSummaryResponse(
        id=dossier_public_id(invoice),
        invoice_id=invoice.id,
        document_type_code=display_code,
        document_type_title=_document_type_title(display_code, config.document_types) if display_code else "Unclassified",
        vendor=counterparty,
        counterparty_label=dossier_counterparty_label(route_target),
        route_target=route_target,
        buyer=(tenant_name or "Tenant").strip(),
        invoice_ref=(invoice.invoice_no or display_document_ref(invoice)).strip(),
        capture_channel=dossier_capture_channel(invoice),
        invoice_date=inv_date,
        currency=(invoice.currency or "AUD").strip() or "AUD",
        subtotal=_money(invoice.subtotal),
        tax=_money(invoice.gst),
        total=_money(invoice.total),
        classification_label=classification_label,
        classification_confidence=classification_confidence,
        po_reference=po_display,
        so_reference=so_ref,
        linkage_reference=linkage_ref,
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
    tenant_id: int,
    dossier_id: str,
) -> Invoice | None:
    ref_lookup, id_fallback = parse_dossier_id_token(dossier_id)
    if ref_lookup is None and id_fallback is None:
        return None

    if ref_lookup:
        for candidate in (ref_lookup, ref_lookup.upper()):
            row = (
                await session.execute(
                    select(Invoice).where(
                        Invoice.tenant_id == tenant_id,
                        Invoice.document_ref == candidate,
                    )
                )
            ).scalar_one_or_none()
            if row is not None:
                return row

    if id_fallback is not None:
        inv = await session.get(Invoice, id_fallback)
        return inv if inv is not None and inv.tenant_id == tenant_id else None

    return None


async def list_dossier_invoices(
    session: AsyncSession,
    tenant_id: int,
    *,
    page: int,
    page_size: int,
    document_type_code: str | None = None,
    q: str | None = None,
) -> tuple[list[Invoice], int]:
    stmt = (
        select(Invoice)
        .where(Invoice.tenant_id == tenant_id)
        .order_by(Invoice.created_at.desc(), Invoice.id.desc())
    )
    count_stmt = select(func.count(Invoice.id)).where(Invoice.tenant_id == tenant_id)

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
            Invoice.so_reference.ilike(needle),
            Invoice.document_type_code.ilike(needle),
        )
        stmt = stmt.where(filt)
        count_stmt = count_stmt.where(filt)

    total = (await session.execute(count_stmt)).scalar() or 0
    rows = (
        await session.execute(stmt.offset((page - 1) * page_size).limit(page_size))
    ).scalars().all()
    return list(rows), total


async def org_display_name(session: AsyncSession, tenant_id: int) -> str:
    org = await session.get(Tenant, tenant_id)
    return org.name if org and org.name else "Tenant"
