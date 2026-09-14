"""Org-metadata → ExtractionRoute (no hardcoded DT-code matrix)."""

from __future__ import annotations

from app.schemas.document_type import DocumentTypeDefinition
from app.services.extraction.routing.routes import ExtractionRoute

# Org playbook_profile → extraction route
_PLAYBOOK_ROUTE_MAP: dict[str, ExtractionRoute] = {
    "po_goods": ExtractionRoute.INVOICE,
    "standard_transactional": ExtractionRoute.INVOICE,
    "direct_expense": ExtractionRoute.INVOICE,
    "freight_logistics": ExtractionRoute.INVOICE,
    "intercompany": ExtractionRoute.INVOICE,
    "ar_goods": ExtractionRoute.INVOICE,
    "credit_adjustment": ExtractionRoute.CREDIT_NOTE,
    "debit_note": ExtractionRoute.DEBIT_NOTE,
    "employee_claim": ExtractionRoute.EXPENSE_CLAIM,
    "reconciliation": ExtractionRoute.STATEMENT,
    "supporting": ExtractionRoute.SUPPORTING_DOCUMENT,
    "pre_transactional": ExtractionRoute.SUPPORTING_DOCUMENT,
    "import_dossier": ExtractionRoute.SUPPORTING_DOCUMENT,
    "informational": ExtractionRoute.SUPPORTING_DOCUMENT,
    "master_data": ExtractionRoute.SUPPORTING_DOCUMENT,
    "non_actionable": ExtractionRoute.SUPPORTING_DOCUMENT,
    "compliance_route": ExtractionRoute.SUPPORTING_DOCUMENT,
}

_INVOICE_DI_PROFILES = frozenset({"prebuilt-invoice", "invoice"})
_RECEIPT_DI_PROFILES = frozenset({"prebuilt-receipt", "receipt"})


def azure_di_profile_for_dt(
    confirmed_dt: str,
    dt_definition: DocumentTypeDefinition | None,
) -> str:
    """Org records do not carry azure_di_profile — routing uses playbook/bundle roles."""
    return ""


def route_from_bundle_roles(
    dt_definition: DocumentTypeDefinition | None,
) -> tuple[ExtractionRoute | None, list[str]]:
    if dt_definition is None:
        return None, []
    purchase_role = (dt_definition.purchase_bundle_role or "").strip().lower()
    sales_role = (dt_definition.sales_bundle_role or "").strip().lower()
    if purchase_role == "po":
        return ExtractionRoute.PURCHASE_ORDER, ["purchase_bundle_role=po"]
    if purchase_role == "grn":
        return ExtractionRoute.GRN, ["purchase_bundle_role=grn"]
    if sales_role in {"so", "dn"}:
        return ExtractionRoute.SUPPORTING_DOCUMENT, [f"sales_bundle_role={sales_role}"]
    return None, []


def route_from_playbook(playbook: str) -> tuple[ExtractionRoute | None, list[str]]:
    token = (playbook or "").strip().lower()
    if not token:
        return None, []
    mapped = _PLAYBOOK_ROUTE_MAP.get(token)
    if mapped is None:
        return None, [f"playbook_unmapped={token}"]
    return mapped, [f"playbook={token}->{mapped.value}"]


def route_from_azure_di_profile(profile: str) -> tuple[ExtractionRoute | None, list[str]]:
    token = (profile or "").strip().lower()
    if not token:
        return None, []
    if token in _INVOICE_DI_PROFILES:
        return ExtractionRoute.INVOICE, [f"azure_di_profile={token}"]
    if token in _RECEIPT_DI_PROFILES:
        return ExtractionRoute.RECEIPT, [f"azure_di_profile={token}"]
    return None, [f"azure_di_profile_ignored={token}"]


