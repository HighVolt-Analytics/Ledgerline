
from app.tenant_ids import PLATFORM_TENANT_UUID, TESTING_TENANT_UUID
"""Tests for document-type playbook catalogue enforcement."""

from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.invoice import Invoice, InvoiceStatus
from app.schemas.document_type import DocumentTypeDefinition
from app.services.classification.document_type_playbook_service import (
    PlaybookGateResult,
    confidence_gate_fields,
    effective_extraction_fields,
    effective_optional_extraction_fields,
    effective_playbook_required_fields,
    effective_required_fields,
    evaluate_playbook_gates,
    extraction_field_keys_from_playbook,
    is_dt_code,
    missing_extraction_fields,
    split_bundle_items,
)
from app.services.invoice.invoice_data import InvoiceData, ParsedLineItem
from app.services.invoice.routing_review_service import requires_playbook_review, requires_routing_review
from app.services.classification.document_type_classifier import DocumentTypeClassification


def _definition(**kwargs) -> DocumentTypeDefinition:
    base = dict(
        code="DT-01",
        title="PO goods invoice",
        shortTitle="PO goods",
        klass="Transactional",
        posting="Yes",
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


def test_effective_required_fields_uses_explicit_subset() -> None:
    definition = _definition(requiredFields=["total"], extractionFields=["po_reference", "total"])
    assert effective_required_fields(definition) == ["total"]
    assert effective_optional_extraction_fields(definition) == ["po_reference"]


def test_effective_required_fields_falls_back_to_extraction() -> None:
    definition = _definition(requiredFields=[], extractionFields=["vendor", "total"])
    assert effective_required_fields(definition) == ["vendor", "total"]


def test_confidence_gate_fields_respects_required_and_absent() -> None:
    definition = _definition(
        playbookProfile="supporting",
        requiredFields=["vendor", "permit_no", "invoice_no"],
        extractionFields=["vendor", "permit_no", "invoice_no"],
        absentFields=["invoice_no", "due_date"],
    )
    assert confidence_gate_fields(definition) == ["permit_no", "vendor"]


def test_confidence_gate_fields_fallback_when_no_definition() -> None:
    assert confidence_gate_fields(None) == ["vendor", "total"]


def test_playbook_required_fields_skip_infrastructure_and_soft_customs() -> None:
    definition = _definition(
        playbookProfile="supporting",
        requiredFields=[
            "attachment_name",
            "document_text",
            "permit_no",
            "consignment_ref",
            "vendor",
        ],
        extractionFields=[
            "attachment_name",
            "document_text",
            "permit_no",
            "consignment_ref",
            "vendor",
        ],
    )
    assert effective_playbook_required_fields(definition) == ["permit_no", "vendor"]


def test_missing_extraction_fields_uses_permit_regex() -> None:
    definition = _definition(
        playbookProfile="supporting",
        requiredFields=["vendor", "permit_no"],
        extractionFields=["vendor", "permit_no", "consignment_ref"],
    )
    invoice = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.PARSING,
        vendor="Spectra Innovations Pte Ltd",
        currency="AUD",
    )
    parsed = InvoiceData(
        vendor="Spectra Innovations Pte Ltd",
        document_text="CLEARANCE PERMIT\nPermit No: OD6E379991N",
        extracted_fields={"permit_no": "OD6E379991N"},
    )
    missing = missing_extraction_fields(definition, invoice=invoice, parsed=parsed)
    assert missing == []


