"""Purchase dossier (PO + GRN + invoice) for invoice drawer PO Match tab."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.invoice import Invoice, InvoiceStatus, PurchaseDocumentType
from app.schemas.purchase import PurchaseDossierMember, PurchaseDossierResponse, ThreeWayMatchResult
from app.services.file_storage import stored_file_available
from app.services.document_ref_service import dossier_public_id
from app.services.po_reference import is_plausible_po_reference
from app.services.purchase_match_service import (
    _latest_grn,
    compute_three_way_match,
    load_purchase_order_for_invoice,
)

_ROLE_LABELS = {
    PurchaseDocumentType.PO.value: "Purchase Order",
    PurchaseDocumentType.GRN.value: "Goods Receipt",
    PurchaseDocumentType.INVOICE.value: "Commercial Invoice",
}

_ACTIVE_STATUSES = {
    InvoiceStatus.DUPLICATE_SKIPPED,
    InvoiceStatus.REJECTED,
}


def _document_ref(inv: Invoice) -> str:
    return dossier_public_id(inv)


def _current_role(invoice: Invoice) -> str | None:
    token = (invoice.purchase_document_type or "").strip().lower()
    if token in _ROLE_LABELS:
        return token
    return None


async def _invoice_by_id(session: AsyncSession, invoice_id: int | None) -> Invoice | None:
    if invoice_id is None:
        return None
    return (
        await session.execute(
            select(Invoice)
            .where(Invoice.id == invoice_id)
            .options(selectinload(Invoice.line_items))
        )
    ).scalar_one_or_none()


async def _latest_upload_for_role(
    session: AsyncSession,
    *,
    tenant_id: int,
    po_reference: str,
    purchase_document_type: str,
) -> Invoice | None:
    row = (
        await session.execute(
            select(Invoice)
            .where(
                Invoice.tenant_id == tenant_id,
                Invoice.po_reference == po_reference,
                Invoice.purchase_document_type == purchase_document_type,
                Invoice.status.not_in(_ACTIVE_STATUSES),
            )
            .order_by(Invoice.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return row


def _member(
    role: str,
    invoice: Invoice | None,
    *,
    current_invoice_id: int,
) -> PurchaseDossierMember:
    label = _ROLE_LABELS.get(role, role)
    if invoice is None:
        return PurchaseDossierMember(role=role, label=label, present=False)
    return PurchaseDossierMember(
        role=role,
        label=label,
        invoice_id=invoice.id,
        document_ref=_document_ref(invoice),
        present=True,
        has_stored_file=stored_file_available(invoice.raw_file_path),
        is_current=invoice.id == current_invoice_id,
    )


async def build_purchase_dossier(
    session: AsyncSession,
    invoice: Invoice,
) -> PurchaseDossierResponse:
    po_reference = (invoice.po_reference or "").strip()
    if not po_reference or not is_plausible_po_reference(po_reference):
        return PurchaseDossierResponse(
            po_reference=None,
            current_role=_current_role(invoice),
            members=[
                _member(PurchaseDocumentType.PO.value, None, current_invoice_id=invoice.id),
                _member(PurchaseDocumentType.GRN.value, None, current_invoice_id=invoice.id),
                _member(PurchaseDocumentType.INVOICE.value, None, current_invoice_id=invoice.id),
            ],
        )

    po_row = await load_purchase_order_for_invoice(session, invoice)

    po_doc_id = po_row.po_document_id if po_row else None
    grn_doc_id = None
    commercial_id = po_row.invoice_id if po_row else None

    if po_row is not None:
        grn = _latest_grn(po_row)
        if grn is not None:
            grn_doc_id = grn.grn_invoice_id

    po_upload = await _latest_upload_for_role(
        session,
        tenant_id=invoice.tenant_id,
        po_reference=po_reference,
        purchase_document_type=PurchaseDocumentType.PO.value,
    )
    grn_upload = await _latest_upload_for_role(
        session,
        tenant_id=invoice.tenant_id,
        po_reference=po_reference,
        purchase_document_type=PurchaseDocumentType.GRN.value,
    )
    invoice_upload = await _latest_upload_for_role(
        session,
        tenant_id=invoice.tenant_id,
        po_reference=po_reference,
        purchase_document_type=PurchaseDocumentType.INVOICE.value,
    )

    if po_doc_id is None and po_upload is not None:
        po_doc_id = po_upload.id
    if grn_doc_id is None and grn_upload is not None:
        grn_doc_id = grn_upload.id
    if commercial_id is None and invoice_upload is not None:
        commercial_id = invoice_upload.id

    current_role = _current_role(invoice)
    if current_role == PurchaseDocumentType.PO.value and po_doc_id is None:
        po_doc_id = invoice.id
    elif current_role == PurchaseDocumentType.GRN.value and grn_doc_id is None:
        grn_doc_id = invoice.id
    elif current_role == PurchaseDocumentType.INVOICE.value and commercial_id is None:
        commercial_id = invoice.id

    po_doc = await _invoice_by_id(session, po_doc_id)
    grn_doc = await _invoice_by_id(session, grn_doc_id)
    commercial_doc = await _invoice_by_id(session, commercial_id)

    members = [
        _member(PurchaseDocumentType.PO.value, po_doc, current_invoice_id=invoice.id),
        _member(PurchaseDocumentType.GRN.value, grn_doc, current_invoice_id=invoice.id),
        _member(
            PurchaseDocumentType.INVOICE.value,
            commercial_doc,
            current_invoice_id=invoice.id,
        ),
    ]

    match: ThreeWayMatchResult | None = None
    match_status: str | None = None
    purchase_order_id: int | None = None

    if po_row is not None:
        purchase_order_id = po_row.id
        commercial_match_id = commercial_id
        if commercial_match_id is None and current_role == PurchaseDocumentType.INVOICE.value:
            commercial_match_id = invoice.id
        commercial_for_match = await _invoice_by_id(session, commercial_match_id)
        match = compute_three_way_match(po_row, commercial_for_match)
        match_status = match.status

    return PurchaseDossierResponse(
        po_reference=po_reference,
        current_role=current_role,
        members=members,
        purchase_order_id=purchase_order_id,
        match=match,
        match_status=match_status,
    )
