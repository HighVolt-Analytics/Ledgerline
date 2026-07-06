"""Runtime LLM document classification and field extraction."""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Sequence

from pydantic import ValidationError

from app.config import get_settings
from app.schemas.document_type import DocumentTypeDefinition
from app.schemas.llm_document import LlmDocumentResult, LlmLineItem, LlmParty
from app.schemas.ocr_artifact import OcrArtifact
from app.services.extraction.azure_openai_client import chat_json_async
from app.services.invoice.invoice_data import InvoiceData, ParsedLineItem
from app.services.tenant.tenant_org_context import OrgContext
from app.services.classification.document_type_field_keys import CANONICAL_EXTRACTION_FIELD_KEYS
from app.services.extraction.llm_catalogue_rows import build_llm_catalogue_rows
from app.services.extraction.extraction_field_values import (
    custom_extraction_field_descriptors,
    custom_extraction_field_keys,
    custom_extraction_field_keys_for_dt,
    custom_extraction_fields_prompt_lines,
    harvest_custom_fields_from_llm_raw,
    normalize_extracted_fields_map,
)
from app.services.extraction.party_field_service import PARTY_LLM_RULES, apply_party_normalization_to_llm
from app.services.shared.flexible_date import parse_flexible_date
from app.utils.logger import get_logger

logger = get_logger(__name__)

# Top-level scalar keys the LLM must return (keeps classify/extract prompts aligned).
_LLM_EXTRACT_SCALAR_KEYS: tuple[str, ...] = (
    "invoice_no",
    "invoice_date",
    "due_date",
    "po_reference",
    "so_reference",
    "cost_centre",
    "subtotal",
    "gst",
    "gst_rate",
    "total",
    "currency",
    "abn",
    "vendor",
    "document_heading",
    "bank_bsb",
    "bank_account",
    "bank_name",
)

_LLM_EXTRACT_JSON_KEYS = ", ".join(
    (
        "suggested_dt",
        "confidence",
        "reasoning",
        "perspective",
        "seller",
        "buyer",
        *_LLM_EXTRACT_SCALAR_KEYS,
        "line_items",
        "field_confidence",
        "extracted_fields",
    )
)

_LLM_EXTRACT_RULES = """- line_items is a list of {{description, amount, qty, unit_price}}.
- line_items must be product/service rows only — never header metadata (Customer, Ship Date, Invoice No, BSB, etc.).
- If a row is a field label ending with ":" it is NOT a line item.
- Leave line_items empty when the document has no product table.
- po_reference: purchase order number when labeled PO / Purchase Order.
- so_reference: sales order number when labeled SO / Sales Order (common on AR invoices and delivery notes).
- cost_centre: department or cost centre code when explicitly labeled.
- bank_bsb, bank_account, bank_name: extract only when explicitly labeled (BSB, Account No, IBAN, SWIFT, Bank Name). Leave empty if absent. Never use phone numbers, invoice numbers, or tax IDs as bank details.
- field_confidence maps field names to 0.0-1.0.
- gst_rate is the tax percentage as a number (e.g. 10 for 10%), not a fraction.
- currency: ISO 4217 code from the document (e.g. AUD, USD, SGD). Leave empty when no currency is shown.
- extracted_fields is an optional object for keys listed in custom_extraction_fields; use string values only."""

_LLM_SYSTEM = f"""You classify finance documents for accounts payable.
Return JSON only with keys:
{_LLM_EXTRACT_JSON_KEYS}.

Rules:
- suggested_dt must be one of the catalogue codes provided, or empty string if unsure.
- confidence is 0.0-1.0 for the document type choice.
- perspective is purchase | sales | unknown (tenant perspective is buyer/AP unless they are the seller).
{{party_rules}}
{_LLM_EXTRACT_RULES}
- Use OCR text faithfully; do not invent amounts or parties.
- few_shot_examples are prior reviewer corrections for this tenant. When document_heading or text_excerpt
  closely matches a few-shot example, strongly prefer that example's human_confirmed_dt over catalogue defaults.
- When llm_suggested_dt was wrong but human_confirmed_dt was chosen, learn from the note and excerpt."""

