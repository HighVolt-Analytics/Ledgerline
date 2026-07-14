"""Field resolution telemetry — logging only, no extraction behavior change."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.schemas.ocr_artifact import OcrArtifact
from app.services.extraction.field_contracts import (
    ExtractionFieldContract,
    FieldCandidate,
    FieldResolutionResult,
    FieldSource,
    FieldType,
    ResolutionStatus,
)
from app.services.extraction.field_resolution_telemetry import (
    attach_field_resolution_telemetry,
    build_legacy_merge_telemetry,
    build_posting_critical_telemetry,
    detail_from_parsed_telemetry,
)
from app.services.invoice.invoice_data import InvoiceData, ParsedLineItem


def test_build_posting_critical_telemetry_di_win() -> None:
    results = [
        FieldResolutionResult(
            key="total",
            value=Decimal("110.00"),
            chosen_source="semantic_di",
            confidence=0.95,
            resolution_status=ResolutionStatus.ACCEPTED,
        )
    ]
    candidates = {
        "total": [
            FieldCandidate(source="semantic_di", value=Decimal("110.00"), confidence=0.95, grounded=True),
            FieldCandidate(source="llm", value=Decimal("100.00"), confidence=0.8, grounded=True),
        ]
    }
    detail = build_posting_critical_telemetry(results, candidates, ocr=OcrArtifact(success=True))
    total = detail["fields"]["total"]
    assert total["chosen_source"] == "azure_di"
    assert total["di_value"] == "110.00"
    assert total["llm_value"] == "100.00"
    assert total["agreed"] is False
    assert detail["di_availability"]["di_available"] is False


def test_build_posting_critical_telemetry_agreement() -> None:
    results = [
        FieldResolutionResult(
            key="invoice_no",
            value="INV-1",
            chosen_source="semantic_di",
            resolution_status=ResolutionStatus.ACCEPTED,
        )
    ]
    candidates = {
        "invoice_no": [
            FieldCandidate(source="semantic_di", value="INV-1", confidence=0.9, grounded=True),
            FieldCandidate(source="llm", value="INV-1", confidence=0.85, grounded=True),
        ]
    }
    detail = build_posting_critical_telemetry(results, candidates)
    row = detail["fields"]["invoice_no"]
    assert row["agreed"] is True
    assert row["chosen_source"] == "azure_di"


def test_attach_telemetry_does_not_change_scalars() -> None:
    parsed = InvoiceData(vendor="Acme", total=Decimal("50.00"))
    detail = {
        "fields": {
            "total": {
                "field_name": "total",
                "chosen_source": "azure_di",
                "di_value": "50.00",
                "llm_value": "49.00",
                "agreed": False,
            }
        }
    }
    enriched = attach_field_resolution_telemetry(parsed, detail)
    assert enriched.total == Decimal("50.00")
    assert enriched.vendor == "Acme"
    assert detail_from_parsed_telemetry(enriched) == detail


def test_legacy_merge_telemetry_infers_chosen_source() -> None:
    llm = InvoiceData(total=Decimal("100.00"), vendor="Acme")
    di = InvoiceData(total=Decimal("110.00"), vendor="Acme Pty Ltd")
    merged = InvoiceData(total=Decimal("110.00"), vendor="Acme Pty Ltd")
    detail = build_legacy_merge_telemetry(
        field_keys=["total", "vendor"],
        llm_parsed=llm,
        di_parsed=di,
        merged=merged,
        ocr=OcrArtifact(
            success=True,
            payload_json={
                "invoice_fields": {"total": "110.00"},
                "field_confidence": {"total": 0.92},
            },
        ),
    )
    assert detail["fields"]["total"]["chosen_source"] == "azure_di"
    assert detail["fields"]["total"]["agreed"] is False
    assert detail["di_availability"]["di_available"] is True


@pytest.mark.asyncio
async def test_merge_output_unchanged_with_telemetry_attached(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.schemas.document_type import DocumentTypeClassifier, DocumentTypeDefinition
    from app.services.extraction.field_resolvers import merge_via_field_contracts

    monkeypatch.setenv("USE_FIELD_CONTRACT_MERGE", "true")
    from app.config import get_settings

    get_settings.cache_clear()

    text = "TAX INVOICE\nDeloitte\nInvoice No: DTT-1\nTotal: 100.00\nABN: 74490121060\n"
    defn = DocumentTypeDefinition(
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
        extraction_fields=["vendor", "invoice_no", "total", "abn", "currency", "cost_centre"],
        required_fields=["vendor", "invoice_no", "total"],
        enabled=True,
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
    merged, _, _ = merge_via_field_contracts(InvoiceData(), ocr, dt_definition=defn)
    assert merged.vendor and "Deloitte" in merged.vendor
    assert merged.total == Decimal("100.00")
    assert detail_from_parsed_telemetry(merged) is not None
    assert merged.total == Decimal("100.00")

    get_settings.cache_clear()


def test_merge_via_field_contracts_same_output_before_after_telemetry_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Telemetry attachment must not alter resolved scalar fields."""
    from app.services.extraction.extraction_orchestrator import merge_extraction_sources

    monkeypatch.setenv("USE_FIELD_CONTRACT_MERGE", "true")
    from app.config import get_settings

    get_settings.cache_clear()

    parsed = InvoiceData(
        vendor="Acme",
        invoice_no="INV-9",
        total=Decimal("42.00"),
        line_items=[ParsedLineItem(description="Widget", qty=Decimal("1"), amount=Decimal("42"))],
    )
    ocr = OcrArtifact(
        success=True,
        text="Invoice INV-9 Total 42.00",
        text_length=24,
        payload_json={
            "invoice_fields": {"vendor": "Acme Pty", "invoice_no": "INV-9", "total": "42.00"},
            "field_confidence": {"vendor": 0.9, "invoice_no": 0.9, "total": 0.9},
            "extraction_route": "invoice",
        },
    )
    from app.schemas.document_type import DocumentTypeClassifier, DocumentTypeDefinition

    defn = DocumentTypeDefinition(
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
        extraction_fields=["vendor", "invoice_no", "total", "line_items"],
        required_fields=["vendor", "invoice_no", "total"],
        enabled=True,
    )
    merged = merge_extraction_sources(parsed, ocr, dt_definition=defn)
    assert merged.vendor
    assert merged.invoice_no == "INV-9"
    assert merged.total == Decimal("42.00")
    telemetry = detail_from_parsed_telemetry(merged)
    assert telemetry is not None
    assert "total" in telemetry.get("fields", {})

    get_settings.cache_clear()


def test_detail_from_parsed_telemetry_roundtrip() -> None:
    parsed = InvoiceData(vendor="Acme", total=Decimal("10.00"))
    detail = {
        "document_ai_provider": "azure_foundry_vision",
        "fields": {
            "total": {
                "field_name": "total",
                "chosen_source": "llm",
                "di_value": None,
                "llm_value": "10.00",
                "agreed": False,
            }
        },
    }
    enriched = attach_field_resolution_telemetry(parsed, detail)
    telemetry_detail = detail_from_parsed_telemetry(enriched)
    assert telemetry_detail is not None
    assert telemetry_detail["fields"]["total"]["chosen_source"] == "llm"
