"""Org DT → purchase/sales register roles (long-term source of truth).

Supporting bundle schema roles stay ``po|grn`` / ``so|dn`` (posting=No).
Commercial invoice legs are org DTs with ``po_goods`` / ``ar_goods`` playbooks
(not a ``*BundleRole: invoice`` field — that is not in the Rule Book schema).

Template DT codes (DT-01/02/03, DT-26/27/28) are last-resort fallbacks only when
the tenant catalogue has no matching enabled card.
"""

from __future__ import annotations

from typing import Literal

from app.schemas.document_type import DocumentTypeDefinition

RegisterSide = Literal["purchase", "sales"]
PurchaseRegisterRole = Literal["po", "grn", "invoice"]
SalesRegisterRole = Literal["so", "dn", "invoice"]

_AR_GOODS_PROFILES = frozenset({"ar_goods", "ar_goods_2way"})
_PO_GOODS_PROFILES = frozenset({"po_goods"})

# Shipped catalogue last-resort codes (must match v5 / document_types.json).
_PURCHASE_ROLE_FALLBACK: dict[str, tuple[str, str]] = {
    "po": ("DT-02", "Purchase order"),
    "grn": ("DT-03", "Goods receipt"),
    "invoice": ("DT-01", "Commercial invoice"),
}
_SALES_ROLE_FALLBACK: dict[str, tuple[str, str]] = {
    "so": ("DT-27", "Sales order"),
    "dn": ("DT-28", "Delivery note"),
    "invoice": ("DT-26", "Customer invoice"),
}

_POSTING_YES = frozenset({"yes", "y", "true", "1"})


def _posting_yes(definition: DocumentTypeDefinition) -> bool:
    return (definition.posting or "").strip().lower() in _POSTING_YES


def _label(definition: DocumentTypeDefinition) -> str:
    return f"{definition.short_title or ''} {definition.title or ''}".lower()


def infer_purchase_supporting_role(definition: DocumentTypeDefinition | None) -> str:
    """Supporting purchase bundle roles only: po | grn."""
    if definition is None:
        return ""
    explicit = (definition.purchase_bundle_role or "").strip().lower()
    if explicit in {"po", "grn"}:
        return explicit
    # Explicit sales supporting roles must not be re-read as purchase GRN from title.
    sales_explicit = (definition.sales_bundle_role or "").strip().lower()
    if sales_explicit in {"so", "dn"}:
        return ""
    label = _label(definition)
    if any(
        token in label
        for token in (
            "grn",
            "goods receipt",
            "delivery receipt",
            "proof of delivery",
            "receipt note",
        )
    ):
        return "grn"
    if "invoice" in label or "tax inv" in label:
        return ""
    if "purchase order" in label:
        return "po"
    import re

    if re.search(r"\bpo\s*(copy|\(|document|form)\b", label):
        return "po"
    short = (definition.short_title or "").strip().lower()
    if short in {"po", "p.o.", "p.o"}:
        return "po"
    return ""


def infer_sales_supporting_role(definition: DocumentTypeDefinition | None) -> str:
    """Supporting sales bundle roles only: so | dn."""
    if definition is None:
        return ""
    explicit = (definition.sales_bundle_role or "").strip().lower()
    if explicit in {"so", "dn"}:
        return explicit
    label = _label(definition)
    if any(token in label for token in ("delivery note", "dispatch", "dn ")):
        return "dn"
    if any(token in label for token in ("sales order", "so ", "so-")):
        return "so"
    return ""


def purchase_register_role_for_definition(definition: DocumentTypeDefinition | None) -> str:
    """Purchase register role for an org DT: po | grn | invoice | ''."""
    if definition is None:
        return ""
    supporting = infer_purchase_supporting_role(definition)
    if supporting:
        return supporting
    from app.services.classification.document_type_playbook_profile_service import (
        effective_playbook_profile,
    )

    profile = (effective_playbook_profile(definition) or "").strip().lower()
    if profile in _PO_GOODS_PROFILES:
        return "invoice"
    route = (definition.route_target or "").strip()
    if (
        route == "Purchase Management"
        and _posting_yes(definition)
        and profile not in {"supporting", "direct_expense"}
    ):
        label = _label(definition)
        if any(
            token in label
            for token in (
                "commercial invoice",
                "tax invoice",
                "vendor invoice",
                "supplier invoice",
                "purchase invoice",
                "non-po vendor",
                "non po vendor",
            )
        ):
            return "invoice"
    return ""


