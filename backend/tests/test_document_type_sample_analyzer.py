"""Tests for document-type sample analysis."""

from datetime import date
from decimal import Decimal

from app.models.invoice import Invoice, InvoiceStatus
from app.services.document_type_recognition_signals import (
    detect_recognition_signals,
    infer_classifier_layout,
    infer_playbook_profile,
)
from app.services.document_type_sample_analyzer import analyze_document_type_samples
from app.services.invoice_data import InvoiceData, ParsedLineItem


def _invoice(**kwargs) -> Invoice:
    base = dict(
        id=1,
        tenant_id=1,
        status=InvoiceStatus.PARSING,
        currency="AUD",
    )
    base.update(kwargs)
    return Invoice(**base)


def _parsed(**kwargs) -> InvoiceData:
    base = dict(
        vendor="Acme Supplies Pty Ltd",
        invoice_no="INV-1001",
        invoice_date=date(2026, 3, 1),
        total=Decimal("110.00"),
        po_reference="PO-44871",
        line_items=[ParsedLineItem(description="Paper", qty=Decimal("1"), amount=Decimal("100"))],
        document_text="TAX INVOICE\nPO Reference PO-44871\nTotal 110.00",
        document_heading="TAX INVOICE",
    )
    base.update(kwargs)
    return InvoiceData(**base)


def test_detect_po_goods_invoice_signals() -> None:
    profile = detect_recognition_signals(
        filename="INV-1001.pdf",
        invoice=_invoice(email_attachment_name="INV-1001.pdf"),
        parsed=_parsed(),
    )
    assert "heading_invoice" in profile.signals
    assert "has_po_reference" in profile.signals
    assert "has_invoice_number" in profile.signals
    assert "has_total_amount" in profile.signals
    assert "vendor" in profile.extraction_fields
    assert infer_playbook_profile(profile.signals) == "po_goods"
    assert infer_classifier_layout(profile.signals) == "all_signals"


def test_detect_grn_supporting_signals() -> None:
    profile = detect_recognition_signals(
        filename="GRN-PO-99.pdf",
        invoice=_invoice(email_attachment_name="GRN-PO-99.pdf"),
        parsed=_parsed(
            invoice_no=None,
            due_date=None,
            document_text="GOODS RECEIPT NOTE\nPO PO-99",
            document_heading="GOODS RECEIPT NOTE",
        ),
    )
    assert "heading_grn" in profile.signals or "filename_grn" in profile.signals
    assert infer_playbook_profile(profile.signals) == "supporting"


def test_merge_multiple_samples_majority(monkeypatch) -> None:
    parsed = _parsed()
    invoice = _invoice(email_attachment_name="invoice-a.pdf")

    def fake_parse(filename: str, content: bytes):
        _ = content
        profile = detect_recognition_signals(
            filename=filename,
            invoice=invoice,
            parsed=parsed,
        )
        return invoice, parsed, "high"

    monkeypatch.setattr(
        "app.services.document_type_sample_analyzer._parse_sample",
        fake_parse,
    )
    proposal = analyze_document_type_samples(
        [
            ("invoice-a.pdf", b"pdf-bytes"),
            ("invoice-b.pdf", b"pdf-bytes"),
        ]
    )
    assert proposal.recognition_signals
    assert "vendor" in proposal.extraction_fields
    assert proposal.playbook_profile
    assert proposal.match_mode
    assert proposal.approval_mode
    assert proposal.route_target
    assert len(proposal.samples) == 2
    assert proposal.one_line
    assert proposal.validation_rules


def test_analyze_rejects_empty_file_list() -> None:
    try:
        analyze_document_type_samples([])
    except ValueError as exc:
        assert "At least one" in str(exc)
    else:
        raise AssertionError("expected ValueError")