_LLM_CLASSIFY_SYSTEM = """You classify finance documents for accounts payable.
Return JSON only with keys:
suggested_dt, confidence, reasoning, perspective, seller, buyer, document_heading.

Rules:
- suggested_dt must be one of the catalogue codes provided, or empty string if unsure.
- confidence is 0.0-1.0 for the document type choice.
- perspective is purchase | sales | unknown (tenant perspective is buyer/AP unless they are the seller).
{party_rules}
- Do not extract invoice amounts, line items, or dates — classification only.
- few_shot_examples are prior reviewer corrections for this tenant. When document_heading or text_excerpt
  closely matches a few-shot example, strongly prefer that example's human_confirmed_dt over catalogue defaults.
- Examples with vendor_key match the sender/vendor — prefer those when the layout matches that supplier.
- Each catalogue row has recognition_mode signals or prompt.
- When recognition_mode is signals, treat recognition_rules as deterministic match hints for that code.
- When recognition_mode is prompt, treat llm_prompt as the authoritative description for that code."""

_LLM_EXTRACT_SYSTEM = f"""You structure accounts-payable fields from the provided OCR payload into JSON.
Return JSON only with keys:
{_LLM_EXTRACT_JSON_KEYS}.

Rules:
- Structure values from ocr.text_excerpt, ocr.layout_kv, and invoice_fields in the user payload.
- Do not invent amounts, parties, or dates absent from that OCR payload.
- suggested_dt must match confirmed_dt from the user payload.
- confidence is 0.0-1.0 for the document type choice.
- perspective is purchase | sales | unknown.
{{party_rules}}
{_LLM_EXTRACT_RULES}
- invoice_date and due_date must be ISO YYYY-MM-DD strings when a date is present."""

_SPARSE_IMAGE_EXTRACT_HINT = """
Sparse OCR: document images may be attached. Prefer ocr.text_excerpt and layout_kv.
Use images only to fill fields still missing from OCR — do not override OCR with invented values."""

_LLM_SYSTEM = _LLM_SYSTEM.format(party_rules=PARTY_LLM_RULES)
_LLM_CLASSIFY_SYSTEM = _LLM_CLASSIFY_SYSTEM.format(party_rules=PARTY_LLM_RULES)
_LLM_EXTRACT_SYSTEM = _LLM_EXTRACT_SYSTEM.format(party_rules=PARTY_LLM_RULES)


def _org_role_lines(org: OrgContext) -> list[str]:
    perspective = (org.default_perspective or "buyer").strip().lower()
    if perspective == "seller":
        return [
            "Tenant acts as accounts receivable (seller). Default perspective is sales unless the tenant appears as buyer.",
        ]
    if perspective == "mixed":
        return [
            "Tenant may act as buyer (accounts payable) or seller (accounts receivable).",
            "Determine perspective from party names and ABN against tenant legal_name, abn, and aliases.",
        ]
    return [
        "Tenant acts as accounts payable (buyer). Default perspective is purchase unless the tenant appears as seller.",
    ]


def build_classify_system_prompt(org: OrgContext) -> str:
    parts = [_LLM_CLASSIFY_SYSTEM.strip(), "", "Tenant context:"]
    parts.extend(f"- {line}" for line in _org_role_lines(org))
    if org.intake_summary.strip():
        parts.extend(["", f"Typical intake: {org.intake_summary.strip()}"])
    if org.classification_hints.strip():
        parts.extend(["", f"Tenant guidance: {org.classification_hints.strip()}"])
    return "\n".join(parts)


