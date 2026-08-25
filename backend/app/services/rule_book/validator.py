"""Validation rules VR03 → VR05 → VR07 → VR08 → VR01 → VR02 (assessment brief)."""



import json

from dataclasses import dataclass

from decimal import Decimal



from sqlalchemy import func, select

from sqlalchemy.ext.asyncio import AsyncSession



from app.models.invoice import Invoice

from app.services.invoice.invoice_data import InvoiceData

from app.services.master_data.vendor_resolver import find_approved_vendor

from app.services.extraction.gst_rate import expected_gst_amount, resolve_gst_rate_percent

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
    tax_id_kind: str | None = None,
    tax_id_label: str | None = None,
) -> ValidationResult:
    from app.jurisdiction.packs import jurisdiction_pack_for_country
    from app.models.tenant import Tenant
    from app.tenant_settings import tenant_country

    mode = get_settings().abn_validation_mode.strip().lower()
    use_checksum = mode == "checksum"

    tenant = await session.get(Tenant, tenant_id)
    pack = jurisdiction_pack_for_country(tenant_country(tenant))
    kind = (tax_id_kind or pack.tax_id_kind or "generic").strip().lower()
    label = (tax_id_label or pack.tax_id_label or "Tax ID").strip()

    def _abn_ok(value: str) -> bool:
        return is_valid_abn(value) if use_checksum else is_abn_format(value)

    candidate = (data.abn or "").strip()
    gstin = data.raw_fields.get("gstin") if isinstance(data.raw_fields, dict) else None
    extracted = data.extracted_fields if isinstance(getattr(data, "extracted_fields", None), dict) else {}
    party_tax = (
        extracted.get("seller_tax_id")
        or extracted.get("buyer_tax_id")
        or extracted.get("seller_abn")
        or extracted.get("buyer_abn")
        or ""
    )
    if not candidate and party_tax:
        candidate = str(party_tax).strip()

    if kind == "abn":
        if candidate and _abn_ok(candidate):
            msg = f"{label} valid" if use_checksum else f"{label} format valid (11 digits)"
            return ValidationResult("VR05", True, msg)
        if use_checksum and candidate and is_acceptable_tax_id(candidate, tax_id_kind="generic"):
            return ValidationResult("VR05", True, "Tax ID accepted (equivalent identifier)")
        if gstin and is_acceptable_tax_id(str(gstin), tax_id_kind="gstin"):
            return ValidationResult("VR05", True, "GSTIN / tax ID present on document")
    else:
        check_value = candidate or (str(gstin).strip() if gstin else "")
        if check_value and is_acceptable_tax_id(check_value, tax_id_kind=kind):
            return ValidationResult("VR05", True, f"{label} accepted")
        if check_value and is_acceptable_tax_id(check_value, tax_id_kind="generic"):
            return ValidationResult("VR05", True, f"{label} / tax ID accepted")

    approved = await find_approved_vendor(
        session,
        tenant_id=tenant_id,
        vendor_name=data.vendor,
        sender=sender,
    )
    if approved and approved.abn:
        if kind == "abn" and _abn_ok(approved.abn):
            data.abn = approved.abn
            return ValidationResult(
                "VR05",
                True,
                f"{label} from approved vendor registry ({approved.vendor_name})",
            )
        if kind != "abn" and is_acceptable_tax_id(approved.abn, tax_id_kind=kind):
            data.abn = approved.abn if kind == "abn" else data.abn
            return ValidationResult(
                "VR05",
                True,
                f"{label} from approved vendor registry ({approved.vendor_name})",
            )

    if not candidate and not gstin:
        return ValidationResult("VR05", False, f"{label} missing")

    if kind == "abn":
        detail = f"Invalid {label} checksum" if use_checksum else f"{label} must be 11 digits"
        return ValidationResult("VR05", False, f"{detail}: {data.abn}")
    return ValidationResult("VR05", False, f"Invalid {label}: {candidate or gstin}")


def vr07_currency(data: InvoiceData, *, expected_currency: str) -> ValidationResult:
    expected = expected_currency.strip().upper()
    currency = (data.currency or "").strip().upper()
    if not currency:
        return ValidationResult("VR07", False, "Currency missing")
    if currency == expected:
        return ValidationResult("VR07", True, f"Currency is {expected}")
    if data.gst is None and data.abn is None:
        return ValidationResult("VR07", True, f"Foreign currency accepted: {currency}")
    return ValidationResult("VR07", False, f"Expected {expected}, got {data.currency}")





