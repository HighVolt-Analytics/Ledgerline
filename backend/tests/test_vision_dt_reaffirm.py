"""Unit tests for post-extract DT reaffirm / flip."""

from __future__ import annotations

from decimal import Decimal

from app.models.invoice import Invoice, InvoiceStatus
from app.schemas.document_type import DocumentTypeDefinition
from app.services.invoice.vision_dt_reaffirm import (
    link_signal_justifies_dt_flip,
    rematch_document_type_after_extract,
)
from app.tenant_ids import TESTING_TENANT_UUID


def _catalogue() -> list[DocumentTypeDefinition]:
    return [
        DocumentTypeDefinition(
            code="DT-01",
            title="Non-PO vendor invoice",
            shortTitle="Non-PO Invoice",
            klass="Transactional",
            posting="Yes",
            recognitionMode="prompt",
            recognitionSignals=[],
            llmPrompt="",
            routeTarget="Purchase Management",
            enabled=True,
            playbookProfile="standard_transactional",
            classifier={"enabled": False, "priority": 80, "confidence": 0.85},
        ),
        DocumentTypeDefinition(
            code="DT-03",
            title="PO-based goods invoice",
            shortTitle="PO Goods Invoice",
            klass="Transactional",
            posting="Yes",
            recognitionMode="prompt",
            recognitionSignals=[],
            llmPrompt="",
            routeTarget="Purchase Management",
            enabled=True,
            playbookProfile="po_goods",
            classifier={"enabled": False, "priority": 40, "confidence": 0.9},
        ),
        DocumentTypeDefinition(
            code="DT-10",
            title="Advance requisition",
            shortTitle="Advance",
            klass="Transactional",
            posting="Yes",
            recognitionMode="prompt",
            recognitionSignals=[],
            llmPrompt="",
            routeTarget="Team Expenses",
            enabled=True,
            playbookProfile="employee_claim",
            teamExpenseKind="advance_requisition",
            classifier={"enabled": True, "priority": 30, "confidence": 0.9},
        ),
        DocumentTypeDefinition(
            code="DT-08",
            title="Expense Claim",
            shortTitle="Expense Claim",
            klass="Transactional",
            posting="Yes",
            recognitionMode="prompt",
            recognitionSignals=[],
            llmPrompt="",
            routeTarget="Expenses Management",
            enabled=True,
            playbookProfile="direct_expense",
            classifier={"enabled": True, "priority": 20, "confidence": 0.85},
        ),
    ]


def test_link_signal_justifies_po_flip() -> None:
    assert link_signal_justifies_dt_flip(
        current_code="DT-01",
        rematch_code="DT-03",
        document_types=_catalogue(),
    )
    assert not link_signal_justifies_dt_flip(
        current_code="DT-03",
        rematch_code="DT-03",
        document_types=_catalogue(),
    )


def test_link_signal_never_demotes_team_expenses_to_expense_claim() -> None:
    assert not link_signal_justifies_dt_flip(
        current_code="DT-10",
        rematch_code="DT-08",
        document_types=_catalogue(),
    )


def test_link_signal_never_te_to_te_on_playbook_alone() -> None:
    """Unpinned TE DTs that differ only by playbook must not flip."""
    types = [
        DocumentTypeDefinition(
            code="DT-10",
            title="Staff funding request",
            shortTitle="Funding",
            klass="Transactional",
            posting="Yes",
            recognitionMode="prompt",
            recognitionSignals=[],
            llmPrompt="",
            routeTarget="Team Expenses",
            enabled=True,
            playbookProfile="standard_transactional",
            classifier={"enabled": True, "priority": 30, "confidence": 0.9},
        ),
        DocumentTypeDefinition(
            code="DT-08",
            title="Expense Claim",
            shortTitle="Claim",
            klass="Transactional",
            posting="Yes",
            recognitionMode="prompt",
            recognitionSignals=[],
            llmPrompt="",
            routeTarget="Team Expenses",
            enabled=True,
            playbookProfile="employee_claim",
            classifier={"enabled": True, "priority": 20, "confidence": 0.85},
        ),
    ]
    assert not link_signal_justifies_dt_flip(
        current_code="DT-10",
        rematch_code="DT-08",
        document_types=types,
    )


def test_link_signal_preserves_pinned_advance_requisition_kind() -> None:
    """Both DTs can be TE; rematch must not rewrite advance_requisition → expense_claim."""
    types = _catalogue()
    for i, dt in enumerate(types):
        if dt.code == "DT-08":
            types[i] = dt.model_copy(
                update={
                    "route_target": "Team Expenses",
                    "playbook_profile": "employee_claim",
                    "team_expense_kind": "expense_claim",
                }
            )
    assert not link_signal_justifies_dt_flip(
        current_code="DT-10",
        rematch_code="DT-08",
        document_types=types,
    )


def test_rematch_flips_non_po_to_po_goods_when_po_present() -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.PARSING,
        document_heading="TAX INVOICE",
        invoice_no="INV-PUR-001",
        po_reference="PO-TEST-001",
        total=Decimal("5500.00"),
        vendor="Everest Furnishings",
        document_type_code="DT-01",
        extracted_fields={"canonical_document_type": "Tax Invoice"},
    )
    rematch = rematch_document_type_after_extract(
        invoice=inv,
        document_types=_catalogue(),
        heading_kind="tax_invoice",
        current_code="DT-01",
    )
    assert rematch is not None
    assert rematch.code == "DT-03"
    assert rematch.reason == "classifier_matched"


def test_rematch_no_flip_when_already_po_goods() -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.PARSING,
        document_heading="TAX INVOICE",
        invoice_no="INV-PUR-001",
        po_reference="PO-TEST-001",
        total=Decimal("5500.00"),
        vendor="Everest",
        document_type_code="DT-03",
    )
    rematch = rematch_document_type_after_extract(
        invoice=inv,
        document_types=_catalogue(),
        heading_kind="tax_invoice",
        current_code="DT-03",
    )
    assert rematch is None
