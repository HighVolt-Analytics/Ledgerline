"""Extended invoice validation rules (VR09–VR16)."""

from __future__ import annotations

import re
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import Invoice
from app.models.purchase_order import PurchaseOrderStatus
from app.schemas.customer import CustomerMaster
from app.schemas.rule_book_config import RuleBookConfigPayload, VendorMaster
from app.services.invoice.invoice_data import InvoiceData
from app.services.invoice.invoice_evaluation_service import ROUTE_SALES
from app.services.purchase.purchase_match_service import load_purchase_order_for_invoice
from app.services.rule_book.tax_invoice_policy import (
    document_has_tax_invoice_wording,
    tax_invoice_policy_for_country,
)
from app.services.rule_book.validator import ValidationResult
from app.services.master_data.vendor_detection import (
    find_matching_customer_master,
    find_matching_vendor_master,
    normalize_abn_digits,
)

LINE_TOLERANCE = Decimal("0.05")
SUBTOTAL_TOLERANCE = Decimal("0.05")
PRICE_MATCH_PCT = Decimal("0.02")
PRICE_MATCH_CAP_AUD = Decimal("100")
FREIGHT_TOLERANCE_AUD = Decimal("100")
FUZZY_AMOUNT_PCT = Decimal("0.005")
FUZZY_DATE_DAYS = 7

_FREIGHT_KEYWORDS = re.compile(
    r"\b(freight|delivery|surcharge|shipping|carriage|handling)\b",
    re.I,
)
_BLOCKED_VENDOR_STATUSES = frozenset({"blocked", "inactive", "suspended", "closed"})


def _document_text(data: InvoiceData) -> str:
    return (data.document_text or "").strip()


def vr09_line_arithmetic(data: InvoiceData) -> ValidationResult:
    if not data.line_items:
        return ValidationResult("VR09", True, "No line items to reconcile")

    issues: list[str] = []
    line_sum = Decimal("0")
    for idx, line in enumerate(data.line_items):
        amount = line.amount
        if amount is not None:
            line_sum += amount
        if line.qty is not None and line.unit_price is not None:
            expected = (line.qty * line.unit_price).quantize(Decimal("0.01"))
            actual = (amount or Decimal("0")).quantize(Decimal("0.01"))
            if abs(actual - expected) > LINE_TOLERANCE:
                issues.append(f"line {idx + 1}: qty×price != amount")

    if data.subtotal is not None and line_sum > 0:
        if abs(line_sum - data.subtotal) > SUBTOTAL_TOLERANCE:
            issues.append("Σ lines != subtotal")

    if issues:
        return ValidationResult("VR09", False, "; ".join(issues))
    return ValidationResult("VR09", True, "Line arithmetic within tolerance")


def vr10_tax_invoice_wording(
    data: InvoiceData,
    *,
    country: str,
    currency: str,
) -> ValidationResult:
    policy = tax_invoice_policy_for_country(country)
    if policy is None:
        return ValidationResult(
            "VR10",
            True,
            f"Tax invoice wording rule not configured for {country or 'unknown country'}",
            skipped=True,
        )
    if not policy.enabled:
        return ValidationResult(
            "VR10",
            True,
            f"Tax invoice wording rule not applicable for {country}",
            skipped=True,
        )

    text = _document_text(data)
    has_wording = document_has_tax_invoice_wording(text, policy)
    subtotal = data.subtotal or data.total or Decimal("0")
    tax_amount = data.gst or Decimal("0")

    if policy.amount_threshold is not None and subtotal >= policy.amount_threshold and not has_wording:
        return ValidationResult(
            "VR10",
            False,
            f"Taxable supply ≥ {currency} {policy.amount_threshold} requires tax-invoice wording on document",
        )
    if policy.enforce_when_tax_present and tax_amount > 0 and not has_wording:
        return ValidationResult(
            "VR10",
            False,
            f"Tax charged but document does not state required tax-invoice wording for {country}",
        )
    if has_wording:
        return ValidationResult("VR10", True, "Tax-invoice wording stated on document")
    return ValidationResult("VR10", True, "Tax invoice wording rule not applicable")


def vr11_date_sanity(data: InvoiceData, *, today: date | None = None) -> ValidationResult:
    if data.invoice_date is None:
        return ValidationResult("VR11", False, "invoice_date required for date sanity")

    anchor = today or date.today()
    if data.invoice_date > anchor:
        return ValidationResult("VR11", False, "Invoice date cannot be in the future")

    age_days = (anchor - data.invoice_date).days
    if age_days > 365:
        return ValidationResult(
            "VR11",
            False,
            "Invoice older than 12 months — controller approval required",
        )
    return ValidationResult("VR11", True, "Invoice date within acceptable range")


