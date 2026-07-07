"""Build dossier linked-documents panel from sales/purchase dossier + playbook bundle."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import Invoice, PurchaseDocumentType, SalesDocumentType
from app.schemas.document_type import DocumentTypeDefinition
from app.schemas.dossier import (
    DossierLinkedDocumentResponse,
    DossierLinkedDocumentsResponse,
    DossierMatchSummaryResponse,
)
from app.services.dossier.document_ref_service import display_document_ref, dossier_public_id
from app.services.classification.document_type_catalog import ROUTE_SALES
from app.services.classification.document_type_playbook_profile_service import should_enforce_bundle_mandatory
from app.services.classification.document_type_playbook_service import invoice_dt_present_by_invoice_no, split_bundle_items
from app.services.dossier.dossier_manual_link_service import apply_manual_links
from app.services.purchase.po_reference import is_plausible_po_reference
from app.services.purchase.purchase_dossier_service import build_purchase_dossier
from app.services.sales.sales_dossier_service import build_sales_dossier
from app.services.sales.so_reference import is_plausible_so_reference, resolve_so_reference_from_invoice

_ROLE_TO_DT = {
    PurchaseDocumentType.PO.value: ("DT-14", "Purchase order"),
    PurchaseDocumentType.GRN.value: ("DT-15", "Goods receipt"),
    PurchaseDocumentType.INVOICE.value: ("DT-01", "Commercial invoice"),
}

_PURCHASE_BUNDLE_ROLE = {
    PurchaseDocumentType.PO.value: "po",
    PurchaseDocumentType.GRN.value: "grn",
    PurchaseDocumentType.INVOICE.value: "invoice",
}

_SALES_BUNDLE_ROLE = {
    SalesDocumentType.SO.value: "so",
    SalesDocumentType.DN.value: "dn",
    SalesDocumentType.INVOICE.value: "invoice",
}

_SALES_ROLE_FALLBACK_DT = {
    SalesDocumentType.SO.value: ("DT-27", "Sales order"),
    SalesDocumentType.DN.value: ("DT-28", "Delivery note"),
    SalesDocumentType.INVOICE.value: ("DT-26", "Customer invoice"),
}


def _dossier_id_for_invoice(inv: Invoice) -> str:
    return dossier_public_id(inv)


def _dt_label(code: str, document_types: list[DocumentTypeDefinition]) -> str:
    for row in document_types:
        if row.code.upper() == code.upper():
            return row.title or row.short_title or code
    return code


def _anchor_document_type(
    invoice: Invoice,
    document_types: list[DocumentTypeDefinition],
) -> tuple[str, str]:
    code = (invoice.document_type_code or "").strip().upper()
    if not code:
        return "", "Unclassified"
    return code, _dt_label(code, document_types)


def _is_sales_dossier_invoice(
    invoice: Invoice,
    definition: DocumentTypeDefinition | None,
) -> bool:
    route = (invoice.route_target or (definition.route_target if definition else None) or "").strip()
    if route == ROUTE_SALES:
        return True
    profile = ((definition.playbook_profile if definition else None) or "").strip().lower()
    return profile == "ar_goods"


def _dt_for_sales_role(
    role: str,
    document_types: list[DocumentTypeDefinition],
) -> tuple[str, str]:
    token = (role or "").strip().lower()
    for row in document_types:
        if (row.sales_bundle_role or "").strip().lower() == token:
            label = (row.title or row.short_title or row.code).strip() or row.code
            return row.code.upper(), label
    return _SALES_ROLE_FALLBACK_DT.get(token, (token.upper(), token))


def _linked_dossier_id(
    *,
    anchor_id: str,
    member_invoice_id: int | None,
    member_document_ref: str | None,
    is_current: bool,
) -> str | None:
    if member_invoice_id is None:
        return None
    if is_current:
        return anchor_id
    if member_document_ref and member_document_ref != "—":
        return member_document_ref
    return f"DOC-{member_invoice_id}"


async def _finalize_linked_documents(
    session: AsyncSession,
    invoice: Invoice,
    response: DossierLinkedDocumentsResponse,
    document_types: list[DocumentTypeDefinition],
    *,
    linkage_cache=None,
) -> DossierLinkedDocumentsResponse:
    from app.services.dossier.dossier_service import (
        append_invoice_no_linked_documents,
        append_reference_linked_documents,
    )

    enriched = await append_invoice_no_linked_documents(
        session,
        invoice,
        response,
        document_types=document_types,
        linkage_cache=linkage_cache,
    )
    enriched = await append_reference_linked_documents(
        session,
        invoice,
        enriched,
        document_types=document_types,
        linkage_cache=linkage_cache,
    )
    return await apply_manual_links(
        session,
        tenant_id=invoice.tenant_id,
        anchor_invoice_id=invoice.id,
        response=enriched,
        document_types=document_types,
    )


async def _build_invoice_no_linked_documents(
    session: AsyncSession,
    invoice: Invoice,
    *,
    document_types: list[DocumentTypeDefinition],
) -> DossierLinkedDocumentsResponse | None:
    """Automatic advisory bundle when sibling uploads share the same invoice_no."""
    invoice_no = (invoice.invoice_no or "").strip()
    if not invoice_no:
        return None
    from app.services.dossier.dossier_service import fetch_linked_invoices_by_invoice_no

    siblings = await fetch_linked_invoices_by_invoice_no(session, invoice)
    if not siblings:
        return None

    anchor_id = _dossier_id_for_invoice(invoice)
    documents: list[DossierLinkedDocumentResponse] = []

    def _row_doc(row: Invoice, *, is_anchor: bool) -> DossierLinkedDocumentResponse:
        code, label = _anchor_document_type(row, document_types)
        return DossierLinkedDocumentResponse(
            id=f"invoice-no-{row.id}",
            document_type_code=code,
            label=label,
            document_ref=display_document_ref(row),
            invoice_no=invoice_no,
            present=True,
            requirement="advisory",
            linked_dossier_id=anchor_id if is_anchor else dossier_public_id(row),
            invoice_id=row.id,
            is_anchor=is_anchor,
            has_file=bool(row.raw_file_path),
            linkage_detail=f"Linked on invoice no {invoice_no}",
            link_kind="system" if is_anchor else "invoice_no",
        )

    documents.append(_row_doc(invoice, is_anchor=True))
    for row in siblings:
        documents.append(_row_doc(row, is_anchor=False))

    return DossierLinkedDocumentsResponse(
        linkage_kind="invoice_no",
        linkage_key=invoice_no,
        linkage_label=f"Invoice no · {invoice_no}",
        enforce_bundle=False,
        documents=documents,
    )


async def build_dossier_linked_documents(
    session: AsyncSession,
    invoice: Invoice,
    *,
    definition: DocumentTypeDefinition | None,
    document_types: list[DocumentTypeDefinition] | None = None,
    linkage_cache=None,
) -> DossierLinkedDocumentsResponse:
    if document_types is None:
        from app.services.invoice.invoice_evaluation_service import load_posting_config_for_tenant

        document_types = (await load_posting_config_for_tenant(session, invoice.tenant_id)).document_types

    anchor_id = _dossier_id_for_invoice(invoice)
    po_ref = (invoice.po_reference or "").strip() or None
    so_ref = resolve_so_reference_from_invoice(invoice)

    if (
        _is_sales_dossier_invoice(invoice, definition)
        and so_ref
        and is_plausible_so_reference(so_ref)
    ):
        sales = await build_sales_dossier(session, invoice, verify_stored_file=False)
        documents: list[DossierLinkedDocumentResponse] = []
        for member in sales.members:
            if member.is_current:
                dt_code, default_label = _anchor_document_type(invoice, document_types)
            else:
                dt_code, default_label = _dt_for_sales_role(member.role, document_types)
            linked_id = _linked_dossier_id(
                anchor_id=anchor_id,
                member_invoice_id=member.invoice_id,
                member_document_ref=member.document_ref,
                is_current=member.is_current,
            )
            sales_role = _SALES_BUNDLE_ROLE.get(member.role)
            documents.append(
                DossierLinkedDocumentResponse(
                    id=f"{dt_code or member.role}-bundle-{member.role}",
                    document_type_code=dt_code,
                    label=default_label if member.is_current else (member.label or default_label),
                    document_ref=member.document_ref,
                    present=member.present,
                    requirement="mandatory",
                    sales_bundle_role=sales_role,
                    source="erp_register" if member.present else None,
                    linked_dossier_id=linked_id,
                    invoice_id=member.invoice_id,
                    is_anchor=member.is_current,
                    has_file=member.has_stored_file,
                    linkage_detail=f"Linked on SO {so_ref}" if member.present else "VR-PB02 required",
                )
            )

        match_summary: DossierMatchSummaryResponse | None = None
        if sales.match is not None and sales.match_summary is not None:
            match_summary = sales.match_summary

        enforce = should_enforce_bundle_mandatory(definition) if definition else True
        return await _finalize_linked_documents(
            session,
            invoice,
            DossierLinkedDocumentsResponse(
                linkage_kind="so_reference",
                linkage_key=so_ref,
                linkage_label=f"SO reference · {so_ref}",
                enforce_bundle=enforce,
                documents=documents,
                match_summary=match_summary,
                sales_order_id=sales.sales_order_id,
            ),
            document_types,
            linkage_cache=linkage_cache,
        )

    if po_ref and is_plausible_po_reference(po_ref):
        purchase = await build_purchase_dossier(session, invoice, verify_stored_file=False)
        documents = []
        for member in purchase.members:
            if member.is_current:
                dt_code, default_label = _anchor_document_type(invoice, document_types)
            else:
                dt_code, default_label = _ROLE_TO_DT.get(
                    member.role, (member.role.upper(), member.label)
                )
            linked_id = _linked_dossier_id(
                anchor_id=anchor_id,
                member_invoice_id=member.invoice_id,
                member_document_ref=member.document_ref,
                is_current=member.is_current,
            )
            documents.append(
                DossierLinkedDocumentResponse(
                    id=f"{dt_code or member.role}-bundle-{member.role}",
                    document_type_code=dt_code,
                    label=default_label if member.is_current else (member.label or default_label),
                    document_ref=member.document_ref,
                    present=member.present,
                    requirement="mandatory",
                    purchase_bundle_role=_PURCHASE_BUNDLE_ROLE.get(member.role),
                    source="erp_register" if member.present else None,
                    linked_dossier_id=linked_id,
                    invoice_id=member.invoice_id,
                    is_anchor=member.is_current,
                    has_file=member.has_stored_file,
                    linkage_detail=f"Linked on {po_ref}" if member.present else "VR-PB02 required",
                )
            )

        match_summary = None
        if purchase.match is not None and purchase.match_summary is not None:
            match_summary = purchase.match_summary

        return await _finalize_linked_documents(
            session,
            invoice,
            DossierLinkedDocumentsResponse(
                linkage_kind="po_reference",
                linkage_key=po_ref,
                linkage_label=f"Linked on {po_ref}",
                enforce_bundle=True,
                documents=documents,
                match_summary=match_summary,
                purchase_order_id=purchase.purchase_order_id,
            ),
            document_types,
            linkage_cache=linkage_cache,
        )

    enforce = should_enforce_bundle_mandatory(definition) if definition else False
    mandatory_codes: list[str] = []
    advisories: list[str] = []
    if definition is not None:
        mandatory_codes, advisories = split_bundle_items(list(definition.bundle_mandatory or []))

    if mandatory_codes:
        anchor_code = (invoice.document_type_code or "").upper()
        invoice_no = (invoice.invoice_no or "").strip()
        linkage_key = so_ref if so_ref and is_plausible_so_reference(so_ref) else po_ref
        if not linkage_key and invoice_no:
            linkage_key = invoice_no
        documents = []
        for code in mandatory_codes:
            is_anchor = code == anchor_code
            present = is_anchor
            if not present and invoice_no:
                present = await invoice_dt_present_by_invoice_no(
                    session,
                    tenant_id=invoice.tenant_id,
                    invoice_no=invoice_no,
                    dt_code=code,
                    exclude_invoice_id=invoice.id,
                )
            documents.append(
                DossierLinkedDocumentResponse(
                    id=f"{code}-bundle",
                    document_type_code=code,
                    label=_dt_label(code, document_types),
                    document_ref=display_document_ref(invoice) if is_anchor else None,
                    invoice_no=invoice_no or None,
                    present=present,
                    requirement="mandatory",
                    linked_dossier_id=anchor_id if is_anchor else None,
                    invoice_id=invoice.id if is_anchor else None,
                    is_anchor=is_anchor,
                    has_file=bool(invoice.raw_file_path) if is_anchor else False,
                    linkage_detail=linkage_key or "Supporting document member",
                )
            )
        if linkage_key and is_plausible_so_reference(linkage_key):
            linkage_kind = "so_reference"
            linkage_label = f"SO reference · {linkage_key}"
        elif linkage_key and is_plausible_po_reference(linkage_key):
            linkage_kind = "po_reference"
            linkage_label = f"Linked on {linkage_key}"
        elif linkage_key and invoice_no and linkage_key == invoice_no:
            linkage_kind = "invoice_no"
            linkage_label = f"Invoice no · {invoice_no}"
        elif linkage_key:
            linkage_kind = "shipment_ref"
            linkage_label = linkage_key
        else:
            linkage_kind = "standalone"
            linkage_label = "Supporting document requirements"
        return await _finalize_linked_documents(
            session,
            invoice,
            DossierLinkedDocumentsResponse(
                linkage_kind=linkage_kind,
                linkage_key=linkage_key,
                linkage_label=linkage_label,
                enforce_bundle=enforce,
                conditional_advisories=advisories,
                documents=documents,
            ),
            document_types,
            linkage_cache=linkage_cache,
        )

    code, label = _anchor_document_type(invoice, document_types)
    invoice_no_bundle = await _build_invoice_no_linked_documents(
        session,
        invoice,
        document_types=document_types,
    )
    if invoice_no_bundle is not None:
        return await _finalize_linked_documents(
            session,
            invoice,
            invoice_no_bundle,
            document_types,
            linkage_cache=linkage_cache,
        )

    return await _finalize_linked_documents(
        session,
        invoice,
        DossierLinkedDocumentsResponse(
            linkage_kind="standalone",
            linkage_key=None,
            linkage_label="No external linkage key",
            enforce_bundle=False,
            documents=[
                DossierLinkedDocumentResponse(
                    id="anchor",
                    document_type_code=code,
                    label=label,
                    document_ref=display_document_ref(invoice),
                    invoice_no=(invoice.invoice_no or "").strip() or None,
                    present=True,
                    requirement="mandatory",
                    linked_dossier_id=anchor_id,
                    invoice_id=invoice.id,
                    is_anchor=True,
                    has_file=bool(invoice.raw_file_path),
                    linkage_detail="This dossier",
                )
            ],
        ),
        document_types,
        linkage_cache=linkage_cache,
    )
