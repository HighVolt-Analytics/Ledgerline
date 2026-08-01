"""Unit tests for vision type-suggest parse/persist."""

from __future__ import annotations

from app.models.invoice import Invoice, InvoiceStatus
from app.services.invoice.vision_type_suggest import (
    DOCUMENT_SUMMARY_KEY,
    VISION_TYPE_SUGGEST_JSON_KEYS,
    document_role_hints_from_invoice,
    parse_vision_type_suggest_raw,
    persist_vision_type_suggest_to_invoice,
)
from app.tenant_ids import TESTING_TENANT_UUID


def test_type_suggest_json_keys_include_summary_not_money() -> None:
    assert "document_heading" in VISION_TYPE_SUGGEST_JSON_KEYS
    assert "canonical_document_type" in VISION_TYPE_SUGGEST_JSON_KEYS
    assert "document_summary" in VISION_TYPE_SUGGEST_JSON_KEYS
    assert "document_role_hints" in VISION_TYPE_SUGGEST_JSON_KEYS
    assert "total" not in VISION_TYPE_SUGGEST_JSON_KEYS
    assert "invoice_no" not in VISION_TYPE_SUGGEST_JSON_KEYS


def test_parse_vision_type_suggest_success() -> None:
    result = parse_vision_type_suggest_raw(
        {
            "document_heading": "EXPENSE REIMBURSEMENT FORM",
            "canonical_document_type": "Expense claim",
            "perspective": "internal",
            "document_summary": (
                "Internal employee expense claim form for reimbursement; "
                "no supplier tax invoice."
            ),
            "document_role_hints": {
                "has_po_reference": "false",
                "has_invoice_number": "false",
                "is_supporting_only": "false",
            },
            "confidence": 0.91,
            "reason": "clear title",
        },
        provider="gemini_vision",
        page_count=1,
    )
    assert result.success is True
    assert result.document_heading == "EXPENSE REIMBURSEMENT FORM"
    assert result.document_summary.startswith("Internal employee")
    assert result.document_role_hints.get("has_po_reference") == "false"
    assert result.perspective in {"internal", "purchase", "sales", "unknown"}


def test_parse_vision_type_suggest_requires_summary() -> None:
    result = parse_vision_type_suggest_raw(
        {
            "document_heading": "TAX INVOICE",
            "canonical_document_type": "Tax Invoice",
            "perspective": "purchase",
            "document_summary": "",
            "document_role_hints": {},
            "confidence": 0.95,
            "reason": "title only",
        },
        provider="gemini_vision",
        page_count=1,
    )
    assert result.success is False
    assert result.fail_reason == "no_summary"


def test_parse_vision_type_suggest_low_confidence_fails() -> None:
    result = parse_vision_type_suggest_raw(
        {
            "document_heading": "FORM",
            "canonical_document_type": "",
            "perspective": "unknown",
            "document_summary": "Unclear form.",
            "confidence": 0.2,
            "reason": "blurry",
        },
        provider="gemini_vision",
        page_count=1,
    )
    assert result.success is False
    assert result.fail_reason in {"low_confidence", "no_identity"}


def test_persist_type_suggest_summary_and_seeds_po() -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.PENDING,
        raw_file_path="/tmp/x.pdf",
        total=None,
        invoice_no=None,
        po_reference=None,
    )
    result = parse_vision_type_suggest_raw(
        {
            "document_heading": "TAX INVOICE",
            "canonical_document_type": "Tax Invoice",
            "perspective": "purchase",
            "document_summary": (
                "Supplier tax invoice from Everest Furnishings to the buyer, "
                "issued against purchase order PO-TEST-001."
            ),
            "document_role_hints": {
                "has_po_reference": True,
                "has_invoice_number": "true",
                "is_credit_note": "false",
                "is_supporting_only": "false",
            },
            "confidence": 0.9,
            "reason": "ok",
        },
        provider="gemini_vision",
        page_count=1,
    )
    assert result.success is True
    persist_vision_type_suggest_to_invoice(inv, result)
    assert inv.document_heading == "TAX INVOICE"
    assert inv.total is None
    assert inv.invoice_no is None
    assert (inv.po_reference or "").upper().startswith("PO-TEST")
    fields = inv.extracted_fields or {}
    assert fields.get("canonical_document_type")
    assert fields.get(DOCUMENT_SUMMARY_KEY)
    hints = document_role_hints_from_invoice(inv)
    assert hints.get("has_po_reference") == "true"
    assert fields.get("vision_type_suggest_confidence")
    assert "total" not in fields