def build_extract_system_prompt(
    org: OrgContext,
    *,
    playbook_profile: str | None = None,
    custom_keys: Sequence[str] | None = None,
) -> str:
    parts = [_LLM_EXTRACT_SYSTEM.strip(), "", "Tenant context:"]
    parts.extend(f"- {line}" for line in _org_role_lines(org))
    profile = (playbook_profile or "").strip().lower()
    if profile == "supporting":
        parts.extend(
            [
                "",
                "Document profile: supporting/permit — extract permit_no, consignment_ref, document_heading; "
                "do not invent invoice_no, due_date, or totals.",
            ]
        )
    elif profile == "direct_expense":
        parts.extend(
            [
                "",
                "Document profile: direct expense — prioritize vendor, total, due_date; po_reference is usually absent.",
            ]
        )
    elif profile in {"po_goods", "ar_goods"}:
        parts.extend(
            [
                "",
                "Document profile: goods invoice — extract po_reference, vendor, line_items, invoice_date, due_date.",
            ]
        )
    elif profile == "credit_adjustment":
        parts.extend(
            [
                "",
                "Document profile: credit note — extract credit reference and amounts (may be negative).",
            ]
        )
    if custom_keys:
        parts.extend(custom_extraction_fields_prompt_lines(custom_extraction_field_descriptors(custom_keys)))
    return "\n".join(parts)


def build_combined_system_prompt(
    org: OrgContext,
    *,
    custom_keys: Sequence[str] | None = None,
) -> str:
    parts = [_LLM_SYSTEM.strip(), "", "Tenant context:"]
    parts.extend(f"- {line}" for line in _org_role_lines(org))
    if org.intake_summary.strip():
        parts.extend(["", f"Typical intake: {org.intake_summary.strip()}"])
    if org.classification_hints.strip():
        parts.extend(["", f"Tenant classification guidance: {org.classification_hints.strip()}"])
    if custom_keys:
        parts.extend(custom_extraction_fields_prompt_lines(custom_extraction_field_descriptors(custom_keys)))
    return "\n".join(parts)


def _catalogue_rows(document_types: Sequence[DocumentTypeDefinition]) -> list[dict[str, Any]]:
    return build_llm_catalogue_rows(document_types)


def _few_shot_rows(examples: Sequence[dict[str, str]]) -> list[dict[str, str]]:
    return list(examples)[:5]


def build_llm_user_payload(
    *,
    ocr: OcrArtifact,
    org: OrgContext,
    document_types: Sequence[DocumentTypeDefinition],
    few_shots: Sequence[dict[str, str]] | None = None,
    custom_keys: Sequence[str] | None = None,
    confirmed_dt: str | None = None,
) -> str:
    excerpt = (ocr.text or "")[:12000]
    keys = (
        list(custom_keys)
        if custom_keys is not None
        else custom_extraction_field_keys(document_types)
    )
    descriptors = custom_extraction_field_descriptors(keys)
    payload: dict[str, Any] = {
        "tenant": {
            "legal_name": org.legal_name,
            "abn": org.abn,
            "aliases": org.aliases,
            "default_perspective": org.default_perspective,
            "intake_summary": org.intake_summary,
            "classification_hints": org.classification_hints,
        },
        "catalogue": _catalogue_rows(document_types),
        "few_shot_examples": _few_shot_rows(few_shots or ()),
        "custom_extraction_fields": keys,
        "custom_extraction_field_descriptors": descriptors,
        "canonical_extraction_fields": sorted(CANONICAL_EXTRACTION_FIELD_KEYS),
        "ocr": {
            "text_excerpt": excerpt,
            "layout_kv": ocr.layout_kv,
            "text_length": ocr.text_length,
            "document_heading": (ocr.payload_json or {}).get("document_heading"),
        },
    }
    invoice_fields = (ocr.payload_json or {}).get("invoice_fields")
    if isinstance(invoice_fields, dict) and invoice_fields:
        payload["invoice_fields"] = invoice_fields
    if confirmed_dt:
        payload["confirmed_dt"] = confirmed_dt.strip().upper()
    return json.dumps(payload, default=str)


