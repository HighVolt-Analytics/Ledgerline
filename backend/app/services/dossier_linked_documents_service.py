"""Build dossier linked-documents panel from purchase dossier + playbook bundle."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import Invoice, PurchaseDocumentType
from app.schemas.document_type import DocumentTypeDefinition
from app.schemas.dossier import (
    DossierLinkedDocumentResponse,
    DossierLinkedDocumentsResponse,
    DossierMatchSummaryResponse,
)
from app.services.document_ref_service import display_document_ref, dossier_public_id
from app.services.document_type_playbook_profile_service import should_enforce_bundle_mandatory
from app.services.document_type_playbook_service import split_bundle_items
from app.services.invoice_evaluation_service import load_config_for_tenant
from app.services.po_reference import is_plausible_po_reference
from app.services.purchase_dossier_service import build_purchase_dossier

_ROLE_TO_DT = {
    PurchaseDocumentType.PO.value: ("DT-14", "Purchase order"),
    PurchaseDocumentType.GRN.value: ("DT-15", "Goods receipt"),
    PurchaseDocumentType.INVOICE.value: ("DT-01", "Commercial invoice"),
}

_BUNDLE_ROLE = {
    PurchaseDocumentType.PO.value: "po",
    PurchaseDocumentType.GRN.value: "grn",
    PurchaseDocumentType.INVOICE.value: "invoice",
}


def _dossier_id_for_invoice(inv: Invoice) -> str:
    return dossier_public_id(inv)


def _dt_label(code: str, document_types: list[DocumentTypeDefinition]) -> str:
    for row in document_types:
        if row.code.upper() == code.upper():
            return row.short_title or row.title or code
    return code


async def build_dossier_linked_documents(
    session: AsyncSession,
    invoice: Invoice,
    *,
    definition: DocumentTypeDefinition | None,
) -> DossierLinkedDocumentsResponse:
    anchor_id = _dossier_id_for_invoice(invoice)
    po_ref = (invoice.po_reference or "").strip() or None

    if po_ref and is_plausible_po_reference(po_ref):
        purchase = await build_purchase_dossier(session, invoice)
        documents: list[DossierLinkedDocumentResponse] = []
        for member in purchase.members:
            dt_code, default_label = _ROLE_TO_DT.get(member.role, (member.role.upper(), member.label))
            linked_id = None
            if member.invoice_id is not None:
                if member.is_current:
                    linked_id = anchor_id
                elif member.document_ref and member.document_ref != "—":
                    linked_id = member.document_ref
                elif member.invoice_id is not None:
                    linked_id = f"DOC-{member.invoice_id}"
            documents.append(
                DossierLinkedDocumentResponse(
                    id=f"{dt_code}-{member.role}",
                    document_type_code=dt_code,
                    label=member.label or default_label,
                    document_ref=member.document_ref,
                    present=member.present,
                    requirement="mandatory",
                    purchase_bundle_role=_BUNDLE_ROLE.get(member.role),
                    source="erp_register" if member.present else None,
                    linked_dossier_id=linked_id,
                    is_anchor=member.is_current,
                    has_file=member.has_stored_file,
                    linkage_detail=f"Linked on {po_ref}" if member.present else "VR-PB01 required",
                )
            )

        match_summary = None
        if purchase.match is not None:
            po_value = float(purchase.match.po_value or 0)
            invoice_total = float(purchase.match.invoice_total or 0)
            match_summary = DossierMatchSummaryResponse(
                status=purchase.match_status or purchase.match.status,
                po_value=po_value,
                invoice_total=invoice_total,
                deviation=invoice_total - po_value,
                currency=(invoice.currency or "AUD").strip() or "AUD",
            )

        return DossierLinkedDocumentsResponse(
            linkage_kind="po_reference",
            linkage_key=po_ref,
            linkage_label=f"Linked on {po_ref}",
            enforce_bundle=True,
            documents=documents,
            match_summary=match_summary,
            purchase_order_id=purchase.purchase_order_id,
        )

    config = load_config_for_tenant(invoice.tenant_id)
    document_types = config.document_types
    enforce = should_enforce_bundle_mandatory(definition) if definition else False
    mandatory_codes: list[str] = []
    advisories: list[str] = []
    if definition is not None:
        mandatory_codes, advisories = split_bundle_items(list(definition.bundle_mandatory or []))

    if mandatory_codes:
        documents = [
            DossierLinkedDocumentResponse(
                id=f"{code}-bundle",
                document_type_code=code,
                label=_dt_label(code, document_types),
                document_ref=display_document_ref(invoice) if code == (invoice.document_type_code or "").upper() else None,
                present=code == (invoice.document_type_code or "").upper(),
                requirement="mandatory",
                linked_dossier_id=anchor_id if code == (invoice.document_type_code or "").upper() else None,
                is_anchor=code == (invoice.document_type_code or "").upper(),
                has_file=bool(invoice.raw_file_path),
                linkage_detail=po_ref or "Bundle member",
            )
            for code in mandatory_codes
        ]
        linkage_kind = "shipment_ref" if po_ref else "standalone"
        return DossierLinkedDocumentsResponse(
            linkage_kind=linkage_kind,
            linkage_key=po_ref,
            linkage_label=po_ref or "Playbook bundle",
            enforce_bundle=enforce,
            conditional_advisories=advisories,
            documents=documents,
        )

    code = (invoice.document_type_code or "DT-01").strip().upper() or "DT-01"
    return DossierLinkedDocumentsResponse(
        linkage_kind="standalone",
        linkage_key=None,
        linkage_label="No external linkage key",
        enforce_bundle=False,
        documents=[
            DossierLinkedDocumentResponse(
                id="anchor",
                document_type_code=code,
                label=_dt_label(code, document_types),
                document_ref=display_document_ref(invoice),
                present=True,
                requirement="mandatory",
                linked_dossier_id=anchor_id,
                is_anchor=True,
                has_file=bool(invoice.raw_file_path),
                linkage_detail="This dossier",
            )
        ],
    )
