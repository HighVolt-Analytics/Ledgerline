"""Tests for extended validation rules VR09–VR16."""

from datetime import date, timedelta
from decimal import Decimal

from app.schemas.rule_book_config import VendorMaster
from app.services.rule_book.extended_validations import (
    vr09_line_arithmetic,
    vr10_tax_invoice_wording,
    vr11_date_sanity,
    vr12_vendor_master,
    vr16_freight_surcharges,
)
from app.services.invoice.invoice_data import InvoiceData, ParsedLineItem


def _vendor_master(**kwargs) -> VendorMaster:
    base = dict(
        id="v-1",
        name="Acme Supplies Pty Ltd",
        aliases=[],
        abn="51824753556",
        status="active",
    )
    base.update(kwargs)
    return VendorMaster.model_validate(base)


def test_vr09_line_arithmetic_passes_within_tolerance() -> None:
    data = InvoiceData(
        subtotal=Decimal("100.00"),
        line_items=[
            ParsedLineItem(description="Widget", qty=Decimal("2"), unit_price=Decimal("50"), amount=Decimal("100")),
        ],
    )
    result = vr09_line_arithmetic(data)
    assert result.passed is True


def test_vr09_line_arithmetic_fails_when_lines_do_not_sum() -> None:
    data = InvoiceData(
        subtotal=Decimal("100.00"),
        line_items=[ParsedLineItem(description="Widget", amount=Decimal("90"))],
    )
    result = vr09_line_arithmetic(data)
    assert result.passed is False


def test_vr10_au_requires_tax_invoice_for_large_taxable_supply() -> None:
    data = InvoiceData(subtotal=Decimal("1500.00"), document_text="Invoice only")
    result = vr10_tax_invoice_wording(data, country="AU", currency="AUD")
    assert result.passed is False
    assert "AUD 1000" in result.message


def test_vr10_au_passes_when_tax_invoice_stated() -> None:
    data = InvoiceData(
        subtotal=Decimal("1500.00"),
        gst=Decimal("150.00"),
        document_text="Tax Invoice for services rendered",
    )
    result = vr10_tax_invoice_wording(data, country="AU", currency="AUD")
    assert result.passed is True


def test_vr10_sg_fails_when_gst_without_wording() -> None:
    data = InvoiceData(
        subtotal=Decimal("200.00"),
        gst=Decimal("18.00"),
        document_text="Invoice only",
    )
    result = vr10_tax_invoice_wording(data, country="SG", currency="SGD")
    assert result.passed is False


def test_vr10_us_skips_rule() -> None:
    data = InvoiceData(
        subtotal=Decimal("5000.00"),
        gst=Decimal("500.00"),
        document_text="Invoice only",
    )
    result = vr10_tax_invoice_wording(data, country="US", currency="USD")
    assert result.passed is True
    assert result.skipped is True


def test_vr10_gb_passes_with_vat_invoice_phrase() -> None:
    data = InvoiceData(
        subtotal=Decimal("500.00"),
        gst=Decimal("100.00"),
        document_text="VAT Invoice for consulting",
    )
    result = vr10_tax_invoice_wording(data, country="GB", currency="GBP")
    assert result.passed is True


def test_vr10_nz_uses_local_threshold() -> None:
    data = InvoiceData(subtotal=Decimal("1500.00"), document_text="Invoice only")
    result = vr10_tax_invoice_wording(data, country="NZ", currency="NZD")
    assert result.passed is False
    assert "NZD 1000" in result.message


def test_vr11_rejects_future_invoice_date() -> None:
    data = InvoiceData(invoice_date=date.today() + timedelta(days=1), due_date=date.today() + timedelta(days=14))
    result = vr11_date_sanity(data)
    assert result.passed is False


def test_vr11_warns_on_old_invoice() -> None:
    old = date.today() - timedelta(days=400)
    data = InvoiceData(invoice_date=old, due_date=old)
    result = vr11_date_sanity(data)
    assert result.passed is False
    assert "12 months" in result.message


def test_vr12_vendor_master_tax_id_mismatch() -> None:
    data = InvoiceData(vendor="Acme Supplies Pty Ltd", abn="12345678901")
    result = vr12_vendor_master(data, vendor_masters=[_vendor_master()])
    assert result.passed is False
    assert "fraud" in result.message.lower()


def test_vr12_vendor_master_ok() -> None:
    data = InvoiceData(vendor="Acme Supplies Pty Ltd", abn="51824753556")
    result = vr12_vendor_master(data, vendor_masters=[_vendor_master()])
    assert result.passed is True


def test_vr12_fails_when_no_masters_configured() -> None:
    data = InvoiceData(vendor="Unknown Supplier Pty Ltd")
    result = vr12_vendor_master(data, vendor_masters=[])
    assert result.passed is False
    assert result.skipped is False
    assert "not registered" in result.message.lower()


def test_vr12_requires_vendor_name_when_no_masters() -> None:
    data = InvoiceData(vendor="")
    result = vr12_vendor_master(data, vendor_masters=[])
    assert result.passed is False
    assert "vendor name required" in result.message.lower()


def test_normalize_legacy_vr12_skip_when_no_masters() -> None:
    from app.services.rule_book.validator import normalize_stored_validation_row

    row = normalize_stored_validation_row(
        {
            "rule": "VR12",
            "passed": True,
            "skipped": True,
            "message": "Vendor master check skipped — no masters configured",
        }
    )
    assert row["skipped"] is False
    assert row["passed"] is False
    assert "not registered" in row["message"].lower()


def test_vr16_freight_above_tolerance() -> None:
    data = InvoiceData(
        po_reference="PO-100",
        line_items=[ParsedLineItem(description="Freight charge", amount=Decimal("150"))],
    )
    result = vr16_freight_surcharges(data)
    assert result.passed is False
