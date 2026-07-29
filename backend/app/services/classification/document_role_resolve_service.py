"""Resolve purchase/sales document roles before DT catalogue scoring.

Role is the finance primitive (po/grn/invoice/so/dn). Org DT codes are selected
only inside the role-filtered catalogue so remapped titles cannot turn a PO
into a commercial ``po_goods`` invoice DT.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from app.schemas.document_type import DocumentTypeDefinition
from app.services.classification.document_type_playbook_profile_service import (
    effective_playbook_profile,
)
from app.services.classification.document_type_register_roles import (
    infer_purchase_supporting_role as _infer_purchase_bundle_role,
    infer_sales_supporting_role as _infer_sales_bundle_role,
    sales_register_role_for_definition,
)

DocumentRole = str  # po | grn | invoice | so | dn

_ROUTE_SALES = "Sales Management"
_ROUTE_PURCHASE = "Purchase Management"

_HEADING_TO_ROLE: dict[str, DocumentRole] = {
    "purchase_order": "po",
    "grn": "grn",
    "invoice": "invoice",
    "tax_invoice": "invoice",
    "commercial_invoice": "invoice",
    "proforma": "invoice",
    "credit_note": "invoice",
    "sales_order": "so",
    "delivery_note": "dn",
}


def role_from_heading_kind(heading_kind: str | None) -> DocumentRole | None:
    if not heading_kind:
        return None
    return _HEADING_TO_ROLE.get(str(heading_kind).strip().lower())


def resolve_document_role(
    *,
    heading_kind: str | None = None,
    filename: str | None = None,
    invoice: Any | None = None,
    document_text: str | None = None,
) -> DocumentRole | None:
    """Resolve po/grn/invoice/so/dn from heading, filename, then field signatures."""
    from_heading = role_from_heading_kind(heading_kind)
    if from_heading:
        return from_heading

    name = (filename or "").strip()
    if name:
        from app.services.purchase.purchase_document_service import (
            _attachment_suggests_commercial_invoice as purchase_inv,
            _attachment_suggests_grn,
            _attachment_suggests_po,
        )
        from app.services.sales.sales_document_service import (
            _attachment_suggests_commercial_invoice as sales_inv,
            _attachment_suggests_dn,
            _attachment_suggests_so,
        )

        if _attachment_suggests_grn(name) or _attachment_suggests_dn(name):
            # Prefer purchase GRN token over DN when both match; DN hints include packing_list.
            if _attachment_suggests_grn(name) and not _attachment_suggests_dn(name):
                return "grn"
            if _attachment_suggests_dn(name) and not _attachment_suggests_grn(name):
                return "dn"
            if _attachment_suggests_grn(name):
                return "grn"
            return "dn"
        if purchase_inv(name) or sales_inv(name):
            return "invoice"
        if _attachment_suggests_po(name):
            return "po"
        if _attachment_suggests_so(name):
            return "so"

    if invoice is not None:
        from app.services.purchase.purchase_document_service import infer_purchase_document_type
        from app.services.sales.sales_document_service import infer_sales_document_type

        # Prefer explicit stored roles.
        stored_purchase = (getattr(invoice, "purchase_document_type", None) or "").strip().lower()
        if stored_purchase in {"po", "grn", "invoice"}:
            return stored_purchase
        stored_sales = (getattr(invoice, "sales_document_type", None) or "").strip().lower()
        if stored_sales in {"so", "dn", "invoice"}:
            return stored_sales

        # Temporarily attach document text for inference when provided.
        prior_text = getattr(invoice, "document_text", None)
        if document_text and not (prior_text or "").strip():
            try:
                invoice.document_text = document_text
            except Exception:
                pass
        try:
            purchase_role = infer_purchase_document_type(invoice)
            if purchase_role:
                return purchase_role
            sales_role = infer_sales_document_type(invoice)
            if sales_role:
                return sales_role
        finally:
            if document_text and prior_text is not None:
                try:
                    invoice.document_text = prior_text
                except Exception:
                    pass

    return None


def definition_matches_role(definition: DocumentTypeDefinition, role: DocumentRole) -> bool:
    """True when the DT card is eligible for the resolved document role."""
    from app.services.classification.document_type_register_roles import (
        purchase_register_role_for_definition,
        sales_register_role_for_definition,
    )

    purchase_role = _infer_purchase_bundle_role(definition)
    sales_role = _infer_sales_bundle_role(definition)
    register_purchase = purchase_register_role_for_definition(definition)
    register_sales = sales_register_role_for_definition(definition)
    playbook = (effective_playbook_profile(definition) or "").strip().lower()
    posting = (definition.posting or "").strip().lower()

    if role == "po":
        return purchase_role == "po" or register_purchase == "po"
    if role == "grn":
        return purchase_role == "grn" or register_purchase == "grn"
    if role == "so":
        return sales_role == "so" or register_sales == "so"
    if role == "dn":
        return sales_role == "dn" or register_sales == "dn"
    if role == "invoice":
        # Prefer explicit AR/AP commercial DTs; never supporting SO/DN/PO/GRN.
        if purchase_role in {"po", "grn"} or sales_role in {"so", "dn"}:
            return False
        if playbook == "supporting":
            return False
        if posting in {"no", "n"}:
            return False
        if register_sales == "invoice" or register_purchase == "invoice":
            return True
        # Broad transactional fallback for role-filtered catalogue scoring.
        return True
    return False


def filter_document_types_for_role(
    document_types: Sequence[DocumentTypeDefinition],
    role: DocumentRole | None,
) -> list[DocumentTypeDefinition]:
    """Return enabled DTs matching role, or all enabled when role is unknown."""
    enabled = [dt for dt in document_types if getattr(dt, "enabled", True)]
    if not role:
        return enabled
    matched = [dt for dt in enabled if definition_matches_role(dt, role)]
    return matched


def perspective_from_invoice(invoice: Any | None) -> str | None:
    if invoice is None:
        return None
    fields = getattr(invoice, "extracted_fields", None)
    if not isinstance(fields, dict):
        return None
    for key in ("perspective", "llm_perspective"):
        token = str(fields.get(key) or "").strip().lower()
        if token in {"sales", "purchase"}:
            return token
    return None


def filter_document_types_for_perspective(
    document_types: Sequence[DocumentTypeDefinition],
    perspective: str | None,
) -> list[DocumentTypeDefinition]:
    """Prefer Sales/Purchase route cards when vision perspective is known."""
    token = (perspective or "").strip().lower()
    if token not in {"sales", "purchase"}:
        return list(document_types)
    want = _ROUTE_SALES if token == "sales" else _ROUTE_PURCHASE
    preferred = [
        dt for dt in document_types if (dt.route_target or "").strip() == want
    ]
    return preferred or list(document_types)


def heading_role_conflicts_with_definition(
    heading_kind: str | None,
    definition: DocumentTypeDefinition,
) -> bool:
    """Hard conflicts that must not be bypassed by high title/metadata scores."""
    role = role_from_heading_kind(heading_kind)
    if not role:
        return False

    purchase_role = _infer_purchase_bundle_role(definition)
    sales_role = _infer_sales_bundle_role(definition)
    playbook = (effective_playbook_profile(definition) or "").strip().lower()

    if role == "po":
        return purchase_role != "po"

    if role == "grn":
        return purchase_role != "grn"

    if role == "so":
        return sales_role != "so"

    if role == "dn":
        return sales_role != "dn"

    if role == "invoice":
        if purchase_role in {"po", "grn"} or sales_role in {"so", "dn"}:
            return True
        if playbook == "supporting":
            return True
        return False

    return False