def vr12_vendor_master(
    data: InvoiceData,
    *,
    vendor_masters: list[VendorMaster],
) -> ValidationResult:
    vendor_name = (data.vendor or "").strip()
    if not vendor_name:
        return ValidationResult("VR12", False, "Vendor name required for master check")

    if not vendor_masters:
        return ValidationResult(
            "VR12",
            False,
            "Vendor not registered — add vendor to master",
        )

    master = find_matching_vendor_master(vendor_name, data.abn, vendor_masters)
    if master is None:
        return ValidationResult(
            "VR12",
            False,
            "Vendor not found in vendor master",
        )

    status = (master.status or "").strip().lower()
    if status in _BLOCKED_VENDOR_STATUSES:
        return ValidationResult("VR12", False, f"Vendor master status is {master.status}")

    doc_abn = normalize_abn_digits(data.abn)
    master_abn = normalize_abn_digits(master.abn)
    if (
        doc_abn
        and master_abn
        and master_abn != "PENDING"
        and doc_abn != master_abn
    ):
        return ValidationResult(
            "VR12",
            False,
            "Tax ID on invoice does not match vendor master — possible fraud/wrong vendor",
        )

    return ValidationResult("VR12", True, f"Vendor master OK ({master.name})")


def vr12_customer_master(
    data: InvoiceData,
    *,
    customer_masters: list[CustomerMaster],
) -> ValidationResult:
    customer_name = (data.vendor or "").strip()
    if not customer_name:
        return ValidationResult("VR12", False, "Customer name required for master check")

    if not customer_masters:
        return ValidationResult(
            "VR12",
            False,
            "Customer not registered — add customer to master",
        )

    master = find_matching_customer_master(customer_name, data.abn, customer_masters)
    if master is None:
        return ValidationResult(
            "VR12",
            False,
            "Customer not found in customer master",
        )

    status = (master.status or "").strip().lower()
    if status in _BLOCKED_VENDOR_STATUSES:
        return ValidationResult("VR12", False, f"Customer master status is {master.status}")

    doc_abn = normalize_abn_digits(data.abn)
    master_abn = normalize_abn_digits(master.abn)
    if (
        doc_abn
        and master_abn
        and master_abn != "PENDING"
        and doc_abn != master_abn
    ):
        return ValidationResult(
            "VR12",
            False,
            "Tax ID on invoice does not match customer master — possible fraud/wrong customer",
        )

    return ValidationResult("VR12", True, f"Customer master OK ({master.name})")


def vr12_counterparty_master(
    data: InvoiceData,
    *,
    route_target: str | None,
    vendor_masters: list[VendorMaster],
    customer_masters: list[CustomerMaster],
) -> ValidationResult:
    if (route_target or "").strip() == ROUTE_SALES:
        return vr12_customer_master(data, customer_masters=customer_masters)
    return vr12_vendor_master(data, vendor_masters=vendor_masters)


async def vr14_po_status(
    data: InvoiceData,
    session: AsyncSession,
    *,
    invoice: Invoice | None,
    tenant_id: int,
    expected_currency: str,
) -> ValidationResult:
    po_ref = (data.po_reference or "").strip()
    if not po_ref:
        return ValidationResult("VR14", True, "No PO reference — PO status check skipped")

    if invoice is None:
        return ValidationResult("VR14", True, "PO status check deferred (no invoice context)")

    po = await load_purchase_order_for_invoice(session, invoice)
    if po is None:
        return ValidationResult("VR14", False, f"PO {po_ref} not found in register")

    if po.status == PurchaseOrderStatus.CLOSED:
        return ValidationResult("VR14", False, f"PO {po_ref} is closed")

    expected = expected_currency.strip().upper()
    currency = (data.currency or invoice.currency or expected).upper()
    if currency != expected:
        return ValidationResult(
            "VR14",
            False,
            f"Invoice currency {currency} must match PO currency ({expected})",
        )

    return ValidationResult("VR14", True, f"PO {po_ref} is open and currency matches")


