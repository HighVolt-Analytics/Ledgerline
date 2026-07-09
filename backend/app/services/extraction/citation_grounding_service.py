"""Verify LLM field citations against OCR text and layout."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from app.schemas.llm_document import FieldCitation, LlmDocumentResult
from app.schemas.ocr_artifact import OcrArtifact
from app.services.extraction.field_grounding_service import value_grounded_in_ocr

_CITATION_CONFIDENCE_CAP = 0.5


@dataclass(frozen=True)
class CitationVerificationResult:
    field_key: str
    verified: bool
    failure_reason: str | None = None


def _normalize_snippet(snippet: str) -> str:
    return re.sub(r"\s+", " ", (snippet or "").strip())


def _snippet_on_page(snippet: str, page: int | None, payload: dict[str, Any]) -> bool:
    if page is None:
        return True
    layout = payload.get("layout_paragraphs")
    if not isinstance(layout, list):
        return True
    target_page = max(0, int(page) - 1)
    normalized = _normalize_snippet(snippet).lower()
    if not normalized:
        return True
    for row in layout:
        if not isinstance(row, dict):
            continue
        page_index = int(row.get("page_index", 0) or 0)
        if page_index != target_page:
            continue
        text = str(row.get("text") or "").lower()
        if normalized in text:
            return True
    return False


def _line_item_row_grounded_in_ocr(row: object, ocr_text: str) -> bool:
    if not isinstance(row, dict):
        return False
    description = str(row.get("description") or "").strip()
    qty = row.get("qty")
    if not description:
        return False
    if value_grounded_in_ocr(description, ocr_text):
        return True
    if qty is not None and str(qty).strip():
        probe = f"{description} {qty}".strip()
        if value_grounded_in_ocr(probe, ocr_text):
            return True
    return False


def _line_items_table_header_grounded(ocr_text: str) -> bool:
    corpus = (ocr_text or "").lower()
    if not corpus:
        return False
    header_signals = ("qty", "quantity", "model", "part", "description", "component")
    hits = sum(1 for signal in header_signals if signal in corpus)
    if hits >= 3:
        return True
    if "qty" in corpus or "quantity" in corpus:
        if any(token in corpus for token in ("part", "model", "component", "description")):
            return True
    return False


def verify_parsed_line_items_citation(
    parsed_line_items: list[object],
    *,
    ocr_text: str,
    ocr_payload: dict[str, Any] | None = None,
) -> CitationVerificationResult:
    """Verify merged line items against OCR (post-merge citation path)."""
    _ = ocr_payload
    if not parsed_line_items:
        return CitationVerificationResult(field_key="line_items", verified=True)
    from app.services.invoice.invoice_data import ParsedLineItem

    rows = [
        {
            "description": item.description,
            "qty": item.qty,
        }
        for item in parsed_line_items
        if isinstance(item, ParsedLineItem)
    ]
    if rows and all(_line_item_row_grounded_in_ocr(row, ocr_text) for row in rows):
        return CitationVerificationResult(field_key="line_items", verified=True)
    if _line_items_table_header_grounded(ocr_text) and rows:
        return CitationVerificationResult(field_key="line_items", verified=True)
    return CitationVerificationResult(
        field_key="line_items",
        verified=False,
        failure_reason="missing_citation",
    )


def verify_field_citation(
    field_key: str,
    value: Any,
    citation: FieldCitation | None,
    *,
    ocr_text: str,
    payload: dict[str, Any] | None = None,
) -> CitationVerificationResult:
    token = str(field_key or "").strip().lower()
    if token == "line_items":
        if not value or value == []:
            return CitationVerificationResult(field_key=token, verified=True)
        if isinstance(value, list):
            rows_grounded = [_line_item_row_grounded_in_ocr(row, ocr_text) for row in value]
            if rows_grounded and all(rows_grounded):
                return CitationVerificationResult(field_key=token, verified=True)
            if _line_items_table_header_grounded(ocr_text):
                return CitationVerificationResult(field_key=token, verified=True)
        if citation is not None and _normalize_snippet(citation.snippet):
            if value_grounded_in_ocr(citation.snippet, ocr_text):
                return CitationVerificationResult(field_key=token, verified=True)
        return CitationVerificationResult(
            field_key=token,
            verified=False,
            failure_reason="missing_citation",
        )
    if value is None or (isinstance(value, str) and not str(value).strip()):
        return CitationVerificationResult(field_key=token, verified=True)
    if citation is None or not _normalize_snippet(citation.snippet):
        return CitationVerificationResult(
            field_key=token,
            verified=False,
            failure_reason="missing_citation",
        )
    snippet = citation.snippet
    if not value_grounded_in_ocr(snippet, ocr_text):
        return CitationVerificationResult(
            field_key=token,
            verified=False,
            failure_reason="snippet_not_in_ocr",
        )
    if payload and not _snippet_on_page(snippet, citation.page, payload):
        return CitationVerificationResult(
            field_key=token,
            verified=False,
            failure_reason="page_mismatch",
        )
    return CitationVerificationResult(field_key=token, verified=True)


def _field_value_from_llm(result: LlmDocumentResult, field_key: str) -> Any:
    token = field_key.strip().lower()
    if token in result.extracted_fields:
        return result.extracted_fields.get(token)
    if hasattr(result, token):
        return getattr(result, token)
    if token == "vendor" and result.seller.name:
        return result.seller.name
    if token in {"seller_name", "seller_tax_id", "seller_abn", "seller_address"}:
        party = result.seller
        mapping = {
            "seller_name": party.name,
            "seller_tax_id": party.tax_id,
            "seller_abn": party.abn or party.tax_id,
            "seller_address": party.address,
        }
        return mapping.get(token)
    if token in {"buyer_name", "buyer_tax_id", "buyer_abn", "buyer_address"}:
        party = result.buyer
        mapping = {
            "buyer_name": party.name,
            "buyer_tax_id": party.tax_id,
            "buyer_abn": party.abn or party.tax_id,
            "buyer_address": party.address,
        }
        return mapping.get(token)
    return None


def verify_and_apply_citations(
    result: LlmDocumentResult,
    ocr: OcrArtifact,
    *,
    field_keys: list[str] | None = None,
) -> tuple[LlmDocumentResult, list[CitationVerificationResult]]:
    """Verify citations and cap field_confidence for failed fields."""
    payload = ocr.payload_json or {}
    keys = field_keys or list(result.field_confidence.keys()) or list(result.field_citations.keys())
    verifications: list[CitationVerificationResult] = []
    confidence = dict(result.field_confidence)
    for key in keys:
        token = str(key or "").strip().lower()
        if not token:
            continue
        citation = result.field_citations.get(token)
        value = _field_value_from_llm(result, token)
        verification = verify_field_citation(
            token,
            value,
            citation,
            ocr_text=ocr.text or "",
            payload=payload,
        )
        verifications.append(verification)
        if not verification.verified and token in confidence:
            confidence[token] = min(confidence[token], _CITATION_CONFIDENCE_CAP)
        elif not verification.verified:
            confidence[token] = _CITATION_CONFIDENCE_CAP
    return result.model_copy(update={"field_confidence": confidence}), verifications


def citation_audit_detail(verifications: list[CitationVerificationResult]) -> dict[str, Any]:
    failed = [
        {
            "field": row.field_key,
            "reason": row.failure_reason,
        }
        for row in verifications
        if not row.verified
    ]
    return {
        "citation_verified_count": sum(1 for row in verifications if row.verified),
        "citation_failed": failed,
    }
