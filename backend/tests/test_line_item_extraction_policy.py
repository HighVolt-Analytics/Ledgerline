"""Application-level line-item extraction policy and ranked fallback."""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

from app.services.extraction.line_item_extraction_policy import (
    LineDocumentShape,
    classify_line_document_shape,
    document_requires_line_items,
    is_sparse_ocr_payload,
    line_items_extraction_incomplete,
    pick_best_fallback_tier,
)
from app.services.extraction.line_items_fallback_service import (
    FALLBACK_PDF_TABLES,
    FALLBACK_STRUCTURED,
    apply_line_items_fallback,
)
from app.services.invoice.invoice_data import InvoiceData, ParsedLineItem
from app.services.invoice.invoice_pipeline_phases import evaluate_line_item_review_gate


def test_classify_money_over_address_qty_noise() -> None:
    text = """
INVOICE
Description Qty in units Price per Amount in USD
Sale of VERs 100000 0.70 $70,000
Site Office: Plot No.4 Andhra Pradesh - 51810
"""
    shape = classify_line_document_shape(text, {})
    assert shape == LineDocumentShape.MONEY


def test_classify_grn_bundle_as_qty_only() -> None:
    text = "GOODS RECEIPT\nItem Description Qty Received\nApples 10"
    shape = classify_line_document_shape(
        text,
        {},
        dt_definition=SimpleNamespace(purchase_bundle_role="grn"),
    )
    assert shape == LineDocumentShape.QTY_ONLY


def test_sparse_vision_payload_detected() -> None:
    assert is_sparse_ocr_payload({"provider": "vision_dt_scoped", "page_count": 1}) is True
    assert is_sparse_ocr_payload({"di_line_items": [{"description": "x", "amount": "1"}]}) is False


def test_pick_best_prefers_payload_over_text() -> None:
    payload_rows = [
        ParsedLineItem(description="A", amount=Decimal("10"), source="di"),
    ]
    text_rows = [
        ParsedLineItem(description="noise", qty=Decimal("51810"), source="regex"),
        ParsedLineItem(description="A", amount=Decimal("10"), source="regex"),
    ]
    picked = pick_best_fallback_tier(
        [
            ("fallback_structured", text_rows, 40),
            ("fallback_structured", payload_rows, 10),
        ]
    )
    assert picked is not None
    assert picked[1] == payload_rows


def test_fallback_prefers_pdf_when_ocr_sparse(monkeypatch, tmp_path) -> None:
    pdf = tmp_path / "inv.pdf"
    pdf.write_bytes(b"%PDF-1.4")

    def _fake_pdf(_path: str, **_kwargs):
        return [
            ParsedLineItem(
                description="Office chairs",
                qty=Decimal("2"),
                unit_price=Decimal("100"),
                amount=Decimal("200"),
                source="table",
            )
        ]

    monkeypatch.setattr(
        "app.services.extraction.layout_field_extractor.parse_line_items_from_pdf_path",
        _fake_pdf,
    )
    # Money-ish document_text that could also regex-parse, but sparse OCR → PDF wins.
    text = "INVOICE\nDescription Qty Unit Price Amount\nOffice chairs 2 100.00 200.00\nTotal $200"
    updated, tier = apply_line_items_fallback(
        InvoiceData(document_text=text, total=Decimal("200")),
        ocr_text=text,
        ocr_payload={"provider": "vision_dt_scoped", "page_count": 1},
        pdf_path=str(pdf),
    )
    assert tier == FALLBACK_PDF_TABLES
    assert updated.line_items[0].amount == Decimal("200")


def test_money_fallback_never_keeps_address_qty_bleed() -> None:
    text = """
TAX INVOICE
Total Amount: $70,000
Site Office: Plot No.4 Gani Kurnool 51810
PH: 0432 423 9000
"""
    updated, tier = apply_line_items_fallback(
        InvoiceData(document_text=text, total=Decimal("70000")),
        ocr_text=text,
    )
    # No real product money rows → empty (hold), not address/phone as lines.
    assert updated.line_items == []
    assert tier is None


def test_di_money_payload_wins_over_text_noise() -> None:
    text = "Prinsengracht 769\nPage 1 of 2\n$45.03 USD due"
    payload = {
        "di_line_items": [
            {
                "description": "Minimum amount",
                "qty": "1",
                "unit_price": "44.61",
                "amount": "44.61",
            }
        ]
    }
    updated, tier = apply_line_items_fallback(
        InvoiceData(vendor="Weaviate", total=Decimal("45.03"), document_text=text),
        ocr_text=text,
        ocr_payload=payload,
    )
    assert tier == FALLBACK_STRUCTURED
    assert len(updated.line_items) == 1
    assert updated.line_items[0].amount == Decimal("44.61")
    assert not any("Prinsengracht" in (r.description or "") for r in updated.line_items)


def test_line_items_missing_gate_when_dt_requires_lines() -> None:
    dt = SimpleNamespace(
        extraction_fields=["vendor", "total", "line_items"],
        required_fields=["vendor", "total", "line_items"],
        compulsory_fields=["vendor", "total", "line_items"],
        absent_fields=[],
        playbook_required_fields=["vendor", "total", "line_items"],
    )
    assert document_requires_line_items(dt) is True
    passed, _conf, reasons = evaluate_line_item_review_gate(
        InvoiceData(total=Decimal("100"), document_text="INVOICE Total $100"),
        dt_definition=dt,
    )
    assert passed is False
    assert "line_items_missing" in reasons
    assert line_items_extraction_incomplete(
        wants_line_items=True,
        rows=[],
        shape=LineDocumentShape.MONEY,
    )

def test_advance_kinds_do_not_hard_require_line_items() -> None:
    from app.schemas.document_type import DocumentTypeDefinition
    from app.services.extraction.line_item_extraction_policy import (
        team_expense_hard_requires_line_items,
    )

    advance = DocumentTypeDefinition(
        code="DT-09",
        title="Advance requisition",
        short_title="Advance",
        klass="Transactional",
        posting="Yes",
        route_target="Team Expenses",
        playbook_profile="employee_claim",
        team_expense_kind="advance_requisition",
        extraction_fields=["vendor", "total", "line_items"],
    )
    assert document_requires_line_items(advance) is True
    assert team_expense_hard_requires_line_items(advance) is False


def test_legacy_against_advance_dt_treated_as_claim_for_line_items() -> None:
    """Legacy against-advance pin clears on DT; kind normalizes to claim → may require lines."""
    from app.schemas.document_type import DocumentTypeDefinition
    from app.services.extraction.line_item_extraction_policy import (
        team_expense_hard_requires_line_items,
    )

    legacy = DocumentTypeDefinition(
        code="DT-10",
        title="Expense against advance",
        short_title="Against",
        klass="Transactional",
        posting="Yes",
        route_target="Team Expenses",
        playbook_profile="employee_claim",
        team_expense_kind="expense_against_advance",
        extraction_fields=["vendor", "total", "line_items"],
    )
    assert legacy.team_expense_kind == ""
    assert document_requires_line_items(legacy) is True
    assert team_expense_hard_requires_line_items(legacy) is True
    assert (
        team_expense_hard_requires_line_items(
            legacy, team_expense_kind="expense_against_advance"
        )
        is True
    )
