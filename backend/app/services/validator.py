"""Validation rules VR03 → VR05 → VR06 → VR07 → VR08 → VR01 → VR02 (assessment brief)."""



import json

from dataclasses import dataclass

from decimal import Decimal



from sqlalchemy import func, select

from sqlalchemy.ext.asyncio import AsyncSession



from app.models.invoice import Invoice

from app.services.invoice_data import InvoiceData

from app.services.vendor_resolver import find_approved_vendor

from app.config import get_settings

from app.utils.abn_validator import is_abn_format, is_valid_abn

from app.utils.tax_id_validator import is_acceptable_tax_id



_REQUIRED = (

    "vendor",

    "abn",

    "invoice_no",

    "invoice_date",

    "due_date",

    "subtotal",

    "gst",

    "total",

)





@dataclass
class ValidationResult:

    rule: str

    passed: bool

    message: str

    skipped: bool = False

    severity: str = "block"





def vr03_required(data: InvoiceData) -> ValidationResult:

    missing = [f for f in _REQUIRED if getattr(data, f) is None]

    if not data.abn:
        gstin = data.raw_fields.get("gstin")
        if gstin and is_acceptable_tax_id(str(gstin)):
            missing = [field for field in missing if field != "abn"]

    if not data.line_items:

        missing.append("line_items")

    else:

        for idx, line in enumerate(data.line_items):

            if not (line.description or "").strip():

                missing.append(f"line_items[{idx}].description")

            if line.amount is None and line.unit_price is None:

                missing.append(f"line_items[{idx}].amount")

    if missing:

        return ValidationResult("VR03", False, f"Missing: {', '.join(missing)}")

    return ValidationResult("VR03", True, "All required fields present")





async def vr05_abn(

    data: InvoiceData,

    session: AsyncSession,

    *,

    tenant_id: int,

    sender: str | None = None,

) -> ValidationResult:

    mode = get_settings().abn_validation_mode.strip().lower()

    use_checksum = mode == "checksum"



    def _abn_ok(value: str) -> bool:

        return is_valid_abn(value) if use_checksum else is_abn_format(value)



    if data.abn and _abn_ok(data.abn):

        msg = "ABN valid" if use_checksum else "ABN format valid (11 digits)"

        return ValidationResult("VR05", True, msg)



    if use_checksum and data.abn and is_acceptable_tax_id(data.abn):

        return ValidationResult("VR05", True, "Tax ID accepted (equivalent identifier)")

    gstin = data.raw_fields.get("gstin")
    if gstin and is_acceptable_tax_id(str(gstin)):
        return ValidationResult("VR05", True, "GSTIN / tax ID present on document")



    approved = await find_approved_vendor(

        session,

        tenant_id=tenant_id,

        vendor_name=data.vendor,

        sender=sender,

    )

    if approved and approved.abn and _abn_ok(approved.abn):

        data.abn = approved.abn

        return ValidationResult(

            "VR05",

            True,

            f"ABN from approved vendor registry ({approved.vendor_name})",

        )



    if not data.abn:

        return ValidationResult("VR05", False, "ABN / Tax ID missing")

    detail = "Invalid ABN checksum" if use_checksum else "ABN must be 11 digits"

    return ValidationResult("VR05", False, f"{detail}: {data.abn}")





def vr06_dates(data: InvoiceData) -> ValidationResult:

    if data.invoice_date is None:

        return ValidationResult("VR06", False, "invoice_date required")

    if data.due_date is None:

        return ValidationResult("VR06", False, "due_date required")

    if data.due_date < data.invoice_date:

        return ValidationResult("VR06", False, "due_date must be on or after invoice_date")

    return ValidationResult("VR06", True, "Dates valid")





def vr07_currency(data: InvoiceData) -> ValidationResult:

    if (data.currency or "AUD").upper() == "AUD":

        return ValidationResult("VR07", True, "Currency is AUD")

    return ValidationResult("VR07", False, f"Expected AUD, got {data.currency}")





