"""Tests for extended validation rules VR09–VR16."""

from datetime import date, timedelta
from decimal import Decimal

from app.schemas.rule_book_config import VendorMaster
from app.services.extended_validations import (
    vr09_line_arithmetic,
    vr10_tax_invoice_au,
    vr11_date_sanity,
    vr12_vendor_master,
    vr16_freight_surcharges,
)
from app.services.invoice_data import InvoiceData, ParsedLineItem


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


def test_vr10_requires_tax_invoice_for_large_taxable_supply() -> None:
    data = InvoiceData(subtotal=Decimal("1500.00"), document_text="Invoice only")
    result = vr10_tax_invoice_au(data)
    assert result.passed is False


def test_vr10_passes_when_tax_invoice_stated() -> None:
    data = InvoiceData(
        subtotal=Decimal("1500.00"),
        gst=Decimal("150.00"),
        document_text="Tax Invoice for services rendered",
    )
    result = vr10_tax_invoice_au(data)
    assert result.passed is True


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


def test_vr16_freight_above_tolerance() -> None:
    data = InvoiceData(
        po_reference="PO-100",
        line_items=[ParsedLineItem(description="Freight charge", amount=Decimal("150"))],
    )
    result = vr16_freight_surcharges(data)
    assert result.passed is False
