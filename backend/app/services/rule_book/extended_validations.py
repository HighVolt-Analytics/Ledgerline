"""Extended invoice validation rules (VR09, VR11, VR12, VR13)."""

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
    counterparty_type: str | None = None,
    vendor_masters: list[VendorMaster],
    customer_masters: list[CustomerMaster],
) -> ValidationResult:
    token = (counterparty_type or "").strip().lower()
    if token == "none":
        return ValidationResult("VR12", True, "Counterparty master check skipped (none)", skipped=True)
    if token == "employee":
        return ValidationResult("VR12", True, "Employee counterparty — vendor/customer master N/A", skipped=True)
    if token == "customer" or (route_target or "").strip() == ROUTE_SALES:
        return vr12_customer_master(data, customer_masters=customer_masters)
    return vr12_vendor_master(data, vendor_masters=vendor_masters)


def _normalize_bank_token(value: str | None) -> str:
    """Strip spaces/dashes so '062-000 12345678' == '06200012345678'."""
    if not value:
        return ""
    return "".join(ch for ch in str(value) if ch.isalnum()).upper()


def vr13_bank_details_match(
    data: InvoiceData,
    *,
    vendor_masters: list[VendorMaster],
    counterparty_type: str | None = None,
) -> ValidationResult:
    """Invoice pay-to bank details must match the vendor master on file.

    Fraud control: a vendor's registered bank account is the source of
    truth for where payment goes. An invoice whose extracted bank
    details diverge from the master — a classic invoice-redirection /
    business-email-compromise pattern — must not post untouched.
    """
    token = (counterparty_type or "").strip().lower()
    if token in {"none", "employee", "customer"}:
        return ValidationResult(
            "VR13",
            True,
            f"Bank details check skipped ({token})",
            skipped=True,
        )

    invoice_bsb = _normalize_bank_token(data.bank_bsb)
    invoice_acct = _normalize_bank_token(data.bank_account)

    if not invoice_bsb and not invoice_acct:
        return ValidationResult(
            "VR13", True, "No bank details on invoice to verify", skipped=True
        )

    vendor_name = (data.vendor or "").strip()
    if not vendor_name:
        return ValidationResult("VR13", True, "Vendor required for bank check", skipped=True)

    master = find_matching_vendor_master(vendor_name, data.abn, vendor_masters)
    if master is None:
        # VR12 already hard-fails an unrecognized vendor; avoid double-counting.
        return ValidationResult(
            "VR13",
            True,
            "Vendor master not found — bank check deferred to VR12",
            skipped=True,
        )

    master_bank = master.bank
    master_bsb = _normalize_bank_token(getattr(master_bank, "bsb", None) if master_bank else None)
    master_acct = _normalize_bank_token(
        getattr(master_bank, "account_number", None) if master_bank else None
    )

    if not master_bsb and not master_acct:
        # Data gap, not a detected conflict — the vendor master simply has no
        # bank details captured yet. Don't hard-block on incomplete master
        # data; only an actual mismatch between the two records is fraud
        # signal strong enough to stop posting.
        return ValidationResult(
            "VR13",
            True,
            f"Vendor master has no bank details on file for {master.name} — "
            "bank check skipped",
            skipped=True,
        )

    bsb_mismatch = bool(invoice_bsb and master_bsb and invoice_bsb != master_bsb)
    acct_mismatch = bool(invoice_acct and master_acct and invoice_acct != master_acct)
    if bsb_mismatch or acct_mismatch:
        return ValidationResult(
            "VR13",
            False,
            "Invoice bank details do not match vendor master on file — "
            "possible payment redirection fraud",
        )

    return ValidationResult("VR13", True, f"Bank details match vendor master ({master.name})")


def _counterparty_type_for_validation(
    document_type_code: str | None,
    document_types: list | None,
    route_target: str | None,
) -> str | None:
    if not document_type_code or not document_types:
        return None
    from app.schemas.document_type import resolved_counterparty_type
    from app.services.classification.document_type_catalog import get_document_type_definition

    defn = get_document_type_definition(document_type_code, document_types=document_types)
    if defn is None:
        return None
    return resolved_counterparty_type(defn, route_target=route_target)


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
    effective_route = route_target or (invoice.route_target if invoice is not None else None)
    counterparty_type = _counterparty_type_for_validation(
        document_type_code,
        document_types,
        effective_route,
    )

    if code == "VR09":
        return vr09_line_arithmetic(data)
    if code == "VR11":
        from app.models.tenant import Tenant
        from app.tenant_settings import tenant_today

        tenant = await session.get(Tenant, tenant_id)
        return vr11_date_sanity(data, today=tenant_today(tenant))
    if code == "VR12":
        customer_masters = await list_customer_masters(session, tenant_id)
        return vr12_counterparty_master(
            data,
            route_target=effective_route,
            counterparty_type=counterparty_type,
            vendor_masters=rule_config.vendor_masters,
            customer_masters=customer_masters,
        )
    if code == "VR13":
        return vr13_bank_details_match(
            data,
            vendor_masters=rule_config.vendor_masters,
            counterparty_type=counterparty_type,
        )
    return None
