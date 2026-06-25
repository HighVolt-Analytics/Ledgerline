"""Tests for sample proposal engine."""

from datetime import date
from decimal import Decimal

from app.models.invoice import Invoice, InvoiceStatus
from app.schemas.document_type import DocumentTypeDefinition
from app.services.document_type_sample_types import ParsedDocumentSample
from app.services.invoice_data import InvoiceData
from app.services.sample_proposal_engine import build_sample_proposal


def _invoice(**kwargs) -> Invoice:
    base = dict(id=1, tenant_id=1, status=InvoiceStatus.PARSING, currency="AUD")
    base.update(kwargs)
    return Invoice(**base)


def _parsed(**kwargs) -> InvoiceData:
    base = dict(
        vendor="Acme Supplies Pty Ltd",
        invoice_no="INV-1001",
        invoice_date=date(2026, 3, 1),
        total=Decimal("110.00"),
        po_reference="PO-44871",
        document_text="TAX INVOICE\nPO Reference PO-44871\nTotal 110.00",
        document_heading="TAX INVOICE",
    )
    base.update(kwargs)
    return InvoiceData(**base)


def _sample(**kwargs) -> ParsedDocumentSample:
    filename = kwargs.pop("filename", "invoice-a.pdf")
    parsed = kwargs.pop("parsed", _parsed())
    return ParsedDocumentSample(
        filename=filename,
        invoice=_invoice(email_attachment_name=filename),
        parsed=parsed,
        confidence="high",
        **kwargs,
    )


def test_build_sample_proposal_heuristic_without_llm(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.sample_proposal_engine.is_azure_openai_enabled",
        lambda: False,
    )
    proposal = build_sample_proposal([_sample()])
    assert proposal.recognition_signals
    assert proposal.proposal_source == "heuristic"
    assert "vendor" in proposal.extraction_fields


def test_build_sample_proposal_hybrid_when_llm_available(monkeypatch) -> None:
    from app.schemas.sample_proposal_llm import LlmSampleProposal

    monkeypatch.setattr(
        "app.services.sample_proposal_engine.is_azure_openai_enabled",
        lambda: True,
    )
    monkeypatch.setattr(
        "app.services.sample_proposal_engine._request_llm_proposal",
        lambda samples, catalogue: LlmSampleProposal(
            playbook_profile="po_goods",
            recognition_signals=["heading_invoice", "has_po_reference"],
            extraction_fields=["vendor", "invoice_no", "po_reference", "total"],
            required_fields=["vendor", "invoice_no", "total"],
            absent_fields=[],
            classifier_layout="all_signals",
            one_line="PO-backed vendor invoice.",
            suggested_title="PO Goods Invoice",
            confidence=0.82,
            reasoning="Invoice references a purchase order and includes line totals.",
        ),
    )
    proposal = build_sample_proposal([_sample()])
    assert proposal.proposal_source == "hybrid"
    assert proposal.playbook_profile == "po_goods"
    assert proposal.reasoning


def test_build_sample_proposal_catalogue_match_fallback(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.sample_proposal_engine.is_azure_openai_enabled",
        lambda: False,
    )
    catalogue = [
        DocumentTypeDefinition(
            code="DT-02",
            title="PO Goods Invoice",
            shortTitle="PO Invoice",
            klass="Transactional",
            posting="Yes",
            fraudRisk="low",
            oneLine="Commercial invoice with PO reference",
            routeTarget="Purchase Management",
            playbookProfile="po_goods",
        )
    ]
    proposal = build_sample_proposal([_sample()], catalogue=catalogue)
    assert proposal.catalogue_matches
    assert proposal.catalogue_matches[0].code == "DT-02"