def _playbook_profile_for_dt(
    document_types: Sequence[DocumentTypeDefinition],
    dt_token: str,
) -> str | None:
    for defn in document_types:
        if (defn.code or "").strip().upper() == dt_token:
            return defn.playbook_profile
    return None


def _custom_keys_for_dt(
    document_types: Sequence[DocumentTypeDefinition],
    dt_token: str,
) -> list[str]:
    custom_keys = custom_extraction_field_keys_for_dt(document_types, dt_token)
    if not custom_keys:
        custom_keys = custom_extraction_field_keys(document_types)
    return list(custom_keys)


def build_structure_extract_prompts(
    *,
    ocr: OcrArtifact,
    org: OrgContext,
    document_types: Sequence[DocumentTypeDefinition],
    confirmed_dt: str,
    few_shots: Sequence[dict[str, str]] | None = None,
    playbook_profile: str | None = None,
    custom_keys: Sequence[str] | None = None,
    sparse: bool = False,
) -> tuple[str, str]:
    """Shared system + user prompts for OCR-first field structuring (all providers)."""
    dt_token = confirmed_dt.strip().upper()
    keys = list(custom_keys) if custom_keys is not None else _custom_keys_for_dt(document_types, dt_token)
    profile = playbook_profile if playbook_profile is not None else _playbook_profile_for_dt(
        document_types, dt_token
    )
    system = build_extract_system_prompt(org, playbook_profile=profile, custom_keys=keys)
    if sparse:
        system = f"{system}{_SPARSE_IMAGE_EXTRACT_HINT}"
    user = build_llm_user_payload(
        ocr=ocr,
        org=org,
        document_types=document_types,
        few_shots=few_shots,
        custom_keys=keys,
        confirmed_dt=dt_token,
    )
    return system, user


