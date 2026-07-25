"""Configured DT match ranking: specificity over raw priority."""

from __future__ import annotations

from decimal import Decimal

from app.models.invoice import Invoice, InvoiceStatus
from app.schemas.document_type import DocumentTypeClassifier, DocumentTypeDefinition
from app.services.classification.document_type_rule_engine import (
    list_configured_document_type_matches,
    match_configured_document_type,
)
from app.services.invoice.invoice_data import InvoiceData
from app.tenant_ids import TESTING_TENANT_UUID


def _invoice(**kwargs) -> Invoice:
    base = dict(
        id=614,
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.PARSING,
        currency="USD",
        vendor="Lexar Co",
        invoice_no="82507681",
        document_heading="INVOICE",
        document_text="INVOICE\nInvoice No 82507681\nCustomer PO PO-250742524\nTotal 18864.00",
        email_attachment_name="lexar-invoice.pdf",
    )
    base.update(kwargs)
    return Invoice(**base)


def _parsed(**kwargs) -> InvoiceData:
    base = dict(
        vendor="Lexar Co",
        invoice_no="82507681",
        total=Decimal("18864.00"),
        document_heading="INVOICE",
        document_text="INVOICE\nInvoice No 82507681\nCustomer PO PO-250742524\nTotal 18864.00",
        po_reference="PO-250742524",
    )
    base.update(kwargs)
    return InvoiceData(**base)


def _playbook_dt(
    code: str,
    *,
    title: str,
    profile: str,
    priority: int,
) -> DocumentTypeDefinition:
    """Prompt-mode DT whose identity comes from playbook recommended signals."""
    return DocumentTypeDefinition(
        code=code,
        title=title,
        shortTitle=code,
        klass="Transactional",
        posting="Yes",
        recognition_mode="prompt",
        recognition_signals=[],
        llm_prompt="Classify this document type.",
        playbookProfile=profile,
        routeTarget="Purchase Management",
        enabled=True,
        classifier=DocumentTypeClassifier(
            enabled=True,
            priority=priority,
            confidence=0.85,
            root={"type": "group", "operator": "AND", "children": []},
        ),
    )


def test_po_present_prefers_po_goods_over_non_po_despite_worse_priority() -> None:
    """Long-term: Non-PO must not win on priority alone when a PO is present."""
    non_po = _playbook_dt(
        "DT-04",
        title="Non-PO vendor invoice",
        profile="standard_transactional",
        priority=100,  # better (lower) priority — used to wrongly win
    )
    po_goods = _playbook_dt(
        "DT-03",
        title="PO-based goods invoice",
        profile="po_goods",
        priority=180,
    )
    invoice = _invoice(po_reference="PO-250742524")
    parsed = _parsed(po_reference="PO-250742524")

    hit = match_configured_document_type(
        [non_po, po_goods],
        invoice=invoice,
        parsed=parsed,
    )
    assert hit is not None
    assert hit[0].code == "DT-03"

    ordered = list_configured_document_type_matches(
        [non_po, po_goods],
        invoice=invoice,
        parsed=parsed,
    )
    assert [d.code for d, _ in ordered] == ["DT-03", "DT-04"]


def test_without_po_non_po_invoice_still_wins() -> None:
    non_po = _playbook_dt(
        "DT-04",
        title="Non-PO vendor invoice",
        profile="standard_transactional",
        priority=100,
    )
    po_goods = _playbook_dt(
        "DT-03",
        title="PO-based goods invoice",
        profile="po_goods",
        priority=50,  # better priority, but requires PO so should not match
    )
    invoice = _invoice(po_reference=None)
    parsed = _parsed(po_reference=None)

    hit = match_configured_document_type(
        [po_goods, non_po],
        invoice=invoice,
        parsed=parsed,
    )
    assert hit is not None
    assert hit[0].code == "DT-04"


def test_equal_specificity_falls_back_to_priority() -> None:
    """When neither requires PO, lower priority still wins."""
    a = _playbook_dt(
        "DT-04",
        title="Non-PO A",
        profile="standard_transactional",
        priority=80,
    )
    b = _playbook_dt(
        "DT-44",
        title="Non-PO B",
        profile="standard_transactional",
        priority=40,
    )
    invoice = _invoice(po_reference=None)
    parsed = _parsed(po_reference=None)

    hit = match_configured_document_type([a, b], invoice=invoice, parsed=parsed)
    assert hit is not None
    assert hit[0].code == "DT-44"
