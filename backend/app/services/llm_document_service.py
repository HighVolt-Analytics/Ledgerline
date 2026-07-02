"""Runtime LLM document classification and field extraction."""

from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Sequence

from pydantic import ValidationError

from app.config import get_settings
from app.schemas.document_type import DocumentTypeDefinition
from app.schemas.llm_document import LlmDocumentResult, LlmLineItem, LlmParty
from app.schemas.ocr_artifact import OcrArtifact
from app.services.azure_openai_client import chat_json_async
from app.services.invoice_data import InvoiceData, ParsedLineItem
from app.services.tenant_org_context import OrgContext
from app.services.classifier_catalogue_compiler import compile_catalogue_recognition
from app.services.document_type_field_keys import CANONICAL_EXTRACTION_FIELD_KEYS
from app.services.extraction_field_values import (
    custom_extraction_field_keys,
    custom_extraction_field_keys_for_dt,
    harvest_custom_fields_from_llm_raw,
    normalize_extracted_fields_map,
)
from app.services.tenant_org_context import OrgContext
from app.utils.logger import get_logger

logger = get_logger(__name__)

_LLM_SYSTEM = """You classify finance documents for accounts payable.
Return JSON only with keys:
suggested_dt, confidence, reasoning, perspective,
seller, buyer, invoice_no, invoice_date, due_date, po_reference,
subtotal, gst, total, currency, abn, vendor, document_heading, line_items, field_confidence, extracted_fields.

Rules:
- suggested_dt must be one of the catalogue codes provided, or empty string if unsure.
- confidence is 0.0-1.0 for the document type choice.
- perspective is purchase | sales | unknown (tenant perspective is buyer/AP unless they are the seller).
- seller and buyer are objects with name and abn.
- line_items is a list of {description, amount, qty, unit_price}.
- field_confidence maps field names to 0.0-1.0.
- Use OCR text faithfully; do not invent amounts or parties.
- few_shot_examples are prior reviewer corrections for this tenant. When document_heading or text_excerpt
  closely matches a few-shot example, strongly prefer that example's human_confirmed_dt over catalogue defaults.
- When llm_suggested_dt was wrong but human_confirmed_dt was chosen, learn from the note and excerpt.
- extracted_fields is an optional object for keys listed in custom_extraction_fields; use string values only."""

_LLM_CLASSIFY_SYSTEM = """You classify finance documents for accounts payable.
Return JSON only with keys:
suggested_dt, confidence, reasoning, perspective, seller, buyer, document_heading.

Rules:
- suggested_dt must be one of the catalogue codes provided, or empty string if unsure.
- confidence is 0.0-1.0 for the document type choice.
- perspective is purchase | sales | unknown (tenant perspective is buyer/AP unless they are the seller).
- seller and buyer are objects with name and abn.
- Do not extract invoice amounts, line items, or dates — classification only.
- few_shot_examples are prior reviewer corrections for this tenant. When document_heading or text_excerpt
  closely matches a few-shot example, strongly prefer that example's human_confirmed_dt over catalogue defaults.
- Examples with vendor_key match the sender/vendor — prefer those when the layout matches that supplier.
- When recognition_rules is present on a catalogue row, treat it as deterministic match hints for that code."""

_LLM_EXTRACT_SYSTEM = """You extract accounts-payable fields from finance documents.
Return JSON only with keys:
suggested_dt, confidence, reasoning, perspective,
seller, buyer, invoice_no, invoice_date, due_date, po_reference,
subtotal, gst, total, currency, abn, vendor, document_heading, line_items, field_confidence, extracted_fields.

Rules:
- suggested_dt must match confirmed_dt from the user payload.
- confidence is 0.0-1.0 for the document type choice.
- perspective is purchase | sales | unknown.
- seller and buyer are objects with name and abn.
- line_items is a list of {description, amount, qty, unit_price}.
- field_confidence maps field names to 0.0-1.0.
- Use OCR text faithfully; do not invent amounts or parties.
- extracted_fields is an optional object for keys listed in custom_extraction_fields; use string values only."""


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


def build_extract_system_prompt(org: OrgContext) -> str:
    parts = [_LLM_EXTRACT_SYSTEM.strip(), "", "Tenant context:"]
    parts.extend(f"- {line}" for line in _org_role_lines(org))
    return "\n".join(parts)


