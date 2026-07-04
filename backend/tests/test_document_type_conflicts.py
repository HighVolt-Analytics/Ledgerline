"""Tests for document-type signal conflicts (legacy heading checks)."""

import pytest

from app.services.classification.document_type_conflicts import (
    conflict_confidence_penalty,
    detect_signal_conflicts,
)
def test_detect_contract_heading_with_invoice_fields() -> None:
    from app.services.classification.document_type_rule_engine import DocumentClassifierContext

    ctx = DocumentClassifierContext(
        attachment_name="",
        email_sender="",
        email_subject="",
        vendor="",
        invoice_no="INV-100",
        po_reference="",
        line_text="",
        document_text="",
        abn="",
        capture_channel="upload",
        invoice_date="",
        due_date="",
        total="100",
        subtotal="",
        gst="",
        billing_address="",
        cost_centre="",
        account_code="",
        account_name="",
        bank_details="",
        currency="AUD",
        attachment_extension="",
        has_po_reference="false",
        has_invoice_no="true",
        has_total="true",
        has_abn="false",
        has_vendor="false",
        has_invoice_date="false",
        has_due_date="false",
        has_subtotal="false",
        has_gst="false",
        has_billing_address="false",
        has_bank_details="false",
        has_line_items="false",
        has_cost_centre="false",
        is_commercial_invoice="false",
        document_heading="Contract",
        has_heading_invoice="false",
        has_heading_po="false",
        has_heading_grn="false",
        has_heading_credit_note="false",
        has_heading_quote="false",
        has_heading_contract="true",
        extracted_fields={},
    )
    conflicts = detect_signal_conflicts(ctx)
    assert "Contract heading with invoice-like fields present" in conflicts


def test_conflict_penalty_caps_at_max() -> None:
    assert conflict_confidence_penalty(["a", "b", "c", "d", "e"]) == pytest.approx(0.35)
