"""Tests for document-type sample analysis."""

from datetime import date
from decimal import Decimal

from app.models.invoice import Invoice, InvoiceStatus
from app.services.document_type_recognition_signals import (
    detect_recognition_signals,
    infer_classifier_layout,
    infer_playbook_profile,
    merge_signals_for_classifier_profiles,
)
from app.services.document_type_sample_analyzer import (
    analyze_document_type_samples,
    parse_document_samples,
)
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


def test_tax_notice_not_triggered_by_ato_substring() -> None:
    profile = detect_recognition_signals(
        filename="EP -Spex1.pdf",
        invoice=_invoice(email_attachment_name="EP -Spex1.pdf"),
        parsed=_parsed(
            invoice_no="EP-001",
            po_reference=None,
            document_text="Automated billing summary\nVendor: Acme\nInvoice No EP-001",
            document_heading="TAX INVOICE",
        ),
    )
    assert "text_tax_notice" not in profile.signals
    assert "heading_invoice" in profile.signals
    assert infer_playbook_profile(profile.signals) == "direct_expense"


def test_billing_summary_triggers_text_invoice() -> None:
    profile = detect_recognition_signals(
        filename="EP -Spex1.pdf",
        invoice=_invoice(email_attachment_name="EP -Spex1.pdf"),
        parsed=_parsed(
            invoice_no="EP-001",
            po_reference=None,
            document_text="Automated billing summary\nInvoice No EP-001\nVendor: Acme",
            document_heading="Billing Summary",
        ),
    )
    assert "text_invoice" in profile.signals
    assert "has_invoice_number" in profile.signals


def test_suggest_missing_signals_for_weak_profile() -> None:
    from app.services.recognition_signal_catalog import suggest_missing_identity_signals

    suggested = suggest_missing_identity_signals(
        frozenset({"has_invoice_number"}),
        playbook="direct_expense",
        document_heading="Billing Summary",
    )
    assert suggested
    assert any(row["signal_id"] == "heading_invoice" for row in suggested)
    profile = detect_recognition_signals(
        filename="EP -Spex1.pdf",
        invoice=_invoice(email_attachment_name="EP -Spex1.pdf"),
        parsed=_parsed(
            invoice_no="EP-001",
            po_reference=None,
            document_text="Automated billing summary\nVendor: Acme\nInvoice No EP-001",
            document_heading="TAX INVOICE",
        ),
    )
    assert "text_tax_notice" not in profile.signals
    assert "heading_invoice" in profile.signals
    assert infer_playbook_profile(profile.signals) == "direct_expense"


def test_refine_credit_note_single_file() -> None:
    profile = detect_recognition_signals(
        filename="credit-2026.pdf",
        invoice=_invoice(email_attachment_name="credit-2026.pdf"),
        parsed=_parsed(
            invoice_no="CN-100",
            po_reference=None,
            document_text="CREDIT NOTE\nVendor: Acme\nCredit Note CN-100\nTotal -50.00",
            document_heading="CREDIT NOTE",
        ),
    )
    assert "text_credit_note" in profile.signals
    assert "text_invoice" not in profile.signals
    assert "text_po" not in profile.signals
    assert infer_playbook_profile(profile.signals) == "credit_adjustment"


def test_refine_quote_single_file() -> None:
    profile = detect_recognition_signals(
        filename="quote-99.pdf",
        invoice=_invoice(email_attachment_name="quote-99.pdf"),
        parsed=_parsed(
            invoice_no=None,
            po_reference=None,
            total=None,
            subtotal=None,
            gst=None,
            document_text="QUOTATION\nEstimate for services\nValid 30 days",
            document_heading="QUOTATION",
        ),
    )
    assert "text_quote" in profile.signals
    assert "has_invoice_number" not in profile.signals
    assert infer_playbook_profile(profile.signals) == "non_actionable"


def test_refine_claim_single_file() -> None:
    profile = detect_recognition_signals(
        filename="expense-claim.pdf",
        invoice=_invoice(email_attachment_name="expense-claim.pdf"),
        parsed=_parsed(
            po_reference=None,
            document_text="EXPENSE CLAIM\nEmployee: Jane\nReimbursement total 45.00",
            document_heading="EXPENSE CLAIM",
        ),
    )
    assert "text_claim" in profile.signals
    assert infer_playbook_profile(profile.signals) == "employee_claim"


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
        return invoice, parsed, "high", None, None

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
    assert proposal.classifier_layout in {"grouped", "all_signals"}
    assert "vendor" in proposal.required_fields
    assert "invoice_no" in proposal.required_fields
    assert proposal.apply_ready is True
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


def test_parse_document_samples_parallel(monkeypatch) -> None:
    import time

    parsed = _parsed()
    invoice = _invoice(email_attachment_name="sample.pdf")

    def slow_parse(filename: str, content: bytes):
        _ = content
        time.sleep(0.05)
        return invoice, parsed, "high", None, None

    monkeypatch.setattr(
        "app.services.document_type_sample_analyzer._parse_sample",
        slow_parse,
    )
    started = time.perf_counter()
    samples, _notes = parse_document_samples(
        [
            ("a.pdf", b"1"),
            ("b.pdf", b"2"),
            ("c.pdf", b"3"),
        ]
    )
    elapsed = time.perf_counter() - started
    assert len(samples) == 3
    assert elapsed < 0.14


def test_detect_text_invoice_in_body_without_title_line() -> None:
    profile = detect_recognition_signals(
        filename="scan.pdf",
        invoice=_invoice(email_attachment_name="scan.pdf"),
        parsed=_parsed(
            document_text="Please remit payment.\nTAX INVOICE\nVendor: Acme",
            document_heading="",
        ),
    )
    assert "text_invoice" in profile.signals