async def vr15_document_match(
    data: InvoiceData,
    session: AsyncSession,
    *,
    invoice: Invoice | None,
    tenant_id: int,
    document_type_code: str | None = None,
    document_types: list | None = None,
) -> ValidationResult:
    from app.services.classification.document_type_match_service import run_document_match_validation

    outcome = await run_document_match_validation(
        data,
        session,
        invoice=invoice,
        tenant_id=tenant_id,
        document_type_code=document_type_code,
        document_types=document_types,
    )
    skipped = outcome.status == "Skipped" and outcome.passed
    return ValidationResult(
        "VR15",
        outcome.passed,
        outcome.message,
        skipped=skipped and "skipped" in outcome.message.lower(),
    )


async def vr15_three_way_match(
    data: InvoiceData,
    session: AsyncSession,
    *,
    invoice: Invoice | None,
    tenant_id: int,
    document_type_code: str | None = None,
    document_types: list | None = None,
) -> ValidationResult:
    """Backward-compatible alias — dispatches by document-type match mode."""
    return await vr15_document_match(
        data,
        session,
        invoice=invoice,
        tenant_id=tenant_id,
        document_type_code=document_type_code,
        document_types=document_types,
    )


def vr16_freight_surcharges(data: InvoiceData, *, expected_currency: str) -> ValidationResult:
    currency = expected_currency.strip().upper()
    freight_total = Decimal("0")
    for line in data.line_items:
        desc = (line.description or "").strip()
        if not desc or not _FREIGHT_KEYWORDS.search(desc):
            continue
        freight_total += line.amount or Decimal("0")

    if freight_total <= 0:
        return ValidationResult("VR16", True, "No freight/surcharge lines detected")

    po_ref = (data.po_reference or "").strip()
    if not po_ref:
        return ValidationResult(
            "VR16",
            False,
            f"Freight/surcharges {currency} {freight_total} without PO reference",
        )

    if freight_total > FREIGHT_TOLERANCE_AUD:
        return ValidationResult(
            "VR16",
            False,
            f"Freight/surcharges {currency} {freight_total} exceed tolerance {currency} {FREIGHT_TOLERANCE_AUD}",
        )

    return ValidationResult(
        "VR16",
        True,
        f"Freight/surcharges {currency} {freight_total} within tolerance",
    )


async def run_extended_validations(
    code: str,
    data: InvoiceData,
    session: AsyncSession,
    *,
    tenant_id: int,
    invoice: Invoice | None = None,
    config: RuleBookConfigPayload | None = None,
    route_target: str | None = None,
    document_type_code: str | None = None,
    document_types: list | None = None,
) -> ValidationResult | None:
    from app.services.invoice.invoice_evaluation_service import load_config_for_tenant
    from app.services.master_data.customer_master_service import list_customer_masters
    from app.services.master_data.master_data_service import classification_config_with_db_masters

    rule_config = await load_config_for_tenant(session, tenant_id) if config is None else config
    rule_config = await classification_config_with_db_masters(session, tenant_id, rule_config)

    if code == "VR09":
        return vr09_line_arithmetic(data)
    if code == "VR10":
        from app.models.tenant import Tenant
        from app.tenant_settings import tenant_country, tenant_currency

        tenant = await session.get(Tenant, tenant_id)
        return vr10_tax_invoice_wording(
            data,
            country=tenant_country(tenant),
            currency=tenant_currency(tenant),
        )
    if code == "VR11":
        from app.models.tenant import Tenant
        from app.tenant_settings import tenant_today

        tenant = await session.get(Tenant, tenant_id)
        return vr11_date_sanity(data, today=tenant_today(tenant))
    if code == "VR12":
        customer_masters = await list_customer_masters(session, tenant_id)
        effective_route = route_target or (invoice.route_target if invoice is not None else None)
        return vr12_counterparty_master(
            data,
            route_target=effective_route,
            vendor_masters=rule_config.vendor_masters,
            customer_masters=customer_masters,
        )
    if code == "VR14":
        from app.models.tenant import Tenant
        from app.tenant_settings import tenant_currency

        tenant = await session.get(Tenant, tenant_id)
        return await vr14_po_status(
            data,
            session,
            invoice=invoice,
            tenant_id=tenant_id,
            expected_currency=tenant_currency(tenant),
        )
    if code == "VR15":
        return await vr15_document_match(
            data,
            session,
            invoice=invoice,
            tenant_id=tenant_id,
            document_type_code=document_type_code,
            document_types=document_types,
        )
    if code == "VR16":
        from app.models.tenant import Tenant
        from app.tenant_settings import tenant_currency

        tenant = await session.get(Tenant, tenant_id)
        return vr16_freight_surcharges(data, expected_currency=tenant_currency(tenant))
    return None
