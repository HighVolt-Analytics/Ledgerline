"""Extended classifier context fields for match rules."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.models.invoice import Invoice, InvoiceStatus
from app.services.document_type_rule_engine import _document_field, build_document_classifier_context
from app.services.invoice_data import InvoiceData
from app.tenant_ids import TESTING_TENANT_UUID


def test_classifier_context_amounts_and_dates() -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.PENDING,
        invoice_date=date(2026, 1, 15),
        due_date=date(2026, 2, 15),
        total=Decimal("120.50"),
        gst=Decimal("10.50"),
        currency="AUD",
        email_attachment_name="scan.PDF",
    )
    parsed = InvoiceData(vendor="Acme Pty Ltd", abn="12 345 678 901")
    ctx = build_document_classifier_context(invoice=inv, parsed=parsed)

    assert _document_field(ctx, "invoice_date") == "2026-01-15"
    assert _document_field(ctx, "total") == "120.50"
    assert _document_field(ctx, "attachment_extension") == "pdf"
    assert _document_field(ctx, "has_vendor") == "true"
    assert _document_field(ctx, "has_abn") == "true"
    assert _document_field(ctx, "has_due_date") == "true"


def test_classifier_context_custom_extracted_field() -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.PENDING,
        extracted_fields={"grn_number": "GRN-9001", "contract_party": "Buyer Co"},
    )
    parsed = InvoiceData(document_text="Goods received")
    ctx = build_document_classifier_context(invoice=inv, parsed=parsed)

    assert _document_field(ctx, "grn_number") == "GRN-9001"
    assert _document_field(ctx, "has_grn_number") == "true"
    assert _document_field(ctx, "has_contract_party") == "true"
    assert _document_field(ctx, "has_missing_field") == "false"