def test_contract_merge_resolves_invoice_noise_by_channel_scores() -> None:
    from app.services.document_type_recognition_signals import SampleSignalProfile

    noisy = frozenset(
        {
            "filename_contract",
            "heading_contract",
            "text_contract",
            "text_governing_law",
            "text_signed_behalf",
            "text_terms",
            "text_invoice",
            "text_tax_notice",
        }
    )
    profiles = [
        SampleSignalProfile("a.pdf", noisy, frozenset({"vendor"}), "CONTRACT"),
        SampleSignalProfile("b.pdf", noisy, frozenset({"vendor"}), "CONTRACT"),
    ]
    signals, layout = merge_signals_for_classifier_profiles(profiles)
    assert layout == "supporting_doc"
    assert "text_contract" in signals
    assert "text_invoice" not in signals
    assert "text_tax_notice" not in signals


def test_merge_signals_unions_channels_across_samples() -> None:
    from app.services.document_type_recognition_signals import SampleSignalProfile

    profiles = [
        SampleSignalProfile(
            filename="a.pdf",
            signals=frozenset({"heading_invoice", "has_invoice_number", "has_po_reference"}),
            extraction_fields=frozenset({"vendor"}),
            document_heading="TAX INVOICE",
        ),
        SampleSignalProfile(
            filename="b.pdf",
            signals=frozenset({"heading_invoice", "has_invoice_number", "has_total_amount"}),
            extraction_fields=frozenset({"vendor"}),
            document_heading="TAX INVOICE",
        ),
    ]
    signals, layout = merge_signals_for_classifier_profiles(profiles)
    assert layout == "grouped"
    assert signals == frozenset(
        {"heading_invoice", "has_invoice_number", "has_po_reference", "has_total_amount"}
    )


def test_detect_direct_expense_signals() -> None:
    profile = detect_recognition_signals(
        filename="receipt.pdf",
        invoice=_invoice(email_attachment_name="receipt.pdf"),
        parsed=_parsed(
            po_reference=None,
            document_text="TAX INVOICE\nTotal 110.00",
            document_heading="TAX INVOICE",
        ),
    )
    assert infer_playbook_profile(profile.signals) == "direct_expense"
    assert infer_classifier_layout(profile.signals, playbook="direct_expense") == "any_signal"


def test_detect_employee_claim_signals() -> None:
    profile = detect_recognition_signals(
        filename="expense-claim.pdf",
        invoice=_invoice(email_attachment_name="expense-claim.pdf"),
        parsed=_parsed(
            po_reference=None,
            invoice_no=None,
            document_text="Employee expense claim\nTotal 45.00",
            document_heading="Expense claim",
        ),
    )
    assert "text_claim" in profile.signals or "filename_claim" in profile.signals
    assert infer_playbook_profile(profile.signals) == "employee_claim"


def test_merge_signals_blocks_when_no_shared_identity() -> None:
    from app.services.document_type_recognition_signals import SampleSignalProfile

    profiles = [
        SampleSignalProfile(
            filename="po.pdf",
            signals=frozenset({"heading_po", "text_po", "filename_po"}),
            extraction_fields=frozenset({"vendor"}),
            document_heading="PURCHASE ORDER",
        ),
        SampleSignalProfile(
            filename="invoice.pdf",
            signals=frozenset({"heading_invoice", "has_invoice_number", "has_total_amount"}),
            extraction_fields=frozenset({"vendor"}),
            document_heading="TAX INVOICE",
        ),
    ]
    signals, layout = merge_signals_for_classifier_profiles(profiles)
    assert signals == frozenset()
    assert layout == "any_signal"


def test_classifier_layout_po_goods_uses_all_signals() -> None:
    signals = frozenset(
        {"has_po_reference", "has_invoice_number", "has_total_amount", "heading_invoice"}
    )
    assert infer_classifier_layout(signals, playbook="po_goods") == "all_signals"


def test_compliance_tax_notice_uses_grouped_layout() -> None:
    from app.services.document_type_recognition_signals import SampleSignalProfile

    profiles = [
        SampleSignalProfile(
            filename="ato-notice.pdf",
            signals=frozenset({"text_tax_notice", "filename_tax_notice"}),
            extraction_fields=frozenset({"vendor", "document_text"}),
            document_heading="Tax compliance notice",
        )
    ]
    signals, layout = merge_signals_for_classifier_profiles(profiles)
    assert layout == "grouped"
    assert "text_tax_notice" in signals
    assert "filename_tax_notice" in signals
    assert infer_playbook_profile(signals) == "compliance_route"


def test_merge_supporting_po_keeps_all_channel_signals() -> None:
    from app.services.document_type_recognition_signals import SampleSignalProfile

    profiles = [
        SampleSignalProfile(
            filename="po.pdf",
            signals=frozenset({"heading_po", "text_po", "filename_po"}),
            extraction_fields=frozenset({"vendor"}),
            document_heading="PURCHASE ORDER",
        )
    ]
    signals, layout = merge_signals_for_classifier_profiles(
        profiles, purchase_bundle_role="po"
    )
    assert layout == "supporting_doc"
    assert signals == frozenset({"heading_po", "text_po", "filename_po"})


def test_classifier_layout_expense_uses_any_signal() -> None:
    signals = frozenset({"has_invoice_number", "heading_invoice"})
    assert infer_classifier_layout(signals, playbook="direct_expense") == "any_signal"