def sales_register_role_for_definition(definition: DocumentTypeDefinition | None) -> str:
    """Sales register role for an org DT: so | dn | invoice | ''."""
    if definition is None:
        return ""
    supporting = infer_sales_supporting_role(definition)
    if supporting:
        return supporting
    from app.services.classification.document_type_playbook_profile_service import (
        effective_playbook_profile,
    )

    profile = (effective_playbook_profile(definition) or "").strip().lower()
    if profile in _AR_GOODS_PROFILES:
        return "invoice"
    route = (definition.route_target or "").strip()
    if route == "Sales Management" and _posting_yes(definition) and profile != "supporting":
        label = _label(definition)
        if any(
            token in label
            for token in (
                "customer invoice",
                "customer tax",
                "tax invoice",
                "sales invoice",
                "ar invoice",
                "commercial invoice",
            )
        ):
            return "invoice"
    return ""


def register_role_for_definition(
    definition: DocumentTypeDefinition | None,
    *,
    side: RegisterSide,
) -> str:
    if side == "purchase":
        return purchase_register_role_for_definition(definition)
    return sales_register_role_for_definition(definition)


def _commercial_definitions(
    document_types: list[DocumentTypeDefinition] | None,
    *,
    side: RegisterSide,
) -> list[DocumentTypeDefinition]:
    if not document_types:
        return []
    out: list[DocumentTypeDefinition] = []
    seen: set[str] = set()
    for row in document_types:
        if not row.enabled:
            continue
        if register_role_for_definition(row, side=side) != "invoice":
            continue
        code = (row.code or "").strip().upper()
        if not code or code in seen:
            continue
        seen.add(code)
        out.append(row)
    return out


def purchase_commercial_invoice_definitions(
    document_types: list[DocumentTypeDefinition] | None,
) -> list[DocumentTypeDefinition]:
    return _commercial_definitions(document_types, side="purchase")


def sales_commercial_invoice_definitions(
    document_types: list[DocumentTypeDefinition] | None,
) -> list[DocumentTypeDefinition]:
    return _commercial_definitions(document_types, side="sales")


def purchase_commercial_invoice_dt_codes(
    document_types: list[DocumentTypeDefinition] | None,
) -> list[str]:
    return [
        (row.code or "").strip().upper()
        for row in purchase_commercial_invoice_definitions(document_types)
        if (row.code or "").strip()
    ]


def sales_commercial_invoice_dt_codes(
    document_types: list[DocumentTypeDefinition] | None,
) -> list[str]:
    return [
        (row.code or "").strip().upper()
        for row in sales_commercial_invoice_definitions(document_types)
        if (row.code or "").strip()
    ]


def dt_code_for_register_role(
    *,
    side: RegisterSide,
    role: str,
    document_types: list[DocumentTypeDefinition] | None,
) -> tuple[str, str]:
    """Resolve (code, label) for a register slot from the org catalogue.

    Template fallbacks are last resort only.
    """
    token = (role or "").strip().lower()
    fallback = (
        _PURCHASE_ROLE_FALLBACK if side == "purchase" else _SALES_ROLE_FALLBACK
    ).get(token, (token.upper(), token))

    if not document_types:
        return fallback

    if token == "invoice":
        commercials = _commercial_definitions(document_types, side=side)
        if commercials:
            row = commercials[0]
            label = (row.title or row.short_title or row.code).strip() or row.code
            return row.code.upper(), label
        # Prefer shipped commercial code if still present in catalogue.
        want = fallback[0]
        for row in document_types:
            if row.enabled and (row.code or "").strip().upper() == want:
                label = (row.title or row.short_title or row.code).strip() or row.code
                return want, label
        return fallback

    for row in document_types:
        if not row.enabled:
            continue
        if register_role_for_definition(row, side=side) == token:
            label = (row.title or row.short_title or row.code).strip() or row.code
            return row.code.upper(), label

    want = fallback[0]
    for row in document_types:
        if row.enabled and (row.code or "").strip().upper() == want:
            label = (row.title or row.short_title or row.code).strip() or row.code
            return want, label
    return fallback