def test_normalize_custom_extraction_field_key() -> None:
    from app.services.classification.document_type_field_keys import normalize_extraction_field_keys

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
async def test_evaluate_playbook_gates_direct_expense_no_bundle_enforcement() -> None:
    definition = _definition(
        code="DT-08",
        playbookProfile="direct_expense",
        bundleMandatory=[],
        absentFields=["po_reference"],
        extractionFields=["vendor", "invoice_no", "total"],
        requiredFields=["vendor", "invoice_no", "total"],
        extraction=[],
    )
    invoice = Invoice(
        id=2,
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.VALIDATING,
        po_reference=None,
        document_type_code="DT-08",
    )
    parsed = InvoiceData(
        vendor="Utility Co",
        invoice_no="UTIL-1",
        total=Decimal("50"),
        line_items=[ParsedLineItem(description="Power", qty=Decimal("1"), amount=Decimal("50"))],
    )
    session = AsyncMock()
    result = await evaluate_playbook_gates(
        session,
        invoice=invoice,
        parsed=parsed,
        definition=definition,
    )
    assert result.missing_bundle_mandatory == ()
    assert result.linkage_key_missing is False
    assert result.block_reason is None
    assert result.blocks_posting is False
    assert requires_playbook_review(result, definition=definition) is False


@pytest.mark.asyncio
async def test_evaluate_playbook_gates_no_po_reference() -> None:
    definition = _definition(playbookProfile="po_goods")
    invoice = Invoice(
        id=1,
        tenant_id=TESTING_TENANT_UUID,
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
    assert result.linkage_key_missing is True
    assert result.block_reason == "linkage"


def test_routing_review_includes_playbook_gate() -> None:
    inv = Invoice(tenant_id=TESTING_TENANT_UUID, status=InvoiceStatus.VALIDATING, route_target="Purchase Management")
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


def test_resolve_playbook_exception_linkage() -> None:
    from app.services.classification.document_type_playbook_service import resolve_playbook_exception

    code, reason, _ = resolve_playbook_exception(
        {
            "block_reason": "linkage",
            "linkage_key_missing": True,
            "missing_bundle_mandatory": ["DT-02"],
        }
    )
    assert code == "LINKAGE_KEY_MISSING"
    assert "PO reference" in reason


def test_resolve_playbook_exception_linkage_sales() -> None:
    from app.services.classification.document_type_playbook_service import resolve_playbook_exception

    code, reason, remediation = resolve_playbook_exception(
        {
            "block_reason": "linkage",
            "linkage_key_missing": True,
            "linkage_book": "sales",
            "missing_bundle_mandatory": ["DT-26"],
        }
    )
    assert code == "LINKAGE_KEY_MISSING"
    assert "SO reference" in reason
    assert "SO copy" in remediation


def test_resolve_playbook_exception_bundle_labels() -> None:
    from app.services.classification.document_type_playbook_service import resolve_playbook_exception

    code, reason, _ = resolve_playbook_exception(
        {
            "block_reason": "bundle",
            "missing_bundle_mandatory": ["DT-02"],
            "missing_bundle_mandatory_labels": {"DT-02": "PO (supporting)"},
        }
    )
    assert code == "BUNDLE_INCOMPLETE"
    assert "PO (supporting)" in reason


def test_playbook_validation_vr_pb01_optional_only() -> None:
    from app.services.classification.document_type_playbook_service import playbook_validation_results

    playbook = PlaybookGateResult(
        missing_bundle_mandatory=(),
        missing_bundle_conditional_dt=(),
        conditional_advisories=(),
        missing_extraction_fields=("vendor",),
        missing_optional_extraction_fields=("invoice_no",),
    )
    results = playbook_validation_results(playbook)
    assert len(results) == 1
    assert results[0].rule == "VR-PB01"
    assert "invoice_no" in results[0].message
    assert "vendor" not in results[0].message


def test_suggest_reclassify_direct_expense_when_linkage_missing() -> None:
    from app.services.classification.document_type_playbook_service import suggest_reclassify_direct_expense_code

    definition = _definition(playbookProfile="po_goods")
    catalogue = [
        definition,
        _definition(code="DT-08", playbookProfile="direct_expense", bundleMandatory=[]),
    ]
    playbook = PlaybookGateResult(
        missing_bundle_mandatory=("DT-14",),
        missing_bundle_conditional_dt=(),
        conditional_advisories=(),
        missing_extraction_fields=(),
        linkage_key_missing=True,
        block_reason="linkage",
    )
    assert suggest_reclassify_direct_expense_code(playbook, definition, catalogue) == "DT-08"