def _normalize_llm_raw(
    raw: dict[str, Any],
    *,
    custom_keys: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Best-effort cleanup before Pydantic validation (LLMs often emit '' or nested vendor)."""
    out = dict(raw)
    vendor = out.get("vendor")
    if isinstance(vendor, dict):
        out["vendor"] = vendor.get("name") or vendor.get("vendor") or ""
    for key in (
        "reasoning",
        "invoice_no",
        "invoice_date",
        "due_date",
        "po_reference",
        "so_reference",
        "cost_centre",
        "currency",
        "abn",
        "vendor",
        "document_heading",
        "bank_bsb",
        "bank_account",
        "bank_name",
    ):
        if out.get(key) is None:
            out[key] = ""
    for money in ("subtotal", "gst", "gst_rate", "total"):
        if out.get(money) == "":
            out[money] = None
    items = out.get("line_items")
    if isinstance(items, list):
        cleaned: list[dict[str, Any]] = []
        for row in items:
            if not isinstance(row, dict):
                continue
            item = dict(row)
            for key in ("amount", "qty", "unit_price"):
                if item.get(key) == "":
                    item[key] = None
            cleaned.append(item)
        out["line_items"] = cleaned
    harvested = harvest_custom_fields_from_llm_raw(out, custom_keys=custom_keys)
    if harvested:
        out["extracted_fields"] = harvested
    else:
        extracted = out.get("extracted_fields")
        if isinstance(extracted, dict):
            out["extracted_fields"] = normalize_extracted_fields_map(extracted)
        elif extracted is not None:
            out["extracted_fields"] = {}
    return out


def _resolved_currency(llm: LlmDocumentResult) -> str:
    """Use LLM currency when present; default AUD only when monetary amounts were extracted."""
    token = (llm.currency or "").strip().upper()
    if token:
        return token
    if llm.subtotal is not None or llm.gst is not None or llm.total is not None:
        return "AUD"
    return "AUD"


def _bank_extracted_fields(llm: LlmDocumentResult) -> dict[str, str]:
    bank_name = (llm.bank_name or "").strip()
    bank_bsb = (llm.bank_bsb or "").strip()
    bank_account = (llm.bank_account or "").strip()
    out: dict[str, str] = {}
    if bank_name:
        out["bank_name"] = bank_name
    parts = [part for part in (bank_name, bank_bsb, bank_account) if part]
    if parts:
        out["bank_details"] = " / ".join(parts)
    return out


def _canonical_scalar_extracted_fields(llm: LlmDocumentResult) -> dict[str, str]:
    out: dict[str, str] = {}
    so_ref = (llm.so_reference or "").strip()
    if so_ref:
        out["so_reference"] = so_ref
    return out


def _parsed_line_items_from_llm(
    llm: LlmDocumentResult,
    *,
    vendor: str | None,
    invoice_no: str | None,
    po_reference: str | None,
    so_reference: str | None,
    cost_centre: str | None,
    extracted_fields: dict[str, str],
) -> list[ParsedLineItem]:
    from app.services.extraction.line_items_parser import enrich_parsed_line_items
    from app.services.extraction.line_items_sanitizer import sanitize_line_items

    items = [
        ParsedLineItem(
            description=row.description or None,
            qty=row.qty,
            unit_price=row.unit_price,
            amount=row.amount,
        )
        for row in llm.line_items
    ]
    cleaned = sanitize_line_items(
        items,
        extracted_fields=extracted_fields,
        vendor=vendor,
        invoice_no=invoice_no,
        po_reference=po_reference,
        so_reference=so_reference,
        cost_centre=cost_centre,
    )
    return enrich_parsed_line_items(cleaned)


async def classify_document_only(
    ocr: OcrArtifact,
    *,
    org: OrgContext,
    document_types: Sequence[DocumentTypeDefinition],
    few_shots: Sequence[dict[str, str]] | None = None,
) -> LlmDocumentResult | None:
    settings = get_settings()
    user = build_llm_user_payload(
        ocr=ocr,
        org=org,
        document_types=document_types,
        few_shots=few_shots,
    )
    raw = await chat_json_async(
        system=build_classify_system_prompt(org),
        user=user,
        timeout_seconds=settings.runtime_llm_timeout_seconds,
        require_runtime=True,
    )
    if raw is None:
        return None
    try:
        result = LlmDocumentResult.model_validate(_normalize_llm_raw(raw))
        result.raw = raw
        return result
    except ValidationError as exc:
        logger.warning("llm_classify_invalid", error=str(exc))
        return None


async def extract_document_fields(
    ocr: OcrArtifact,
    *,
    org: OrgContext,
    document_types: Sequence[DocumentTypeDefinition],
    confirmed_dt: str,
    few_shots: Sequence[dict[str, str]] | None = None,
) -> LlmDocumentResult | None:
    settings = get_settings()
    dt_token = confirmed_dt.strip().upper()
    custom_keys = _custom_keys_for_dt(document_types, dt_token)
    system, user = build_structure_extract_prompts(
        ocr=ocr,
        org=org,
        document_types=document_types,
        confirmed_dt=dt_token,
        few_shots=few_shots,
        custom_keys=custom_keys,
    )
    raw = await chat_json_async(
        system=system,
        user=user,
        timeout_seconds=settings.runtime_llm_timeout_seconds,
        require_runtime=True,
    )
    if raw is None:
        return None
    try:
        normalized = _normalize_llm_raw(raw, custom_keys=custom_keys)
        normalized["suggested_dt"] = dt_token
        result = LlmDocumentResult.model_validate(normalized)
        result.raw = raw
        return result
    except ValidationError as exc:
        logger.warning("llm_extract_invalid", error=str(exc))
        return None


async def classify_and_extract(
    ocr: OcrArtifact,
    *,
    org: OrgContext,
    document_types: Sequence[DocumentTypeDefinition],
    few_shots: Sequence[dict[str, str]] | None = None,
) -> LlmDocumentResult | None:
    settings = get_settings()
    custom_keys = custom_extraction_field_keys(document_types)
    user = build_llm_user_payload(
        ocr=ocr,
        org=org,
        document_types=document_types,
        few_shots=few_shots,
        custom_keys=custom_keys,
    )
    raw = await chat_json_async(
        system=build_combined_system_prompt(org, custom_keys=custom_keys),
        user=user,
        timeout_seconds=settings.runtime_llm_timeout_seconds,
        require_runtime=True,
    )
    if raw is None:
        return None
    try:
        result = LlmDocumentResult.model_validate(_normalize_llm_raw(raw, custom_keys=custom_keys))
        result.raw = raw
        return result
    except ValidationError as exc:
        logger.warning("llm_document_invalid", error=str(exc))
        return None


def _parse_date(raw: str) -> date | None:
    return parse_flexible_date(raw)


def _parse_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def llm_result_to_invoice_data(
    llm: LlmDocumentResult,
    *,
    ocr: OcrArtifact,
    custom_keys: Sequence[str] | None = None,
    org: OrgContext | None = None,
) -> InvoiceData:
    org_ctx = org or OrgContext()
    ocr_text = ocr.text or None
    _parties, perspective, finance, party_fields = apply_party_normalization_to_llm(
        llm,
        ocr_text=ocr_text,
        org=org_ctx,
    )

    line_items: list[ParsedLineItem] = []
    extracted = harvest_custom_fields_from_llm_raw(llm.raw, custom_keys=custom_keys)
    extracted = {
        **party_fields,
        **_canonical_scalar_extracted_fields(llm),
        **_bank_extracted_fields(llm),
        **(llm.extracted_fields or {}),
        **extracted,
    }
    line_items = _parsed_line_items_from_llm(
        llm,
        vendor=finance.get("vendor"),
        invoice_no=(llm.invoice_no or "").strip() or None,
        po_reference=(llm.po_reference or "").strip() or None,
        so_reference=(llm.so_reference or "").strip() or extracted.get("so_reference"),
        cost_centre=(llm.cost_centre or "").strip() or None,
        extracted_fields=extracted,
    )
    from app.services.extraction.gst_rate import parse_gst_rate_percent, resolve_gst_rate_percent

    parsed = InvoiceData(
        vendor=finance.get("vendor"),
        abn=finance.get("abn"),
        billing_address=finance.get("billing_address"),
        invoice_no=(llm.invoice_no or "").strip() or None,
        invoice_date=_parse_date(llm.invoice_date),
        due_date=_parse_date(llm.due_date),
        currency=_resolved_currency(llm),
        subtotal=llm.subtotal,
        gst=llm.gst,
        gst_rate=parse_gst_rate_percent(llm.gst_rate),
        total=llm.total,
        po_reference=(llm.po_reference or "").strip() or None,
        cost_centre=(llm.cost_centre or "").strip() or None,
        bank_bsb=(llm.bank_bsb or "").strip() or None,
        bank_account=(llm.bank_account or "").strip() or None,
        line_items=line_items,
        document_text=ocr_text,
        document_heading=(llm.document_heading or "").strip() or None,
        extracted_fields=extracted,
        raw_fields={
            "llm_suggested_dt": llm.suggested_dt,
            "llm_confidence": llm.confidence,
            "llm_perspective": llm.perspective,
            "perspective": perspective,
            "seller": llm.seller.model_dump(),
            "buyer": llm.buyer.model_dump(),
            "layout_kv": ocr.layout_kv,
            "extracted_fields": extracted,
        },
    )
    parsed.gst_rate = resolve_gst_rate_percent(parsed)
    return parsed


def apply_document_type_to_invoice(
    invoice: object,
    *,
    code: str,
    confidence: float,
    llm_suggested_dt: str | None = None,
    llm_confidence: float | None = None,
) -> None:
    token = (code or "").strip().upper()
    setattr(invoice, "document_type_code", token or None)
    setattr(invoice, "document_type_confidence", round(confidence, 4))
    if llm_suggested_dt is not None:
        setattr(invoice, "llm_suggested_dt", (llm_suggested_dt or "").strip().upper() or None)
    if llm_confidence is not None:
        setattr(invoice, "llm_confidence", round(llm_confidence, 4))