def vr08_gst(
    data: InvoiceData,
    *,
    expected_currency: str,
    statutory_tax_rate: Decimal | None = None,
    tax_label: str = "Tax",
) -> ValidationResult:
    expected = expected_currency.strip().upper()
    doc_currency = (data.currency or "").strip().upper()
    if data.gst is None:
        if data.subtotal is not None and doc_currency and doc_currency != expected:
            return ValidationResult("VR08", True, f"{tax_label} not applicable for foreign invoice")
        return ValidationResult(
            "VR08", True, f"Skipped — subtotal and {tax_label} required", skipped=True
        )
    if data.subtotal is None:
        return ValidationResult(
            "VR08", True, f"Skipped — subtotal and {tax_label} required", skipped=True
        )
    rate = resolve_gst_rate_percent(data)
    if rate is None:
        return ValidationResult(
            "VR08", True, f"Skipped — {tax_label} rate could not be determined", skipped=True
        )
    expected_amt = expected_gst_amount(data.subtotal, rate)
    if abs(data.gst - expected_amt) <= Decimal("0.02"):
        return ValidationResult("VR08", True, f"{tax_label} matches {rate}% of subtotal")
    return ValidationResult("VR08", False, f"{tax_label} {data.gst} != {rate}% of {data.subtotal}")





def vr01_total(data: InvoiceData) -> ValidationResult:

    if None in (data.subtotal, data.gst, data.total):

        return ValidationResult("VR01", True, "Skipped — subtotal, GST, and total required", skipped=True)

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

    """Document identity must be unique per vendor within an organisation (brief §4.1)."""

    settings = get_settings()
    if not settings.duplicate_invoice_check_enabled:
        return ValidationResult("VR02", True, "Duplicate check disabled")

    from app.services.dossier.document_duplicate_service import identity_duplicate_exists
    from app.services.extraction.document_identity_service import (
        extract_identity_fields,
        identity_field_keys_from_catalogue,
        is_identity_field_key,
    )
    from app.services.extraction.extraction_field_values import extracted_fields_from_parsed
    from app.services.invoice.invoice_evaluation_service import load_config_for_tenant

    config = await load_config_for_tenant(session, tenant_id)
    custom_keys = identity_field_keys_from_catalogue(config.document_types)

    match = await identity_duplicate_exists(
        session,
        data,
        tenant_id=tenant_id,
        exclude_id=exclude_id,
        custom_field_keys=custom_keys,
    )
    if match is not None:
        duplicate = match.invoice
        ref = duplicate.invoice_no or duplicate.po_reference or duplicate.id
        if match.kind == "fuzzy":
            from app.services.audit.audit_service import log_event
            from app.services.extraction.pdf_content_fingerprint import (
                boost_confidence_with_content_similarity,
            )

            confidence = match.confidence_score or 0.0
            content_sim = None
            confidence, content_sim = boost_confidence_with_content_similarity(
                confidence,
                data.document_text,
                duplicate.document_text,
            )
            detail = {
                "matched_invoice_id": duplicate.id,
                "confidence_score": confidence,
                "layer": "fuzzy",
                "vendor": data.vendor,
            }
            if content_sim is not None:
                detail["content_similarity"] = content_sim
            await log_event(
                session,
                "fuzzy_duplicate_suspected",
                invoice_id=exclude_id,
                detail=detail,
            )
            return ValidationResult(
                "VR02",
                False,
                f"Possible duplicate (fuzzy review): vendor {data.vendor or duplicate.vendor}, "
                f"matched {ref} (confidence={confidence})",
                severity="warn",
            )
        return ValidationResult(
            "VR02",
            False,
            f"Duplicate document identity ({match.kind}) for vendor "
            f"{data.vendor or duplicate.vendor}: {ref}",
            severity="block",
        )

    identity_present = bool((data.invoice_no or "").strip() or (data.po_reference or "").strip())
    if not identity_present:
        for key, value in extracted_fields_from_parsed(data).items():
            if is_identity_field_key(key) and value.strip():
                identity_present = True
                break
    if not identity_present and data.document_text:
        harvested = extract_identity_fields(data.document_text, custom_field_keys=custom_keys)
        identity_present = any(harvested.values())

    if not identity_present:
        return ValidationResult("VR02", False, "Document identity missing for duplicate check")

    if not (data.vendor or "").strip():
        return ValidationResult("VR02", False, "Vendor required for duplicate check")

    layers = "identity, exact, normalized"
    if settings.fuzzy_duplicate_check_enabled:
        layers = f"{layers}, fuzzy"
    return ValidationResult("VR02", True, f"No duplicate detected ({layers})")





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
    from app.services.classification.document_type_field_checks import field_is_present
    from app.services.classification.document_type_rule_engine import build_document_classifier_context

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


_SYNC_RULES = [vr03_required, vr08_gst, vr01_total]


def _append_playbook_validations(
    results: list[ValidationResult],
    playbook_gates: object | None,
) -> list[ValidationResult]:
    if playbook_gates is None:
        return results
    from app.services.classification.document_type_playbook_service import playbook_validation_results

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
    from app.services.rule_book.validation_runner import ValidationRunContext, run_configured_validations

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


