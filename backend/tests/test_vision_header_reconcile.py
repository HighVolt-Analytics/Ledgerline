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


def test_bare_dollar_clears_uncorroborated_aud() -> None:
    iso, symbol, reason = reconcile_currency_from_text(
        current_currency="AUD",
        text=(
            "Rosty.ai x LML Content Invoice\n"
            "Total $1,399.00\n"
            "50% Advance $699.50\n"
            "Enough body text so grounding length threshold is satisfied for currency checks."
        ),
    )
    assert iso == ""
    assert symbol == "$"
    assert "cleared" in reason


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


def test_bare_dollar_empty_stays_empty_with_symbol() -> None:
    iso, symbol, reason = reconcile_currency_from_text(
        current_currency="",
        text="Invoice\nTotal $100.00",
    )
    assert iso == ""
    assert symbol == "$"
    assert "ambiguous" in reason


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