def build_combined_system_prompt(org: OrgContext) -> str:
    parts = [_LLM_SYSTEM.strip(), "", "Tenant context:"]
    parts.extend(f"- {line}" for line in _org_role_lines(org))
    if org.intake_summary.strip():
        parts.extend(["", f"Typical intake: {org.intake_summary.strip()}"])
    if org.classification_hints.strip():
        parts.extend(["", f"Tenant classification guidance: {org.classification_hints.strip()}"])
    return "\n".join(parts)


def _catalogue_rows(document_types: Sequence[DocumentTypeDefinition]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for defn in document_types:
        if not defn.enabled:
            continue
        hint = getattr(defn, "llm_hint", None) or ""
        recognition = compile_catalogue_recognition(defn)
        row: dict[str, str] = {
            "code": defn.code.strip().upper(),
            "title": defn.title,
            "one_line": defn.one_line,
            "llm_hint": str(hint).strip(),
        }
        if recognition:
            row["recognition_rules"] = recognition
        rows.append(row)
    return rows


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
        "canonical_extraction_fields": sorted(CANONICAL_EXTRACTION_FIELD_KEYS),
        "ocr": {
            "text_excerpt": excerpt,
            "layout_kv": ocr.layout_kv,
            "text_length": ocr.text_length,
        },
    }
    if confirmed_dt:
        payload["confirmed_dt"] = confirmed_dt.strip().upper()
    return json.dumps(payload, default=str)


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
        "currency",
        "abn",
        "document_heading",
    ):
        if out.get(key) is None:
            out[key] = ""
    for money in ("subtotal", "gst", "total"):
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
    custom_keys = custom_extraction_field_keys_for_dt(document_types, dt_token)
    if not custom_keys:
        custom_keys = custom_extraction_field_keys(document_types)
    user = build_llm_user_payload(
        ocr=ocr,
        org=org,
        document_types=document_types,
        few_shots=few_shots,
        custom_keys=custom_keys,
        confirmed_dt=dt_token,
    )
    raw = await chat_json_async(
        system=build_extract_system_prompt(org),
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
    user = build_llm_user_payload(
        ocr=ocr,
        org=org,
        document_types=document_types,
        few_shots=few_shots,
    )
    raw = await chat_json_async(
        system=build_combined_system_prompt(org),
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
        logger.warning("llm_document_invalid", error=str(exc))
        return None


def _parse_date(raw: str) -> date | None:
    token = (raw or "").strip()
    if not token:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(token[:10], fmt).date()
        except ValueError:
            continue
    return None


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
    from app.services.counterparty_service import counterparty_side_for_perspective, resolve_counterparty_name
    from app.utils.abn_validator import storage_abn

    org_ctx = org or OrgContext()
    side = counterparty_side_for_perspective(llm.perspective)
    if side == "party" and org_ctx.default_perspective == "seller":
        side = "customer"
    elif side == "party":
        side = "vendor"

    vendor = resolve_counterparty_name(
        side=side,
        org=org_ctx,
        buyer_name=llm.buyer.name,
        buyer_abn=llm.buyer.abn,
        seller_name=llm.seller.name,
        seller_abn=llm.seller.abn,
        generic_name=llm.vendor,
        document_text=ocr.text or None,
    )
    abn = storage_abn((llm.abn or llm.seller.abn or llm.buyer.abn or "").strip() or None)
    line_items: list[ParsedLineItem] = []
    for row in llm.line_items:
        line_items.append(
            ParsedLineItem(
                description=row.description or None,
                qty=row.qty,
                unit_price=row.unit_price,
                amount=row.amount,
            )
        )
    extracted = harvest_custom_fields_from_llm_raw(llm.raw, custom_keys=custom_keys)
    return InvoiceData(
        vendor=vendor,
        abn=abn,
        invoice_no=(llm.invoice_no or "").strip() or None,
        invoice_date=_parse_date(llm.invoice_date),
        due_date=_parse_date(llm.due_date),
        currency=(llm.currency or "AUD").strip().upper() or "AUD",
        subtotal=llm.subtotal,
        gst=llm.gst,
        total=llm.total,
        po_reference=(llm.po_reference or "").strip() or None,
        line_items=line_items,
        document_text=ocr.text or None,
        document_heading=(llm.document_heading or "").strip() or None,
        extracted_fields=extracted,
        raw_fields={
            "llm_suggested_dt": llm.suggested_dt,
            "llm_confidence": llm.confidence,
            "llm_perspective": llm.perspective,
            "seller": llm.seller.model_dump(),
            "buyer": llm.buyer.model_dump(),
            "layout_kv": ocr.layout_kv,
            "extracted_fields": extracted,
        },
    )


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
