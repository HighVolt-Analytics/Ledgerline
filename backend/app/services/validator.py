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





def vr03_required(data: InvoiceData) -> ValidationResult:

    missing = [f for f in _REQUIRED if getattr(data, f) is None]

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

    org_id: int,

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



    approved = await find_approved_vendor(

        session,

        org_id=org_id,

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

    org_id: int,

) -> ValidationResult:

    """Invoice number must be unique per vendor within an organisation (brief §4.1)."""

    if not get_settings().duplicate_invoice_check_enabled:
        return ValidationResult("VR02", True, "Duplicate check disabled")

    if not data.invoice_no:

        return ValidationResult("VR02", False, "Invoice number missing")

    if not (data.vendor or "").strip():

        return ValidationResult("VR02", False, "Vendor required for duplicate check")



    vendor_key = data.vendor.strip().lower()

    stmt = select(Invoice).where(

        Invoice.org_id == org_id,

        func.lower(Invoice.invoice_no) == data.invoice_no.strip().lower(),

        func.lower(Invoice.vendor) == vendor_key,

    )

    if exclude_id:

        stmt = stmt.where(Invoice.id != exclude_id)

    if (await session.execute(stmt)).scalar_one_or_none():

        return ValidationResult(

            "VR02",

            False,

            f"Duplicate invoice no for vendor {data.vendor}: {data.invoice_no}",

        )

    return ValidationResult("VR02", True, "Invoice number unique for vendor")





_SYNC_RULES = [vr03_required, vr06_dates, vr07_currency, vr08_gst, vr01_total]





async def run_all_validations(

    data: InvoiceData,

    session: AsyncSession,

    exclude_id: int | None = None,

    *,

    org_id: int,

    sender: str | None = None,

    route_target: str | None = None,

) -> list[ValidationResult]:

    results = [fn(data) for fn in _SYNC_RULES]

    results.insert(1, await vr05_abn(data, session, org_id=org_id, sender=sender))

    results.append(await vr02_unique(data, session, exclude_id, org_id=org_id))

    from app.services.team_expense_validator import run_team_expense_validations

    results.extend(
        await run_team_expense_validations(
            data,
            session,
            org_id=org_id,
            route_target=route_target,
            email_sender=sender,
        )
    )

    return results





def all_passed(results: list[ValidationResult]) -> bool:

    return all(r.passed for r in results)





def results_to_json(results: list[ValidationResult]) -> str:

    return json.dumps([r.__dict__ for r in results])


