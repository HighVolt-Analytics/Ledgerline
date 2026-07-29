"""Sales dossier (SO + DN + invoice) for invoice drawer SO Match tab."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.invoice import Invoice, InvoiceStatus, SalesDocumentType
from app.schemas.dossier import DossierMatchSummaryResponse
from app.schemas.purchase import ThreeWayMatchResult
from app.schemas.sales import SalesDossierMember, SalesDossierResponse
from app.services.dossier.document_ref_service import dossier_public_id
from app.services.shared.file_storage import has_stored_path, stored_file_available
from app.services.sales.sales_linking_service import find_dn_invoices_by_invoice_no
from app.services.sales.sales_match_service import (
    _latest_dn,
    load_sales_order_for_invoice,
    sales_order_to_response,
)
from app.services.sales.so_reference import invoice_so_reference_equals, is_plausible_so_reference

_ROLE_LABELS = {
    SalesDocumentType.SO.value: "Sales Order",
    SalesDocumentType.DN.value: "Delivery Note",
    SalesDocumentType.INVOICE.value: "Commercial Invoice",
}

_ACTIVE_STATUSES = {
    InvoiceStatus.DUPLICATE_SKIPPED,
    InvoiceStatus.REJECTED,
}


def _document_ref(inv: Invoice) -> str:
    return dossier_public_id(inv)


def _current_role(invoice: Invoice) -> str | None:
    token = (invoice.sales_document_type or "").strip().lower()
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
    tenant_id,
    so_reference: str,
    roles: tuple[str, ...],
) -> dict[str, Invoice | None]:
    if not roles:
        return {}
    rows = (
        await session.execute(
            select(Invoice)
            .where(
                Invoice.tenant_id == tenant_id,
                invoice_so_reference_equals(so_reference),
                Invoice.sales_document_type.in_(roles),
                Invoice.status.not_in(_ACTIVE_STATUSES),
            )
            .order_by(Invoice.sales_document_type, Invoice.id.desc())
        )
    ).scalars().all()
    latest: dict[str, Invoice | None] = {role: None for role in roles}
    for row in rows:
        role = (row.sales_document_type or "").strip().lower()
        if role in latest and latest[role] is None:
            latest[role] = row
    return latest


async def _latest_commercial_upload_for_so(
    session: AsyncSession,
    *,
    tenant_id,
    so_reference: str,
    document_types: list | None,
) -> Invoice | None:
    """Find commercial invoice on SO via sales_document_type or org AR/goods DTs."""
    from app.services.classification.document_type_register_roles import (
        sales_commercial_invoice_dt_codes,
        sales_register_role_for_definition,
    )
    from app.services.classification.document_type_catalog import get_document_type_definition

    role_hit = await _latest_uploads_for_roles(
        session,
        tenant_id=tenant_id,
        so_reference=so_reference,
        roles=(SalesDocumentType.INVOICE.value,),
    )
    typed = role_hit.get(SalesDocumentType.INVOICE.value)
    if typed is not None:
        return typed

    codes = sales_commercial_invoice_dt_codes(document_types)
    if not codes:
        return None
    rows = (
        await session.execute(
            select(Invoice)
            .where(
                Invoice.tenant_id == tenant_id,
                invoice_so_reference_equals(so_reference),
                Invoice.document_type_code.in_(codes),
                Invoice.status.not_in(_ACTIVE_STATUSES),
            )
            .order_by(Invoice.id.desc())
        )
    ).scalars().all()
    for row in rows:
        sales_dt = (row.sales_document_type or "").strip().lower()
        if sales_dt in {SalesDocumentType.SO.value, SalesDocumentType.DN.value}:
            continue
        definition = get_document_type_definition(
            row.document_type_code or "",
            document_types=document_types,
            tenant_id=tenant_id,
        )
        if sales_register_role_for_definition(definition) == "invoice":
            return row
        if not sales_dt:
            return row
    return None


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
) -> SalesDossierMember:
    label = _ROLE_LABELS.get(role, role)
    if invoice is None:
        return SalesDossierMember(role=role, label=label, present=False)
    has_file = (
        stored_file_available(invoice.raw_file_path, tenant_id=invoice.tenant_id)
        if verify_stored_file
        else has_stored_path(invoice.raw_file_path)
    )
    return SalesDossierMember(
        role=role,
        label=label,
        invoice_id=invoice.id,
        document_ref=_document_ref(invoice),
        present=True,
        has_stored_file=has_file,
        is_current=invoice.id == current_invoice_id,
    )


async def build_sales_dossier(
    session: AsyncSession,
    invoice: Invoice,
    *,
    verify_stored_file: bool = True,
) -> SalesDossierResponse:
    so_reference = (invoice.so_reference or "").strip()
    if not so_reference or not is_plausible_so_reference(so_reference):
        return SalesDossierResponse(
            so_reference=None,
            current_role=_current_role(invoice),
            members=[
                _member(SalesDocumentType.SO.value, None, current_invoice_id=invoice.id, verify_stored_file=verify_stored_file),
                _member(SalesDocumentType.DN.value, None, current_invoice_id=invoice.id, verify_stored_file=verify_stored_file),
                _member(SalesDocumentType.INVOICE.value, None, current_invoice_id=invoice.id, verify_stored_file=verify_stored_file),
            ],
        )

    so_row = await load_sales_order_for_invoice(session, invoice)

    so_doc_id = so_row.so_document_id if so_row else None
    dn_doc_id = None
    commercial_id = so_row.invoice_id if so_row else None

    if so_row is not None:
        dn = _latest_dn(so_row)
        if dn is not None:
            dn_doc_id = dn.dn_invoice_id

    from app.services.invoice.invoice_evaluation_service import load_posting_config_for_tenant

    config = await load_posting_config_for_tenant(session, invoice.tenant_id)
    document_types = list(config.document_types)

    role_uploads = await _latest_uploads_for_roles(
        session,
        tenant_id=invoice.tenant_id,
        so_reference=so_reference,
        roles=(
            SalesDocumentType.SO.value,
            SalesDocumentType.DN.value,
            SalesDocumentType.INVOICE.value,
        ),
    )
    so_upload = role_uploads.get(SalesDocumentType.SO.value)
    dn_upload = role_uploads.get(SalesDocumentType.DN.value)
    invoice_upload = role_uploads.get(SalesDocumentType.INVOICE.value)
    if invoice_upload is None:
        invoice_upload = await _latest_commercial_upload_for_so(
            session,
            tenant_id=invoice.tenant_id,
            so_reference=so_reference,
            document_types=document_types,
        )

    if so_doc_id is None and so_upload is not None:
        so_doc_id = so_upload.id
    if dn_doc_id is None and dn_upload is not None:
        dn_doc_id = dn_upload.id
    if commercial_id is None and invoice_upload is not None:
        commercial_id = invoice_upload.id

    current_role = _current_role(invoice)
    if current_role is None:
        from app.services.classification.document_type_catalog import get_document_type_definition
        from app.services.classification.document_type_register_roles import (
            sales_register_role_for_definition,
        )

        definition = get_document_type_definition(
            invoice.document_type_code or "",
            document_types=document_types,
            tenant_id=invoice.tenant_id,
        )
        inferred = sales_register_role_for_definition(definition)
        if inferred in _ROLE_LABELS:
            current_role = inferred

    if current_role == SalesDocumentType.SO.value and so_doc_id is None:
        so_doc_id = invoice.id
    elif current_role == SalesDocumentType.DN.value and dn_doc_id is None:
        dn_doc_id = invoice.id
    elif current_role == SalesDocumentType.INVOICE.value and commercial_id is None:
        commercial_id = invoice.id

    commercial_match_id = commercial_id
    if commercial_match_id is None and current_role == SalesDocumentType.INVOICE.value:
        commercial_match_id = invoice.id

    if dn_doc_id is None and commercial_match_id is not None:
        loaded_commercial = await _invoice_by_id(session, commercial_match_id)
        if loaded_commercial and loaded_commercial.invoice_no:
            from app.services.extraction.invoice_no_sanitizer import INVOICE_NO_SECONDARY_KEY

            extracted = loaded_commercial.extracted_fields or {}
            secondary = (
                extracted.get(INVOICE_NO_SECONDARY_KEY) if isinstance(extracted, dict) else None
            )
            dn_matches = await find_dn_invoices_by_invoice_no(
                session,
                tenant_id=invoice.tenant_id,
                invoice_no=loaded_commercial.invoice_no,
                invoice_no_secondary=str(secondary) if secondary else None,
                sales_order_id=so_row.id if so_row is not None else None,
            )
            if dn_matches:
                dn_doc_id = dn_matches[0].id

    invoice_ids = {i for i in (so_doc_id, dn_doc_id, commercial_id) if i is not None}
    if commercial_match_id is not None:
        invoice_ids.add(commercial_match_id)

    loaded = await _invoices_by_id(session, invoice_ids)
    so_doc = loaded.get(so_doc_id) if so_doc_id is not None else None
    dn_doc = loaded.get(dn_doc_id) if dn_doc_id is not None else None
    commercial_doc = loaded.get(commercial_id) if commercial_id is not None else None

    members = [
        _member(SalesDocumentType.SO.value, so_doc, current_invoice_id=invoice.id, verify_stored_file=verify_stored_file),
        _member(SalesDocumentType.DN.value, dn_doc, current_invoice_id=invoice.id, verify_stored_file=verify_stored_file),
        _member(
            SalesDocumentType.INVOICE.value,
            commercial_doc,
            current_invoice_id=invoice.id,
            verify_stored_file=verify_stored_file,
        ),
    ]

    match: ThreeWayMatchResult | None = None
    match_status: str | None = None
    match_summary: DossierMatchSummaryResponse | None = None
    sales_register = None
    sales_order_id: int | None = None

    if so_row is not None:
        sales_order_id = so_row.id
        commercial_for_match = (
            loaded.get(commercial_match_id) if commercial_match_id is not None else None
        )
        if commercial_for_match is None and so_row.invoice_id is not None:
            commercial_for_match = loaded.get(so_row.invoice_id)
            if commercial_for_match is None:
                commercial_for_match = await _invoice_by_id(session, so_row.invoice_id)
        sales_register = sales_order_to_response(
            so_row,
            commercial_for_match,
            config=config,
        )
        match = sales_register.match
        match_status = match.status

    return SalesDossierResponse(
        so_reference=so_reference,
        current_role=current_role,
        members=members,
        sales_order_id=sales_order_id,
        match=match,
        match_status=match_status,
        match_summary=match_summary,
        sales_register=sales_register,
    )
