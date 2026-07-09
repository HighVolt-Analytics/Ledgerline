"""Extended invoice validation rules (VR09, VR11, VR12)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import Invoice
from app.schemas.customer import CustomerMaster
from app.schemas.rule_book_config import RuleBookConfigPayload, VendorMaster
from app.services.invoice.invoice_data import InvoiceData
from app.services.invoice.invoice_evaluation_service import ROUTE_SALES
from app.services.rule_book.validator import ValidationResult
from app.services.master_data.vendor_detection import (
    find_matching_customer_master,
    find_matching_vendor_master,
    normalize_abn_digits,
)

LINE_TOLERANCE = Decimal("0.05")
SUBTOTAL_TOLERANCE = Decimal("0.05")

_BLOCKED_VENDOR_STATUSES = frozenset({"blocked", "inactive", "suspended", "closed"})


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
    return None
