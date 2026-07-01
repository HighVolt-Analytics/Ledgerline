
from app.tenant_ids import PLATFORM_TENANT_UUID, TESTING_TENANT_UUID
"""Tests for per-field extraction confidence scoring."""

from datetime import date
from decimal import Decimal

from app.models.invoice import Invoice
from app.models.line_item import LineItem
from app.services.field_extraction_confidence import compute_extraction_field_confidence


def _invoice(**kwargs) -> Invoice:
    inv = Invoice(tenant_id=TESTING_TENANT_UUID, currency="AUD")
    for key, value in kwargs.items():
        setattr(inv, key, value)
    return inv


def test_grn_like_document_varied_scores() -> None:
    inv = _invoice(
        vendor="Acme Corp Pvt Ltd",
        po_reference="PO-2025-0101",
        invoice_no=None,
        total=None,
        email_attachment_name="SET1_GRN-2025-0101_Industrial.pdf",
        validation_results='[{"rule":"VR03","passed":false,"message":"Missing: invoice_no, total","skipped":false}]',
    )
    inv.line_items = [
        LineItem(
            invoice_id=1,
            description="Widget A",
            qty=Decimal("5"),
            unit_price=Decimal("10"),
            amount=Decimal("50"),
        )
    ]
    scores = compute_extraction_field_confidence(inv)

    assert scores["vendor"] >= 90
    assert scores["po_reference"] >= 90
    assert scores["line_items"] >= 90
    assert scores["attachment_name"] >= 95
    assert scores["invoice_no"] <= 25
    assert scores["total"] <= 25
    assert scores["vendor"] != scores["po_reference"]


def test_vendor_not_penalized_by_vendor_match_confidence() -> None:
    inv = _invoice(
        vendor="Atlassian Pty Ltd",
        vendor_confidence=0.3,
        invoice_no="INV-1001",
        invoice_date=date(2025, 1, 15),
        due_date=date(2025, 2, 15),
        subtotal=Decimal("100"),
        gst=Decimal("10"),
        total=Decimal("110"),
    )
    scores = compute_extraction_field_confidence(inv)
    assert scores["vendor"] >= 90


def test_amount_mismatch_lowers_total() -> None:
    inv = _invoice(
        vendor="Acme Pty Ltd",
        subtotal=Decimal("100"),
        gst=Decimal("10"),
        total=Decimal("200"),
        validation_results='[{"rule":"VR08","passed":false,"message":"GST mismatch","skipped":false}]',
    )
    scores = compute_extraction_field_confidence(inv)
    assert scores["total"] < 60