def route_from_title_hints(
    dt_definition: DocumentTypeDefinition | None,
) -> tuple[ExtractionRoute | None, list[str]]:
    """Soft fallback from org title/short_title when profile metadata is empty."""
    if dt_definition is None:
        return None, []
    blob = " ".join(
        [
            str(dt_definition.title or ""),
            str(dt_definition.short_title or ""),
        ]
    ).lower()
    if not blob.strip():
        return None, []
    checks: list[tuple[tuple[str, ...], ExtractionRoute]] = [
        (("credit note", "credit memo", "credit note"), ExtractionRoute.CREDIT_NOTE),
        (("debit note",), ExtractionRoute.DEBIT_NOTE),
        (("remittance", "payment advice", "payment advice"), ExtractionRoute.REMITTANCE),
        (("statement", "vendor statement", "account statement"), ExtractionRoute.STATEMENT),
        (("goods received", "grn", "delivery docket"), ExtractionRoute.GRN),
        (("purchase order",), ExtractionRoute.PURCHASE_ORDER),
        (("expense claim", "reimbursement", "employee expense"), ExtractionRoute.EXPENSE_CLAIM),
        (("receipt",), ExtractionRoute.RECEIPT),
        (("tax invoice", "sales invoice", "invoice"), ExtractionRoute.INVOICE),
    ]
    normalized = f" {blob} "
    for needles, route in checks:
        if any(n in blob for n in needles):
            return route, [f"title_hint->{route.value}"]
    # Word-boundary PO (avoids matching inside other words)
    if " purchase order " in normalized or " po " in normalized or blob.strip() in {"po", "p.o.", "p.o"}:
        return ExtractionRoute.PURCHASE_ORDER, ["title_hint->purchase_order"]
    return None, []


def allow_invoice_model_for_org(
    *,
    route: ExtractionRoute,
    playbook: str,
    azure_di_profile: str,
) -> bool:
    """Expense claims may use invoice model when org DI profile says so."""
    if route != ExtractionRoute.EXPENSE_CLAIM:
        return False
    profile = (azure_di_profile or "").strip().lower()
    if profile in _INVOICE_DI_PROFILES:
        return True
    # employee_claim playbook historically used prebuilt-invoice for tax-invoice shaped claims
    return (playbook or "").strip().lower() == "employee_claim"


def resolve_org_extraction_route(
    *,
    confirmed_dt: str,
    dt_definition: DocumentTypeDefinition | None,
    playbook: str,
) -> tuple[ExtractionRoute, list[str], bool]:
    """
    Resolve route from org DT metadata only.

    Priority:
      1. purchase/sales bundle roles
      2. org playbook_profile
      3. catalog azure_di_profile
      4. title/short_title soft hints
      5. unknown
    """
    reasons: list[str] = []

    route, role_reasons = route_from_bundle_roles(dt_definition)
    reasons.extend(role_reasons)
    if route is not None:
        di_profile = azure_di_profile_for_dt(confirmed_dt, dt_definition)
        allow = allow_invoice_model_for_org(
            route=route, playbook=playbook, azure_di_profile=di_profile
        )
        return route, reasons, allow

    route, playbook_reasons = route_from_playbook(playbook)
    reasons.extend(playbook_reasons)
    if route is not None:
        di_profile = azure_di_profile_for_dt(confirmed_dt, dt_definition)
        # Remittance: supporting playbook + remittance title → remittance
        if route == ExtractionRoute.SUPPORTING_DOCUMENT:
            title_route, title_reasons = route_from_title_hints(dt_definition)
            if title_route in {
                ExtractionRoute.REMITTANCE,
                ExtractionRoute.STATEMENT,
                ExtractionRoute.PURCHASE_ORDER,
                ExtractionRoute.GRN,
            }:
                reasons.extend(title_reasons)
                route = title_route
        allow = allow_invoice_model_for_org(
            route=route, playbook=playbook, azure_di_profile=di_profile
        )
        return route, reasons, allow

    di_profile = azure_di_profile_for_dt(confirmed_dt, dt_definition)
    route, di_reasons = route_from_azure_di_profile(di_profile)
    reasons.extend(di_reasons)
    if route is not None:
        allow = allow_invoice_model_for_org(
            route=route, playbook=playbook, azure_di_profile=di_profile
        )
        return route, reasons, allow

    route, title_reasons = route_from_title_hints(dt_definition)
    reasons.extend(title_reasons)
    if route is not None:
        allow = allow_invoice_model_for_org(
            route=route, playbook=playbook, azure_di_profile=di_profile
        )
        return route, reasons, allow

    reasons.append("org_metadata_insufficient")
    return ExtractionRoute.UNKNOWN, reasons, False
