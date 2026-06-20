"""Tests for document-type playbook catalogue enforcement."""

from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.invoice import Invoice, InvoiceStatus
from app.schemas.document_type import DocumentTypeDefinition
from app.services.document_type_playbook_service import (
    PlaybookGateResult,
    effective_extraction_fields,
    effective_required_fields,
    evaluate_playbook_gates,
    extraction_field_keys_from_playbook,
    is_dt_code,
    split_bundle_items,
)
from app.services.invoice_data import InvoiceData, ParsedLineItem
from app.services.routing_review_service import requires_playbook_review, requires_routing_review
from app.services.document_type_classifier import DocumentTypeClassification


def _definition(**kwargs) -> DocumentTypeDefinition:
    base = dict(
        code="DT-01",
        title="PO goods invoice",
        shortTitle="PO goods",
        klass="Transactional",
        posting="Yes",
        fraudRisk="low",
        oneLine="test",
        routeTarget="Purchase Management",
        extraction=[
            "Vendor name & tax ID / ABN",
            "Vendor invoice number, invoice date",
            "PO number(s)",
        ],
        match=["3-way (PO ↔ GRN ↔ Invoice) at line level"],
        bundleMandatory=["DT-14", "DT-15"],
    )
    base.update(kwargs)
    return DocumentTypeDefinition(**base)


def test_split_bundle_items_dt_and_text() -> None:
    dt, text = split_bundle_items(["DT-14", "Quality certificate", "DT-15"])
    assert dt == ["DT-14", "DT-15"]
    assert text == ["Quality certificate"]


def test_is_dt_code() -> None:
    assert is_dt_code("DT-14") is True
    assert is_dt_code("quality certificate") is False


def test_extraction_maps_to_field_keys() -> None:
    definition = _definition()
    keys = extraction_field_keys_from_playbook(definition)
    assert "vendor" in keys
    assert "invoice_no" in keys
    assert "po_reference" in keys


def test_effective_extraction_fields_prefers_explicit_keys() -> None:
    definition = _definition(extractionFields=["vendor", "total"])
    assert effective_extraction_fields(definition) == ["vendor", "total"]


def test_effective_required_fields_merges_extraction() -> None:
    definition = _definition(requiredFields=["total"], extractionFields=["po_reference"])
    keys = effective_required_fields(definition)
    assert keys == ["po_reference"]


def test_normalize_custom_extraction_field_key() -> None:
    from app.services.document_type_field_keys import normalize_extraction_field_keys

    keys = normalize_extraction_field_keys(["vendor", "Contract_Party", "INVALID-KEY", "milestone_1"])
    assert keys == ["vendor", "contract_party", "milestone_1"]


def test_bundle_mandatory_normalizes_dt_codes() -> None:
    definition = _definition(bundleMandatory=["dt-14", "DT-15", "not-a-code", "DT-14"])
    assert definition.bundle_mandatory == ["DT-14", "DT-15"]


def test_bundle_conditional_keeps_advisory_text() -> None:
    definition = _definition(
        bundleConditional=["DT-14", "Quality certificate", "dt-14", "Packing list"]
    )
    assert definition.bundle_conditional == ["DT-14", "Quality certificate", "Packing list"]


def test_playbook_blocks_posting_when_bundle_missing() -> None:
    playbook = PlaybookGateResult(
        missing_bundle_mandatory=("DT-14",),
        missing_bundle_conditional_dt=(),
        conditional_advisories=(),
        missing_extraction_fields=(),
    )
    assert playbook.blocks_posting is True
    assert requires_playbook_review(playbook) is True


@pytest.mark.asyncio
async def test_evaluate_playbook_gates_no_po_reference() -> None:
    definition = _definition()
    invoice = Invoice(
        id=1,
        org_id=1,
        status=InvoiceStatus.VALIDATING,
        po_reference=None,
        document_type_code="DT-01",
    )
    parsed = InvoiceData(
        vendor="Acme",
        invoice_no="INV-1",
        total=Decimal("100"),
        line_items=[ParsedLineItem(description="Item", qty=Decimal("1"), amount=Decimal("100"))],
    )
    session = AsyncMock()
    result = await evaluate_playbook_gates(
        session,
        invoice=invoice,
        parsed=parsed,
        definition=definition,
    )
    assert result.missing_bundle_mandatory == ("DT-14", "DT-15")
    assert result.blocks_posting is True


def test_routing_review_includes_playbook_gate() -> None:
    inv = Invoice(org_id=1, status=InvoiceStatus.VALIDATING, route_target="Purchase Management")
    classification = DocumentTypeClassification(
        "DT-01",
        0.95,
        "matched",
        min_route_confidence=0.65,
    )
    playbook = PlaybookGateResult(
        missing_bundle_mandatory=("DT-15",),
        missing_bundle_conditional_dt=(),
        conditional_advisories=(),
        missing_extraction_fields=(),
    )
    assert requires_routing_review(inv, classification, playbook=playbook) is True
