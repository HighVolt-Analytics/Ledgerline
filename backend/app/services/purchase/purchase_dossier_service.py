"""Purchase dossier (PO + GRN + invoice) for invoice drawer PO Match tab."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.invoice import Invoice, InvoiceStatus, PurchaseDocumentType
from app.schemas.dossier import DossierMatchSummaryResponse
from app.schemas.purchase import PurchaseDossierMember, PurchaseDossierResponse, ThreeWayMatchResult
from app.services.dossier.dossier_match_service import build_dossier_match_summary
from app.services.shared.file_storage import has_stored_path, stored_file_available
from app.services.dossier.document_ref_service import dossier_public_id
from app.services.purchase.po_reference import invoice_po_reference_equals, is_plausible_po_reference
from app.services.purchase.purchase_linking_service import find_grn_invoices_by_invoice_no
from app.services.purchase.purchase_match_service import (
    _latest_grn,
    compute_three_way_match,
    load_purchase_order_for_invoice,
    purchase_order_to_response,
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
    rows = await _invoices_by_id(session, {invoice_id})
    return rows.get(invoice_id)


async def _latest_uploads_for_roles(
    session: AsyncSession,
    *,
    tenant_id: int,
    po_reference: str,
    roles: tuple[str, ...],
) -> dict[str, Invoice | None]:
    if not roles:
        return {}
    rows = (
        await session.execute(
            select(Invoice)
            .where(
                Invoice.tenant_id == tenant_id,
                invoice_po_reference_equals(po_reference),
                Invoice.purchase_document_type.in_(roles),
                Invoice.status.not_in(_ACTIVE_STATUSES),
            )
            .order_by(Invoice.purchase_document_type, Invoice.id.desc())
        )
    ).scalars().all()
    latest: dict[str, Invoice | None] = {role: None for role in roles}
    for row in rows:
        role = (row.purchase_document_type or "").strip().lower()
        if role in latest and latest[role] is None:
            latest[role] = row
    return latest


async def _invoices_by_id(
    session: AsyncSession,
    invoice_ids: set[int],
) -> dict[int, Invoice]:
    if not invoice_ids:
        return {}
    rows = (
        await session.execute(
            select(Invoice)
            .where(Invoice.id.in_(invoice_ids))
            .options(selectinload(Invoice.line_items))
        )
    ).scalars().all()
    return {row.id: row for row in rows}


def _member(
    role: str,
    invoice: Invoice | None,
    *,
    current_invoice_id: int,
    verify_stored_file: bool,
) -> PurchaseDossierMember:
    label = _ROLE_LABELS.get(role, role)
    if invoice is None:
        return PurchaseDossierMember(role=role, label=label, present=False)
    has_file = (
        stored_file_available(invoice.raw_file_path, tenant_id=invoice.tenant_id)
        if verify_stored_file
        else has_stored_path(invoice.raw_file_path)
    )
    return PurchaseDossierMember(
        role=role,
        label=label,
        invoice_id=invoice.id,
        document_ref=_document_ref(invoice),
        present=True,
        has_stored_file=has_file,
        is_current=invoice.id == current_invoice_id,
    )


async def build_purchase_dossier(
    session: AsyncSession,
    invoice: Invoice,
    *,
    verify_stored_file: bool = True,
) -> PurchaseDossierResponse:
    po_reference = (invoice.po_reference or "").strip()
    if not po_reference or not is_plausible_po_reference(po_reference):
        return PurchaseDossierResponse(
            po_reference=None,
            current_role=_current_role(invoice),
            members=[
                _member(PurchaseDocumentType.PO.value, None, current_invoice_id=invoice.id, verify_stored_file=verify_stored_file),
                _member(PurchaseDocumentType.GRN.value, None, current_invoice_id=invoice.id, verify_stored_file=verify_stored_file),
                _member(PurchaseDocumentType.INVOICE.value, None, current_invoice_id=invoice.id, verify_stored_file=verify_stored_file),
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

    role_uploads = await _latest_uploads_for_roles(
        session,
        tenant_id=invoice.tenant_id,
        po_reference=po_reference,
        roles=(
            PurchaseDocumentType.PO.value,
            PurchaseDocumentType.GRN.value,
            PurchaseDocumentType.INVOICE.value,
        ),
    )
    po_upload = role_uploads.get(PurchaseDocumentType.PO.value)
    grn_upload = role_uploads.get(PurchaseDocumentType.GRN.value)
    invoice_upload = role_uploads.get(PurchaseDocumentType.INVOICE.value)

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

    commercial_match_id = commercial_id
    if commercial_match_id is None and current_role == PurchaseDocumentType.INVOICE.value:
        commercial_match_id = invoice.id

    if grn_doc_id is None and commercial_match_id is not None:
        loaded_commercial = await _invoice_by_id(session, commercial_match_id)
        if loaded_commercial and loaded_commercial.invoice_no:
            from app.services.extraction.invoice_no_sanitizer import INVOICE_NO_SECONDARY_KEY

            extracted = loaded_commercial.extracted_fields or {}
            secondary = (
                extracted.get(INVOICE_NO_SECONDARY_KEY) if isinstance(extracted, dict) else None
            )
            grn_matches = await find_grn_invoices_by_invoice_no(
                session,
                tenant_id=invoice.tenant_id,
                invoice_no=loaded_commercial.invoice_no,
                invoice_no_secondary=str(secondary) if secondary else None,
                purchase_order_id=po_row.id if po_row is not None else None,
            )
            if grn_matches:
                grn_doc_id = grn_matches[0].id

    invoice_ids = {i for i in (po_doc_id, grn_doc_id, commercial_id) if i is not None}
    if commercial_match_id is not None:
        invoice_ids.add(commercial_match_id)

    loaded = await _invoices_by_id(session, invoice_ids)
    po_doc = loaded.get(po_doc_id) if po_doc_id is not None else None
    grn_doc = loaded.get(grn_doc_id) if grn_doc_id is not None else None
    commercial_doc = loaded.get(commercial_id) if commercial_id is not None else None

    members = [
        _member(PurchaseDocumentType.PO.value, po_doc, current_invoice_id=invoice.id, verify_stored_file=verify_stored_file),
        _member(PurchaseDocumentType.GRN.value, grn_doc, current_invoice_id=invoice.id, verify_stored_file=verify_stored_file),
        _member(
            PurchaseDocumentType.INVOICE.value,
            commercial_doc,
            current_invoice_id=invoice.id,
            verify_stored_file=verify_stored_file,
        ),
    ]

    match: ThreeWayMatchResult | None = None
    match_status: str | None = None
    match_summary: DossierMatchSummaryResponse | None = None
    purchase_register = None
    purchase_order_id: int | None = None

    if po_row is not None:
        purchase_order_id = po_row.id
        commercial_for_match = (
            loaded.get(commercial_match_id) if commercial_match_id is not None else None
        )
        if commercial_for_match is None and po_row.invoice_id is not None:
            commercial_for_match = loaded.get(po_row.invoice_id)
            if commercial_for_match is None:
                commercial_for_match = await _invoice_by_id(session, po_row.invoice_id)
        match = compute_three_way_match(po_row, commercial_for_match)
        match_status = match.status
        match_summary = build_dossier_match_summary(
            po_row=po_row,
            commercial=commercial_for_match,
            match=match,
            currency=(invoice.currency or "").strip(),
            po_doc=po_doc,
            grn_doc=grn_doc,
        )
        from app.services.invoice.invoice_evaluation_service import load_posting_config_for_tenant

        config = await load_posting_config_for_tenant(session, invoice.tenant_id)
        purchase_register = purchase_order_to_response(
            po_row,
            commercial_for_match,
            config=config,
        )

    return PurchaseDossierResponse(
        po_reference=po_reference,
        current_role=current_role,
        members=members,
        purchase_order_id=purchase_order_id,
        match=match,
        match_status=match_status,
        match_summary=match_summary,
        purchase_register=purchase_register,
    )