def vr08_gst(data: InvoiceData) -> ValidationResult:

    if data.subtotal is None or data.gst is None:

        return ValidationResult("VR08", False, "Subtotal and GST required")

    expected = (data.subtotal * Decimal("0.10")).quantize(Decimal("0.01"))

    if abs(data.gst - expected) <= Decimal("0.02"):

        return ValidationResult("VR08", True, "GST is 10% of subtotal")

    return ValidationResult("VR08", False, f"GST {data.gst} != 10% of {data.subtotal}")





def vr01_total(data: InvoiceData) -> ValidationResult:

    if None in (data.subtotal, data.gst, data.total):

        return ValidationResult("VR01", False, "Subtotal, GST, total required")

    expected = data.subtotal + data.gst

    if abs(data.total - expected) <= Decimal("0.01"):

        return ValidationResult("VR01", True, "Total matches subtotal + GST")

    return ValidationResult("VR01", False, f"Total {data.total} != {expected}")





async def vr02_unique(

    data: InvoiceData,

    session: AsyncSession,

    exclude_id: int | None = None,

    *,

    tenant_id: int,

) -> ValidationResult:

    """Invoice number must be unique per vendor within an organisation (brief §4.1)."""

    if not get_settings().duplicate_invoice_check_enabled:
        return ValidationResult("VR02", True, "Duplicate check disabled")

    if not data.invoice_no:

        return ValidationResult("VR02", False, "Invoice number missing")

    if not (data.vendor or "").strip():

        return ValidationResult("VR02", False, "Vendor required for duplicate check")



    from app.services.document_duplicate_service import (
        fuzzy_business_duplicate_exists,
        invoice_number_duplicate_exists,
        normalized_invoice_number_duplicate_exists,
    )

    duplicate = await invoice_number_duplicate_exists(
        session,
        data,
        tenant_id=tenant_id,
        exclude_id=exclude_id,
    )
    if duplicate is not None:
        return ValidationResult(
            "VR02",
            False,
            f"Exact duplicate invoice no for vendor {data.vendor}: {data.invoice_no}",
        )

    normalized_dup = await normalized_invoice_number_duplicate_exists(
        session,
        data,
        tenant_id=tenant_id,
        exclude_id=exclude_id,
    )
    if normalized_dup is not None:
        return ValidationResult(
            "VR02",
            False,
            f"Normalized duplicate invoice no for vendor {data.vendor}: {data.invoice_no}",
        )

    fuzzy_dup = await fuzzy_business_duplicate_exists(
        session,
        data,
        tenant_id=tenant_id,
        exclude_id=exclude_id,
    )
    if fuzzy_dup is not None:
        return ValidationResult(
            "VR02",
            False,
            (
                f"Fuzzy duplicate: vendor {data.vendor}, similar amount/date "
                f"(invoice {fuzzy_dup.invoice_no})"
            ),
        )

    return ValidationResult("VR02", True, "No duplicate detected (exact, normalized, fuzzy)")





def vr03_po_document(data: InvoiceData) -> ValidationResult:
    missing: list[str] = []
    if not (data.vendor or "").strip():
        missing.append("vendor")
    if not (data.po_reference or "").strip():
        missing.append("po_reference")
    if not data.line_items:
        missing.append("line_items")
    elif data.total is None and data.subtotal is None:
        missing.append("total")
    if missing:
        return ValidationResult("VR03", False, f"Missing: {', '.join(missing)}")
    return ValidationResult("VR03", True, "PO document fields present")


def vr03_grn_document(data: InvoiceData) -> ValidationResult:
    missing: list[str] = []
    if not (data.po_reference or "").strip():
        missing.append("po_reference")
    if not data.line_items:
        missing.append("line_items")
    if missing:
        return ValidationResult("VR03", False, f"Missing: {', '.join(missing)}")
    return ValidationResult("VR03", True, "GRN document fields present")


