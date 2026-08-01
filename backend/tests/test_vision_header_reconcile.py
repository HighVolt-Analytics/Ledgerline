"""Tests for post-vision currency/total reconcile + header field grounding."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.models.invoice import Invoice, InvoiceStatus
from app.services.invoice.vision_header_extract import (
    VisionHeaderExtractResult,
    vision_header_should_review,
)
from app.services.invoice.vision_header_reconcile import (
    apply_vision_header_text_reconcile,
    ground_vision_header_result,
    prefer_grand_total_over_subtotal,
    reconcile_currency_from_text,
)
from app.tenant_ids import TESTING_TENANT_UUID


def test_rupee_overrides_wrong_aud() -> None:
    iso, symbol, reason = reconcile_currency_from_text(
        current_currency="AUD",
        text="TAX INVOICE\nTotal ₹9800.53\nMakeMyTrip (India)",
    )
    assert iso == "INR"
    assert symbol is None
    assert "override" in reason


def test_bare_dollar_overrides_uncorroborated_aud_with_usd() -> None:
    iso, symbol, reason = reconcile_currency_from_text(
        current_currency="AUD",
        text=(
            "Rosty.ai x LML Content Invoice\n"
            "Total $1,399.00\n"
            "50% Advance $699.50\n"
            "Enough body text so grounding length threshold is satisfied for currency checks."
        ),
    )
    assert iso == "USD"
    assert symbol is None
    assert "override" in reason


def test_amd_processor_brand_clears_invented_armenian_dram() -> None:
    iso, symbol, reason = reconcile_currency_from_text(
        current_currency="AMD",
        text=(
            "COMMERCIAL INVOICE Spectra Innovations Pte Ltd\n"
            "1 AMD Ryzen 5 5500 Desktop Processor 10 53.00 530.00\n"
            "2 AMD Ryzen 7 5700G Desktop Processor 30 145.00 4,350.00\n"
            "PAYMENT: SIGHT L/C\n"
            "Total 34,410.95\n"
            "Enough body text so grounding length threshold is satisfied for currency checks."
        ),
    )
    assert iso == ""
    assert symbol is None
    assert "cleared" in reason


def test_thin_text_keeps_vision_iso() -> None:
    iso, symbol, reason = reconcile_currency_from_text(
        current_currency="USD",
        text="25-Jul-2025 17:36 IST",
    )
    assert iso == "USD"
    assert symbol is None
    assert "thin_text" in reason


def test_bare_dollar_empty_fills_usd() -> None:
    iso, symbol, reason = reconcile_currency_from_text(
        current_currency="",
        text="Invoice\nTotal $100.00",
    )
    assert iso == "USD"
    assert symbol is None
    assert "fill" in reason or "ocr" in reason


def test_us_prefix_keeps_usd() -> None:
    iso, symbol, reason = reconcile_currency_from_text(
        current_currency="USD",
        text="MongoDB Limited\nTotal US$37.08",
    )
    assert iso == "USD"
    assert symbol is None
    assert "corroborated" in reason or "confirms" in reason or "ocr" in reason


def test_prefer_grand_total_over_subtotal_mongodb_style() -> None:
    text = (
        "server hour $32.25\n"
        "Subtotal $33.70\n"
        "Value-Added Tax $3.38\n"
        "Credits $0.00\n"
        "Total $37.08\n"
    )
    money, reason = prefer_grand_total_over_subtotal(Decimal("33.70"), text)
    assert money == Decimal("37.08")
    assert "upgraded" in reason


def test_apply_reconcile_updates_invoice() -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.EXCEPTION,
        currency="AUD",
        total=Decimal("9434.00"),
        extracted_fields={"currency": "AUD", "total": "9434.00"},
    )
    text = (
        "MakeMyTrip (India) Private Limited\n"
        "Subtotal ₹9434.00\n"
        "Total ₹9800.53\n"
    )
    detail = apply_vision_header_text_reconcile(inv, text)
    assert inv.currency == "INR"
    assert inv.total == Decimal("9800.53")
    assert (inv.extracted_fields or {}).get("currency") == "INR"
    assert detail["currency_after"] == "INR"
    assert "upgraded" in str(detail["total_reason"])


def test_ground_recovers_inv_no_from_text_when_vision_ungrounded() -> None:
    from datetime import date
    from decimal import Decimal

    from app.services.invoice.vision_header_extract import VisionHeaderExtractResult
    from app.services.invoice.vision_header_reconcile import ground_vision_header_result

    text = (
        "PERMIT NO : OD5I458006S\n"
        "CARGO CLEARANCE PERMIT\n"
        "SKYLIFT CONSOLIDATOR (PTE) LTD\n"
        "UNITS (INV NO: 250970286) 5622.17\n"
        "UNIQUE REF : 197700341D 20250905 5701\n"
        "VALIDITY PERIOD : 05/09/2025\n"
        + ("padding " * 20)
    )
    result = VisionHeaderExtractResult(
        success=True,
        document_heading="CARGO CLEARANCE PERMIT",
        counterparty_name="SKYLIFT CONSOLIDATOR (PTE) LTD",
        invoice_no="WRONG-FAKE-999",
        other_reference="197700341D 20250905 5701",
        invoice_date=date(2025, 9, 5),
        total=Decimal("0.00"),
        confidence=0.9,
        reason="x",
        provider="test",
    )
    grounded, detail = ground_vision_header_result(result, text)
    assert grounded.invoice_no == "250970286"
    assert "invoice_no" in detail["recovered"]
    assert detail.get("invoice_no_vision_cleared") == "WRONG-FAKE-999"


def test_ground_clears_invented_invoice_no_and_vendor() -> None:
    from datetime import date
    from decimal import Decimal

    from app.services.invoice.vision_header_extract import VisionHeaderExtractResult
    from app.services.invoice.vision_header_reconcile import ground_vision_header_result

    result = VisionHeaderExtractResult(
        success=True,
        document_heading="TAX INVOICE",
        canonical_document_type="Tax Invoice",
        counterparty_name="Hallucinated Vendor Pty",
        perspective="purchase",
        invoice_no="INV-FAKE-999",
        po_reference="PO-REAL-100",
        invoice_date=date(2026, 3, 15),
        total=Decimal("100.00"),
        currency="AUD",
        confidence=0.92,
        reason="clear",
        provider="gemini_vision",
        page_count=2,
    )
    # No Invoice No / INV NO label — only PO — so fake invoice_no cannot be recovered.
    text = (
        "TAX INVOICE\n"
        "Acme Pty Ltd\n"
        "PO Number: PO-REAL-100\n"
        "Date: 15/03/2026\n"
        "Total AUD 100.00\n"
        "Extra padding so grounding text length clears the minimum threshold chars."
    )
    grounded, detail = ground_vision_header_result(result, text)
    assert "invoice_no" in detail["cleared"]
    assert "counterparty_name" in detail["cleared"]
    assert grounded.invoice_no == ""
    assert grounded.counterparty_name == ""
    assert grounded.po_reference == "PO-REAL-100"
    assert grounded.document_heading == "TAX INVOICE"
    assert grounded.total == Decimal("100.00")
    assert grounded.needs_review is True


def test_enrich_sets_invoice_no_and_permit_other_ref() -> None:
    from app.services.invoice.vision_header_extract import VisionHeaderExtractResult
    from app.services.invoice.vision_header_reconcile import enrich_vision_header_refs_from_text

    text = (
        "PERMIT NO : OD5I458006S\n"
        "CARGO CLEARANCE PERMIT\n"
        "UNITS (INV NO: 250970286) 5622.17\n"
        "UNIQUE REF : 197700341D 20250905 5701\n"
        + ("padding " * 20)
    )
    result = VisionHeaderExtractResult(
        success=True,
        document_heading="CARGO CLEARANCE PERMIT",
        invoice_no="",
        other_reference="197700341D 20250905 5701",
        confidence=0.8,
        provider="test",
    )
    enriched, detail = enrich_vision_header_refs_from_text(result, text)
    assert enriched.invoice_no == "250970286"
    assert enriched.other_reference == "OD5I458006S"
    assert "invoice_no" in detail["filled"]
    assert "other_reference" in detail["filled"]


def test_ground_recovers_invoice_date_from_labeled_text() -> None:
    from decimal import Decimal

    from app.services.invoice.vision_header_extract import VisionHeaderExtractResult
    from app.services.invoice.vision_header_reconcile import ground_vision_header_result

    text = (
        "COMMERCIAL INVOICE\n"
        "RYANS COMPUTERS LIMITED\n"
        "Invoice Date: 4/9/2025\n"
        "Total USD 34410.95\n"
        + ("padding " * 20)
    )
    result = VisionHeaderExtractResult(
        success=True,
        document_heading="COMMERCIAL INVOICE",
        counterparty_name="RYANS COMPUTERS LIMITED",
        invoice_no="250970286",
        invoice_date=date(2099, 1, 1),
        total=Decimal("34410.95"),
        currency="USD",
        confidence=0.9,
        provider="test",
    )
    grounded, detail = ground_vision_header_result(result, text)
    assert grounded.invoice_date == date(2025, 9, 4)
    assert "invoice_date" in detail["recovered"]


def test_ground_keeps_unpadded_claim_form_date() -> None:
    """TE forms print '3 June 2026'; vision ISO must not be cleared as ungrounded."""
    from decimal import Decimal

    from app.services.invoice.vision_header_extract import VisionHeaderExtractResult
    from app.services.invoice.vision_header_reconcile import ground_vision_header_result

    text = (
        "EMPLOYEE EXPENSE CLAIM FORM\n"
        "CLAIM NO. DATE\n"
        "EXP-2026-091 3 June 2026\n"
        "EMPLOYEE NAME Vishnu\n"
        "Subtotal AUD 2,000.00\n"
        "GST 10% AUD 200.00\n"
        "Total Claimed AUD 2,200.00\n"
        "This document is not a tax invoice.\n"
    )
    result = VisionHeaderExtractResult(
        success=True,
        document_heading="EMPLOYEE EXPENSE CLAIM FORM",
        invoice_date=date(2026, 6, 3),
        invoice_date_raw="2026-06-03",
        total=Decimal("2200.00"),
        subtotal=Decimal("2000.00"),
        gst=Decimal("200.00"),
        currency="AUD",
        confidence=0.9,
        provider="test",
    )
    grounded, detail = ground_vision_header_result(result, text)
    assert grounded.invoice_date == date(2026, 6, 3)
    assert "invoice_date" in detail["kept"]
    assert "invoice_date" not in detail["cleared"]


def test_enrich_fills_missing_invoice_date_from_text() -> None:
    from app.services.invoice.vision_header_extract import VisionHeaderExtractResult
    from app.services.invoice.vision_header_reconcile import enrich_vision_header_refs_from_text

    text = (
        "COMMERCIAL INVOICE\n"
        "Date of issue: 15/03/2026\n"
        + ("padding " * 20)
    )
    result = VisionHeaderExtractResult(
        success=True,
        document_heading="COMMERCIAL INVOICE",
        confidence=0.8,
        provider="test",
    )
    enriched, detail = enrich_vision_header_refs_from_text(result, text)
    assert enriched.invoice_date == date(2026, 3, 15)
    assert "invoice_date" in detail["filled"]


def test_enrich_permit_only_leaves_invoice_no_empty() -> None:
    from app.services.invoice.vision_header_extract import VisionHeaderExtractResult
    from app.services.invoice.vision_header_reconcile import (
        enrich_vision_header_refs_from_text,
        ground_vision_header_result,
    )

    text = (
        "PERMIT NO : OD5I458006S\n"
        "CARGO CLEARANCE PERMIT\n"
        "UNIQUE REF : 197700341D 20250905 5701\n"
        + ("padding " * 20)
    )
    result = VisionHeaderExtractResult(
        success=True,
        document_heading="CARGO CLEARANCE PERMIT",
        invoice_no="",
        other_reference="",
        confidence=0.8,
        provider="test",
    )
    enriched, detail = enrich_vision_header_refs_from_text(result, text)
    assert enriched.invoice_no == ""
    assert enriched.other_reference == "OD5I458006S"
    assert "invoice_no" not in detail["filled"]
    assert "other_reference" in detail["filled"]

    # Vision wrongly put Permit No into invoice_no — grounding must clear it.
    result2 = VisionHeaderExtractResult(
        success=True,
        document_heading="CARGO CLEARANCE PERMIT",
        invoice_no="OD5I458006S",
        other_reference="",
        confidence=0.9,
        provider="test",
    )
    grounded, gdetail = ground_vision_header_result(result2, text)
    assert grounded.invoice_no == ""
    assert "invoice_no" in gdetail["cleared"]
    assert gdetail.get("invoice_no_cleared_reason") == "non_invoice_labeled_id"


def test_ground_skips_thin_text() -> None:
    from app.services.invoice.vision_header_extract import VisionHeaderExtractResult
    from app.services.invoice.vision_header_reconcile import ground_vision_header_result

    result = VisionHeaderExtractResult(
        success=True,
        document_heading="TAX INVOICE",
        counterparty_name="Only On Image Vendor",
        invoice_no="INV-SCAN-1",
        confidence=0.9,
        reason="scan",
        provider="gemini_vision",
    )
    grounded, detail = ground_vision_header_result(result, "short")
    assert detail["skipped"] is True
    assert grounded.counterparty_name == "Only On Image Vendor"
    assert grounded.invoice_no == "INV-SCAN-1"


def test_ground_prefers_commercial_inv_over_soft_grounded_permit() -> None:
    from app.services.invoice.vision_header_extract import VisionHeaderExtractResult
    from app.services.invoice.vision_header_reconcile import ground_vision_header_result

    text = (
        "PERMIT NO : OD5I458006S\n"
        "CARGO CLEARANCE PERMIT\n"
        "SKYLIFT CONSOLIDATOR (PTE) LTD\n"
        "UNITS (INV NO: 250970286) 5622.17\n"
        "UNIQUE REF : 197700341D 20250905 5701\n"
        + ("padding " * 20)
    )
    result = VisionHeaderExtractResult(
        success=True,
        document_heading="CARGO CLEARANCE PERMIT",
        counterparty_name="SKYLIFT CONSOLIDATOR (PTE) LTD",
        invoice_no="OD5I458006S",
        other_reference="197700341D 20250905 5701",
        confidence=0.9,
        reason="x",
        provider="test",
    )
    grounded, detail = ground_vision_header_result(result, text)
    assert grounded.invoice_no == "250970286"
    assert detail.get("invoice_no_prefer_commercial") == "250970286"
    assert detail.get("invoice_no_vision_cleared") == "OD5I458006S"


def test_ground_rejects_customer_header_and_recovers_invoice_no() -> None:
    """Packing-list column bleed: vision 'Customer' → recover labeled Invoice No."""
    from app.services.invoice.vision_header_extract import VisionHeaderExtractResult
    from app.services.invoice.vision_header_reconcile import ground_vision_header_result

    text = (
        "PACKING LIST\n"
        "Lexar Co., Limited\n"
        "Date PackingList No. Invoice No. Customer PO Incoterm\n"
        "2025-07-25 0000078729 82507681 PO-250742524 EXW Hong Kong\n"
        + ("padding " * 20)
    )
    result = VisionHeaderExtractResult(
        success=True,
        document_heading="PACKING LIST",
        canonical_document_type="Packing List",
        counterparty_name="Lexar Co., Limited",
        invoice_no="Customer",
        confidence=0.88,
        reason="header bleed",
        provider="test",
    )
    grounded, detail = ground_vision_header_result(result, text)
    assert grounded.invoice_no == "82507681"
    assert detail.get("invoice_no_vision_rejected") == "Customer"
    assert "invoice_no" in detail["recovered"]


def test_ground_keeps_digit_invoice_no_when_customer_appears_in_ocr() -> None:
    """Do not overwrite a correct vision invoice_no with adjacent 'Customer' header."""
    from app.services.invoice.vision_header_extract import VisionHeaderExtractResult
    from app.services.invoice.vision_header_reconcile import ground_vision_header_result

    text = (
        "PACKING LIST\n"
        "Invoice No. Customer PO\n"
        "82507681 PO-250742524\n"
        + ("padding " * 20)
    )
    result = VisionHeaderExtractResult(
        success=True,
        document_heading="PACKING LIST",
        counterparty_name="Lexar Co., Limited",
        invoice_no="82507681",
        confidence=0.9,
        reason="ok",
        provider="test",
    )
    grounded, detail = ground_vision_header_result(result, text)
    assert grounded.invoice_no == "82507681"
    assert "invoice_no" in detail["kept"] or detail.get("invoice_no_prefer_commercial") in (
        None,
        "82507681",
    )


def test_ground_fixes_near_miss_invoice_no() -> None:
    from app.services.invoice.vision_header_extract import VisionHeaderExtractResult
    from app.services.invoice.vision_header_reconcile import ground_vision_header_result

    text = (
        "MongoDB Limited\n"
        "Invoice Number: 686b6174909b5272abdce254\n"
        "Total US$37.08\n"
        + ("padding " * 20)
    )
    result = VisionHeaderExtractResult(
        success=True,
        document_heading="Invoice",
        counterparty_name="MongoDB Limited",
        # Vision dropped a digit vs the labeled token.
        invoice_no="686b617490b5272abdce254",
        total=None,
        currency="USD",
        confidence=0.9,
        reason="x",
        provider="test",
    )
    grounded, detail = ground_vision_header_result(result, text)
    assert grounded.invoice_no == "686b6174909b5272abdce254"
    assert "invoice_no" in detail["recovered"]


def test_vision_header_should_review_low_confidence() -> None:
    result = VisionHeaderExtractResult(
        success=True,
        document_heading="TAX INVOICE",
        confidence=0.4,
        provider="gemini_vision",
    )
    assert vision_header_should_review(result) is True


def test_apply_reconcile_clears_ungrounded_total() -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.EXCEPTION,
        currency="USD",
        total=Decimal("99999.00"),
        extracted_fields={"currency": "USD", "total": "99999.00"},
    )
    text = (
        "MongoDB Limited\n"
        "Subtotal US$33.70\n"
        "Value-Added Tax US$3.38\n"
        "Total US$37.08\n"
        "Enough body text here so grounding length threshold is satisfied fully."
    )
    detail = apply_vision_header_text_reconcile(inv, text)
    # 99999 not in text and not upgraded from a matching subtotal → cleared
    assert inv.total is None or inv.total == Decimal("37.08")
    assert detail["total_reason"] in {
        "cleared_ungrounded_total",
        "upgraded_labeled_grand_total",
        "upgraded_subtotal_plus_tax",
        "unchanged",
    }


def test_amount_consistency_clears_gst_never_invents_balance() -> None:
    from app.services.invoice.vision_header_reconcile import (
        apply_vision_header_amount_consistency,
    )

    result = VisionHeaderExtractResult(
        success=True,
        document_heading="TAX INVOICE",
        subtotal=Decimal("100.00"),
        gst=Decimal("50.00"),
        total=Decimal("110.00"),
        confidence=0.9,
        provider="claude_vision",
    )
    updated, detail = apply_vision_header_amount_consistency(result)
    assert "subtotal_gst_total_mismatch" in detail["flags"]
    assert "gst" in detail["cleared"]
    assert updated.gst is None
    assert updated.subtotal == Decimal("100.00")
    assert updated.total == Decimal("110.00")
    assert updated.amount_inconsistency is True
    assert updated.needs_review is True
    # Never invent balancing gst = total - subtotal
    assert updated.gst is None


def test_amount_consistency_clears_tax_inclusive_subtotal() -> None:
    """When subtotal ≈ total with positive gst, clear subtotal (not gst)."""
    from app.services.invoice.vision_header_reconcile import (
        apply_vision_header_amount_consistency,
    )

    result = VisionHeaderExtractResult(
        success=True,
        document_heading="TAX INVOICE",
        subtotal=Decimal("9800.54"),
        gst=Decimal("55.92"),
        total=Decimal("9800.53"),
        confidence=0.9,
        provider="claude_vision",
    )
    updated, detail = apply_vision_header_amount_consistency(result)
    assert "tax_inclusive_subtotal" in detail["flags"]
    assert "subtotal" in detail["cleared"]
    assert updated.subtotal is None
    assert updated.gst == Decimal("55.92")
    assert updated.total == Decimal("9800.53")


def test_amount_consistency_ok_when_balanced() -> None:
    from app.services.invoice.vision_header_reconcile import (
        apply_vision_header_amount_consistency,
    )

    result = VisionHeaderExtractResult(
        success=True,
        subtotal=Decimal("100.00"),
        gst=Decimal("10.00"),
        total=Decimal("110.00"),
        confidence=0.9,
        provider="claude_vision",
    )
    updated, detail = apply_vision_header_amount_consistency(result)
    assert detail["flags"] == []
    assert detail["cleared"] == []
    assert updated.gst == Decimal("10.00")
    assert updated.amount_inconsistency is False


def test_amount_consistency_line_sum_mismatch_flags_review() -> None:
    from app.services.invoice.invoice_data import ParsedLineItem
    from app.services.invoice.vision_header_reconcile import (
        apply_vision_header_amount_consistency,
    )

    result = VisionHeaderExtractResult(
        success=True,
        subtotal=Decimal("100.00"),
        total=Decimal("110.00"),
        line_items=(
            ParsedLineItem(description="A", amount=Decimal("10.00"), source="vision_header"),
            ParsedLineItem(description="B", amount=Decimal("10.00"), source="vision_header"),
        ),
        confidence=0.9,
        provider="claude_vision",
    )
    updated, detail = apply_vision_header_amount_consistency(result)
    assert "line_items_amount_mismatch" in detail["flags"]
    assert updated.line_items_amount_mismatch is True
    assert updated.needs_review is True
    # Lines are not auto-rewritten
    assert len(updated.line_items) == 2


def test_amount_consistency_line_sum_selects_total_clears_foreign_subtotal() -> None:
    """Dual-currency: SGD taxable value as subtotal, USD total matches line sum."""
    from app.services.invoice.invoice_data import ParsedLineItem
    from app.services.invoice.vision_header_reconcile import (
        apply_vision_header_amount_consistency,
    )

    result = VisionHeaderExtractResult(
        success=True,
        document_heading="COMMERCIAL INVOICE",
        subtotal=Decimal("7712.47"),
        gst=Decimal("0.00"),
        total=Decimal("6031.00"),
        currency="USD",
        line_items=(
            ParsedLineItem(description="Item A", amount=Decimal("3000.00"), source="vision_header"),
            ParsedLineItem(description="Item B", amount=Decimal("3031.00"), source="vision_header"),
        ),
        confidence=0.9,
        provider="claude_vision",
    )
    updated, detail = apply_vision_header_amount_consistency(result)
    assert "line_sum_selected_total" in detail["flags"]
    assert "subtotal" in detail["cleared"]
    assert updated.subtotal is None
    assert updated.total == Decimal("6031.00")
    assert updated.gst == Decimal("0.00")
    assert updated.amount_inconsistency is False
    assert updated.line_items_amount_mismatch is False
    assert updated.needs_review is False
    assert detail["line_sum"] == "6031.00"


def test_amount_consistency_line_sum_matches_neither_keeps_review() -> None:
    from app.services.invoice.invoice_data import ParsedLineItem
    from app.services.invoice.vision_header_reconcile import (
        apply_vision_header_amount_consistency,
    )

    result = VisionHeaderExtractResult(
        success=True,
        subtotal=Decimal("7712.47"),
        gst=Decimal("0.00"),
        total=Decimal("6031.00"),
        line_items=(
            ParsedLineItem(description="A", amount=Decimal("100.00"), source="vision_header"),
            ParsedLineItem(description="B", amount=Decimal("200.00"), source="vision_header"),
        ),
        confidence=0.9,
        provider="claude_vision",
    )
    updated, detail = apply_vision_header_amount_consistency(result)
    assert "line_sum_selected_total" not in detail["flags"]
    assert updated.needs_review is True
    assert updated.subtotal == Decimal("7712.47")
    assert updated.total == Decimal("6031.00")


def test_vision_header_should_review_on_amount_inconsistency() -> None:
    result = VisionHeaderExtractResult(
        success=True,
        document_heading="TAX INVOICE",
        confidence=0.95,
        amount_inconsistency=True,
        provider="claude_vision",
    )
    assert vision_header_should_review(result) is True


def test_ground_clears_ungrounded_subtotal_and_tax_id() -> None:
    result = VisionHeaderExtractResult(
        success=True,
        document_heading="TAX INVOICE",
        subtotal=Decimal("88888.00"),
        gst=Decimal("8.00"),
        total=Decimal("110.00"),
        seller_abn="51824753556",
        confidence=0.9,
        provider="claude_vision",
    )
    text = (
        "TAX INVOICE Acme Pty Ltd\n"
        "GST 8.00\n"
        "Total 110.00\n"
        "Enough body text so grounding length threshold is satisfied for money checks."
    )
    updated, detail = ground_vision_header_result(result, text)
    assert "subtotal" in detail["cleared"]
    assert updated.subtotal is None
    assert updated.gst == Decimal("8.00")
    assert "seller_abn" in detail["cleared"]
    assert updated.seller_abn == ""


def test_ground_keeps_gst_sum_of_cgst_sgst_components() -> None:
    """Invoice 656 pattern: gst total is not a page token; CGST+SGST are."""
    result = VisionHeaderExtractResult(
        success=True,
        document_heading="TAX INVOICE",
        counterparty_name="MAKEMYTRIP (INDIA) PRIVATE LIMITED",
        invoice_no="M06AI26115837637",
        gst=Decimal("55.92"),
        total=Decimal("9800.53"),
        other_reference="NF7AI3JB48483693376",  # OCR near-miss vs NF7A13JB...
        confidence=0.88,
        provider="claude_vision",
    )
    text = (
        "TAX INVOICE\n"
        "MAKEMYTRIP (INDIA) PRIVATE LIMITED\n"
        "CGST @9%\n"
        "₹27.96\n"
        "SGST @9%\n"
        "₹27.96\n"
        "Grand Total\n"
        "₹9800.53\n"
        "Booking ID\n"
        "NF7A13JB48483693376\n"
        "Invoice No\n"
        "M06AI26115837637\n"
        "Enough body text so grounding length threshold is satisfied for money checks."
    )
    updated, detail = ground_vision_header_result(result, text)
    assert updated.gst == Decimal("55.92")
    assert "gst" not in detail["cleared"]
    assert "other_reference" in detail["cleared"]
    # Only a secondary ref cleared → do not force needs_review via cleared-count.
    assert updated.needs_review is False
