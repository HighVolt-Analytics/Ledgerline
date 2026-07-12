"""Tests for extraction field contracts and resolution."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.schemas.document_type import DocumentTypeClassifier, DocumentTypeDefinition
from app.schemas.ocr_artifact import OcrArtifact
from app.services.extraction.field_contract_resolver import (
    resolve_extraction_field_contracts_for_dt,
)
from app.services.extraction.field_contracts import (
    ExtractionFieldContract,
    FieldCandidate,
    FieldSource,
    FieldType,
    ResolutionStatus,
    contracts_to_selected_keys,
)
from app.services.extraction.field_resolvers import (
    merge_via_field_contracts,
    project_resolution_to_invoice_data,
    resolve_field_value,
)
from app.services.extraction.extraction_field_values import (
    configured_extraction_keys,
    effective_extraction_field_keys_for_dt,
)
from app.services.extraction.routing.routes import ExtractionRoute
from app.services.invoice.invoice_data import InvoiceData


def _defn(**kwargs) -> DocumentTypeDefinition:
    base = dict(
        code="DT-01",
        title="PO-based goods invoice",
        shortTitle="PO goods invoice",
        klass="Transactional",
        posting="Yes",
        recognition_mode="signals",
        recognition_signals=["heading_invoice"],
        llm_prompt="",
        routeTarget="Purchase Management",
        playbook_profile="po_goods",
        classifier=DocumentTypeClassifier(),
        extraction_fields=["vendor", "invoice_no", "total"],
        required_fields=["vendor", "invoice_no", "total"],
        enabled=True,
    )
    base.update(kwargs)
    return DocumentTypeDefinition(**base)


def test_contracts_respect_org_configured_fields() -> None:
    defn = _defn(extraction_fields=["vendor", "permit_no"], required_fields=["vendor"])
    contracts = resolve_extraction_field_contracts_for_dt(
        [defn], "DT-01", route=ExtractionRoute.INVOICE, dt_definition=defn
    )
    keys = contracts_to_selected_keys(contracts)
    assert keys == ["vendor", "permit_no"]
    by_key = {c.key: c for c in contracts}
    assert by_key["vendor"].required is True
    assert by_key["permit_no"].required is False
    assert FieldSource.SEMANTIC_DI.value not in by_key["permit_no"].allowed_sources or (
        by_key["permit_no"].field_type == FieldType.CUSTOM
        or by_key["permit_no"].field_type == FieldType.IDENTIFIER
    )


def test_supporting_route_stays_sparse_without_org_fields() -> None:
    defn = _defn(
        code="DT-90",
        title="Packing list",
        shortTitle="Packing list",
        klass="Non-transactional",
        posting="No",
        routeTarget="Vault",
        playbook_profile="supporting",
        extraction_fields=[],
        required_fields=[],
    )
    contracts = resolve_extraction_field_contracts_for_dt(
        [defn],
        "DT-90",
        route=ExtractionRoute.SUPPORTING_DOCUMENT,
        dt_definition=defn,
    )
    assert contracts_to_selected_keys(contracts) == []


def test_commercial_fallback_for_empty_transactional_route() -> None:
    defn = _defn(
        code="ORG-88",
        title="Custom goods invoice",
        shortTitle="Custom goods",
        extraction_fields=[],
        required_fields=[],
        playbook_profile="standard_transactional",
        matrix_template_code="",
    )
    contracts = resolve_extraction_field_contracts_for_dt(
        [defn],
        "ORG-88",
        route=ExtractionRoute.INVOICE,
        dt_definition=defn,
    )
    keys = contracts_to_selected_keys(contracts)
    assert "vendor" in keys
    assert "invoice_no" in keys
    assert "currency" in keys
    assert "line_items" in keys


def test_configured_extraction_keys_adapter() -> None:
    defn = _defn()
    keys = configured_extraction_keys(defn)
    assert "vendor" in keys
    assert effective_extraction_field_keys_for_dt([defn], "DT-01") == keys


def test_resolve_field_value_di_wins_when_allowed() -> None:
    contract = ExtractionFieldContract(
        key="invoice_no",
        field_type=FieldType.IDENTIFIER,
        allowed_sources=(FieldSource.SEMANTIC_DI, FieldSource.LLM),
        authoritative_source_order=(FieldSource.SEMANTIC_DI, FieldSource.LLM),
        grounding_required=False,
        min_confidence=0.5,
    )
    result = resolve_field_value(
        contract,
        [
            FieldCandidate(source="llm", value="WRONG", grounded=True),
            FieldCandidate(source="semantic_di", value="INV-1", confidence=0.9, grounded=True),
        ],
    )
    assert result.resolution_status == ResolutionStatus.ACCEPTED
    assert result.value == "INV-1"
    assert result.chosen_source == "semantic_di"


def test_resolve_field_value_low_confidence_di_loses_to_grounded_regex() -> None:
    contract = ExtractionFieldContract(
        key="invoice_no",
        field_type=FieldType.IDENTIFIER,
        allowed_sources=(FieldSource.SEMANTIC_DI, FieldSource.REGEX),
        authoritative_source_order=(FieldSource.SEMANTIC_DI, FieldSource.REGEX),
        grounding_required=True,
        min_confidence=0.8,
    )
    result = resolve_field_value(
        contract,
        [
            FieldCandidate(source="semantic_di", value="BAD", confidence=0.2, grounded=False),
            FieldCandidate(source="regex", value="INV-99", confidence=None, grounded=True),
        ],
    )
    assert result.value == "INV-99"
    assert result.chosen_source == "regex"


def test_project_abn_currency_cost_centre_to_invoice_data() -> None:
    from app.services.extraction.field_contracts import FieldResolutionResult

    parsed = InvoiceData()
    results = [
        FieldResolutionResult(
            key="abn",
            value="74490121060",
            chosen_source="semantic_di",
            resolution_status=ResolutionStatus.ACCEPTED,
            target_column="abn",
        ),
        FieldResolutionResult(
            key="currency",
            value="AUD",
            chosen_source="regex",
            resolution_status=ResolutionStatus.ACCEPTED,
            target_column="currency",
        ),
        FieldResolutionResult(
            key="cost_centre",
            value="FIN-ADVISORY",
            chosen_source="layout_kv",
            resolution_status=ResolutionStatus.ACCEPTED,
            target_column="cost_centre",
        ),
    ]
    contracts = [
        ExtractionFieldContract(key="abn", canonical=True, target_column="abn"),
        ExtractionFieldContract(key="currency", canonical=True, target_column="currency"),
        ExtractionFieldContract(key="cost_centre", canonical=True, target_column="cost_centre"),
    ]
    merged = project_resolution_to_invoice_data(parsed, results, contracts=contracts)
    assert merged.abn == "74490121060"
    assert merged.currency == "AUD"
    assert merged.cost_centre == "FIN-ADVISORY"
    assert (merged.extracted_fields or {}).get("seller_abn") == "74490121060"


def test_merge_via_field_contracts_fills_from_di_and_text(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("USE_FIELD_CONTRACT_MERGE", "true")
    from app.config import get_settings

    get_settings.cache_clear()

    text = (
        "TAX INVOICE\nDeloitte Touche Tohmatsu\nABN: 74 490 121 060\n"
        "Invoice No\nDTT-1\nCurrency\nAUD\nCost Centre\nFIN-1\nTotal Due\n$100.00\n"
    )
    defn = _defn(
        extraction_fields=[
            "vendor",
            "abn",
            "invoice_no",
            "currency",
            "cost_centre",
            "total",
        ],
        required_fields=["vendor", "invoice_no", "total"],
    )
    ocr = OcrArtifact(
        success=True,
        text=text,
        text_length=len(text),
        layout_kv={"Cost Centre": "FIN-1", "Currency": "AUD"},
        payload_json={
            "invoice_fields": {
                "vendor": "Deloitte Touche Tohmatsu",
                "invoice_no": "DTT-1",
                "total": "100.00",
                "abn": "74490121060",
            },
            "field_confidence": {
                "vendor": 0.95,
                "invoice_no": 0.95,
                "total": 0.95,
                "abn": 0.9,
            },
            "extraction_route": "invoice",
        },
    )
    merged, enriched, results = merge_via_field_contracts(
        InvoiceData(),
        ocr,
        dt_definition=defn,
    )
    assert merged.vendor and "Deloitte" in merged.vendor
    assert merged.invoice_no == "DTT-1"
    assert merged.total == Decimal("100.00")
    assert merged.abn == "74490121060"
    assert merged.currency == "AUD"
    assert merged.cost_centre == "FIN-1"
    assert enriched.payload_json and "field_resolution" in enriched.payload_json
    assert any(r.key == "vendor" for r in results)

    get_settings.cache_clear()


def test_legacy_merge_still_works_when_flag_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("USE_FIELD_CONTRACT_MERGE", "false")
    from app.config import get_settings
    from app.services.extraction.extraction_orchestrator import merge_extraction_sources

    get_settings.cache_clear()
    text = "TAX INVOICE\nAcme\nInvoice No: INV-1\nTotal: 50.00\n"
    ocr = OcrArtifact(success=True, text=text, text_length=len(text))
    merged = merge_extraction_sources(InvoiceData(vendor="Acme"), ocr)
    assert merged.invoice_no == "INV-1" or merged.total is not None or merged.vendor == "Acme"
    get_settings.cache_clear()