def vr03_direct_expense(data: InvoiceData) -> ValidationResult:
    missing: list[str] = []
    if not (data.vendor or "").strip():
        missing.append("vendor")
    if not (data.invoice_no or "").strip():
        missing.append("invoice_no")
    if data.total is None:
        missing.append("total")
    if not data.line_items:
        missing.append("line_items")
    if missing:
        return ValidationResult("VR03", False, f"Missing: {', '.join(missing)}")
    return ValidationResult("VR03", True, "Direct expense fields present")


def vr03_compulsory_fields(
    invoice: Invoice,
    data: InvoiceData,
    compulsory_keys: list[str],
) -> ValidationResult:
    """Validate document-type compulsory field keys."""
    from app.services.document_type_field_checks import field_is_present
    from app.services.document_type_rule_engine import build_document_classifier_context

    if not compulsory_keys:
        return ValidationResult("VR03", True, "No compulsory fields configured", skipped=True)

    ctx = build_document_classifier_context(invoice=invoice, parsed=data)
    missing: list[str] = []
    for key in compulsory_keys:
        if not field_is_present(key, invoice=invoice, parsed=data, ctx=ctx):
            missing.append(key)
    if missing:
        return ValidationResult("VR03", False, f"Missing compulsory: {', '.join(missing)}")
    return ValidationResult("VR03", True, "All compulsory fields present")


def _skipped(rule: str, reason: str) -> ValidationResult:
    return ValidationResult(rule, True, reason, skipped=True)


_SYNC_RULES = [vr03_required, vr06_dates, vr07_currency, vr08_gst, vr01_total]


def _append_playbook_validations(
    results: list[ValidationResult],
    playbook_gates: object | None,
) -> list[ValidationResult]:
    if playbook_gates is None:
        return results
    from app.services.document_type_playbook_service import playbook_validation_results

    return [*results, *playbook_validation_results(playbook_gates)]


async def run_all_validations(
    data: InvoiceData,
    session: AsyncSession,
    exclude_id: int | None = None,
    *,
    tenant_id: int,
    sender: str | None = None,
    route_target: str | None = None,
    purchase_document_type: str | None = None,
    has_receipt_file: bool = False,
    document_type_code: str | None = None,
    validation_profile: str | None = None,
    document_types: list | None = None,
    playbook_gates: object | None = None,
    invoice: Invoice | None = None,
) -> list[ValidationResult]:
    from app.services.validation_runner import ValidationRunContext, run_configured_validations

    ctx = ValidationRunContext(
        data=data,
        session=session,
        tenant_id=tenant_id,
        exclude_id=exclude_id,
        sender=sender,
        route_target=route_target,
        purchase_document_type=purchase_document_type,
        has_receipt_file=has_receipt_file,
        document_type_code=document_type_code,
        validation_profile=validation_profile,
        document_types=document_types,
        playbook_gates=playbook_gates,
        invoice=invoice,
    )
    return await run_configured_validations(ctx)


def normalize_stored_validation_row(row: dict) -> dict:
    """Upgrade legacy VR12 rows that skipped when the tenant had no vendor masters."""
    rule = str(row.get("rule", "")).strip().upper()
    if rule != "VR12" or not row.get("skipped"):
        return row
    message = str(row.get("message", "")).lower()
    if "no masters" in message or "check skipped" in message:
        return {
            **row,
            "rule": rule,
            "passed": False,
            "skipped": False,
            "message": "Vendor not registered — add vendor to master",
        }
    return row


def normalize_stored_validation_results(rows: list[dict]) -> list[dict]:
    return [normalize_stored_validation_row(row) for row in rows if isinstance(row, dict)]


def all_passed(results: list[ValidationResult]) -> bool:
    return all(
        r.passed or r.skipped or (not r.passed and r.severity == "warn")
        for r in results
    )





def results_to_json(results: list[ValidationResult]) -> str:

    return json.dumps([{**r.__dict__} for r in results])


