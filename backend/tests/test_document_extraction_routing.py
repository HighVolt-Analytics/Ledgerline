"""Tests for multi-document extraction routing and strategies."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.schemas.document_type import DocumentTypeDefinition
from app.schemas.finance_document import FinanceDocumentNormalized
from app.schemas.ocr_artifact import OcrArtifact
from app.services.extraction.finance_document_adapters import (
    finance_document_from_invoice_data,
    invoice_data_from_finance_document,
)
from app.services.extraction.line_items_parser import (
    merge_line_items_gap_fill_only,
    resolve_line_items_for_strategy,
)
from app.services.extraction.routing import (
    get_extraction_strategy,
    route_document_for_extraction,
)
from app.services.extraction.routing.decision import DocumentRouteDecision
from app.services.extraction.routing.routes import ExtractionRoute as ER
from app.services.invoice.invoice_data import InvoiceData, ParsedLineItem


def _dt(
    code: str,
    *,
    playbook: str = "",
    purchase_role: str = "",
    sales_role: str = "",
    title: str | None = None,
) -> DocumentTypeDefinition:
    payload: dict = {
        "code": code,
        "title": title or code,
        "shortTitle": title or code,
        "klass": "Transactional",
        "posting": "Yes",
        "recognitionMode": "prompt",
        "llmPrompt": "test",
        "routeTarget": "Purchase Management",
        "enabled": True,
    }
    if playbook:
        payload["playbookProfile"] = playbook
    if purchase_role:
        payload["purchaseBundleRole"] = purchase_role
    if sales_role:
        payload["salesBundleRole"] = sales_role
    return DocumentTypeDefinition.model_validate(payload)


def test_org_playbook_drives_route_not_dt_code() -> None:
    # Same code DT-99, different org playbooks → different routes
    assert (
        route_document_for_extraction(
            "DT-99", _dt("DT-99", playbook="standard_transactional", title="Any Invoice")
        ).route
        == ER.INVOICE
    )
    assert (
        route_document_for_extraction(
            "DT-99", _dt("DT-99", playbook="credit_adjustment", title="Credit")
        ).route
        == ER.CREDIT_NOTE
    )
    assert (
        route_document_for_extraction(
            "DT-99", _dt("DT-99", playbook="debit_note", title="Debit")
        ).route
        == ER.DEBIT_NOTE
    )
    assert (
        route_document_for_extraction(
            "DT-99", _dt("DT-99", playbook="reconciliation", title="Statement")
        ).route
        == ER.STATEMENT
    )
    assert (
        route_document_for_extraction(
            "DT-99", _dt("DT-99", playbook="employee_claim", title="Claim")
        ).route
        == ER.EXPENSE_CLAIM
    )
    assert route_document_for_extraction("", None).route == ER.UNKNOWN


def test_repurposed_dt_code_follows_org_playbook_not_shipped_matrix() -> None:
    # Shipped DT-13 is statement/reconciliation; org repurposes to packing list
    decision = route_document_for_extraction(
        "DT-13",
        _dt("DT-13", playbook="supporting", title="PACKING LIST"),
    )
    assert decision.route == ER.SUPPORTING_DOCUMENT
    assert not decision.uses_invoice_model


def test_po_grn_bundle_roles_override_playbook() -> None:
    po = route_document_for_extraction(
        "DT-99",
        _dt("DT-99", playbook="standard_transactional", purchase_role="po", title="PO"),
    )
    assert po.route == ER.PURCHASE_ORDER
    assert not po.uses_invoice_model

    grn = route_document_for_extraction(
        "DT-99",
        _dt("DT-99", playbook="supporting", purchase_role="grn", title="GRN"),
    )
    assert grn.route == ER.GRN
    assert not grn.uses_invoice_model


def test_supporting_playbook_overrides_invoice_shaped_code() -> None:
    decision = route_document_for_extraction(
        "DT-01",
        _dt("DT-01", playbook="supporting", title="Supporting copy"),
    )
    assert decision.route == ER.SUPPORTING_DOCUMENT
    assert not decision.uses_invoice_model


def test_expense_claim_allows_invoice_model_from_playbook() -> None:
    decision = route_document_for_extraction(
        "DT-12",
        _dt("DT-12", playbook="employee_claim", title="Employee claim"),
    )
    assert decision.route == ER.EXPENSE_CLAIM
    assert decision.allow_invoice_model is True
    assert decision.uses_invoice_model is True


def test_should_run_prebuilt_invoice_di_wrapper() -> None:
    from app.services.extraction.extraction_orchestrator import should_run_prebuilt_invoice_di

    assert (
        should_run_prebuilt_invoice_di(
            "DT-01", _dt("DT-01", playbook="po_goods", title="PO goods invoice")
        )
        is True
    )
    assert (
        should_run_prebuilt_invoice_di(
            "DT-03", _dt("DT-03", purchase_role="grn", title="GRN")
        )
        is False
    )
    assert (
        should_run_prebuilt_invoice_di(
            "DT-13", _dt("DT-13", playbook="reconciliation", title="Vendor statement")
        )
        is False
    )


def test_invoice_strategy_runs_even_when_layout_line_items_present(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AZURE_DI_ENDPOINT", "https://test.cognitiveservices.azure.com")
    monkeypatch.setenv("AZURE_DI_KEY", "fake-key")
    from app.config import get_settings

    get_settings.cache_clear()

    pdf = tmp_path / "inv.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")

    ocr = OcrArtifact(
        success=True,
        text="TAX INVOICE Vendor Acme Total 100",
        text_length=40,
        di_model="prebuilt-layout",
        payload_json={
            "table_line_items": [
                {"description": "Invoice Date", "qty": None, "amount": None, "unit_price": None},
                {
                    "description": "Widget",
                    "qty": "1",
                    "amount": "100.00",
                    "unit_price": "100.00",
                },
            ],
            "di_model": "prebuilt-layout",
        },
    )

    called: dict[str, object] = {}

    def fake_parse(path, content_type="application/pdf", model_id_override=None):
        called["ran"] = True
        data = InvoiceData(
            vendor="Acme",
            invoice_no="INV-1",
            total=Decimal("100"),
            line_items=[
                ParsedLineItem(
                    description="Widget",
                    qty=Decimal("1"),
                    amount=Decimal("100"),
                    source="di",
                )
            ],
            raw_fields={
                "di_scalar_sources": {"vendor": "VendorName", "total": "InvoiceTotal"},
                "field_confidence": {"vendor": 0.9, "total": 0.95},
                "field_sources": {"vendor": "semantic_di", "total": "semantic_di"},
            },
            extracted_fields={"seller_name": "Acme"},
        )
        return data, {"content": "TAX INVOICE"}, "success"

    monkeypatch.setattr(
        "app.services.extraction.di_raw_persist.parse_invoice_with_raw",
        fake_parse,
    )

    from app.services.extraction.di_extract_service import enrich_ocr_for_route

    defn = _dt("DT-01", playbook="po_goods", title="Tax Invoice")
    decision = route_document_for_extraction("DT-01", defn)
    enriched, audit = enrich_ocr_for_route(
        ocr, pdf, confirmed_dt="DT-01", dt_definition=defn, decision=decision
    )

    assert called.get("ran") is True
    assert audit.get("failure_reason") != "skipped_existing_line_items"
    assert enriched.payload_json.get("invoice_fields")
    assert enriched.payload_json.get("extraction_route") == "invoice"
    assert "di_line_items" in enriched.payload_json
    get_settings.cache_clear()


def test_grn_strategy_does_not_call_invoice_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AZURE_DI_ENDPOINT", "https://test.cognitiveservices.azure.com")
    monkeypatch.setenv("AZURE_DI_KEY", "fake-key")
    from app.config import get_settings

    get_settings.cache_clear()

    pdf = tmp_path / "grn.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    ocr = OcrArtifact(
        success=True,
        text="GOODS RECEIVED NOTE",
        text_length=20,
        di_model="prebuilt-layout",
        payload_json={"table_line_items": [{"description": "Item A", "qty": "2"}]},
    )

    def boom(*_a, **_k):
        raise AssertionError("prebuilt-invoice must not run for GRN")

    monkeypatch.setattr(
        "app.services.extraction.di_raw_persist.parse_invoice_with_raw",
        boom,
    )

    from app.services.extraction.di_extract_service import enrich_ocr_for_route

    defn = _dt("DT-03", purchase_role="grn", title="GRN")
    decision = route_document_for_extraction("DT-03", defn)
    enriched, audit = enrich_ocr_for_route(
        ocr, pdf, confirmed_dt="DT-03", dt_definition=defn, decision=decision
    )
    assert decision.route == ER.GRN
    assert audit.get("skip_reason") == "layout_primary"
    assert audit.get("failure_reason") in (None, "")
    assert enriched.payload_json.get("extraction_route") == "grn"
    assert enriched.payload_json.get("layout_line_mode") == "primary"
    assert enriched.payload_json.get("finance_document")
    assert "field_sources" in enriched.payload_json
    get_settings.cache_clear()


def test_force_invoice_model_runs_prebuilt_invoice_on_layout_primary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AZURE_DI_ENDPOINT", "https://test.cognitiveservices.azure.com")
    monkeypatch.setenv("AZURE_DI_KEY", "fake-key")
    from app.config import get_settings

    get_settings.cache_clear()

    pdf = tmp_path / "grn.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    ocr = OcrArtifact(
        success=True,
        text="GOODS RECEIVED NOTE",
        text_length=20,
        di_model="prebuilt-layout",
        payload_json={"table_line_items": [{"description": "Item A", "qty": "2"}]},
    )
    called: dict[str, object] = {}

    def fake_parse(path, content_type="application/pdf", model_id_override=None):
        called["ran"] = True
        return (
            InvoiceData(vendor="Acme", total=Decimal("100")),
            {"content": "GRN"},
            "success",
        )

    monkeypatch.setattr(
        "app.services.extraction.di_raw_persist.parse_invoice_with_raw",
        fake_parse,
    )

    from app.services.extraction.di_extract_service import enrich_ocr_for_route

    defn = _dt("DT-03", purchase_role="grn", title="GRN")
    decision = route_document_for_extraction("DT-03", defn)
    assert decision.uses_invoice_model is False
    enriched, audit = enrich_ocr_for_route(
        ocr,
        pdf,
        confirmed_dt="DT-03",
        dt_definition=defn,
        decision=decision,
        force_invoice_model=True,
    )
    assert called.get("ran") is True
    assert "force_invoice_model" in (audit.get("route_reasons") or [])
    assert enriched.payload_json.get("invoice_fields")
    get_settings.cache_clear()


def test_gap_fill_does_not_append_unmatched_layout_rows() -> None:
    di = [
        ParsedLineItem(
            description="Consulting",
            qty=Decimal("1"),
            amount=Decimal("100"),
            source="di",
        )
    ]
    layout = [
        ParsedLineItem(description="Invoice Date", source="table"),
        ParsedLineItem(
            description="Consulting",
            qty=Decimal("1"),
            unit_price=Decimal("100"),
            amount=None,
            source="table",
        ),
        ParsedLineItem(description="Mystery junk row", amount=Decimal("9"), source="table"),
    ]
    merged = merge_line_items_gap_fill_only(di, layout)
    descs = [m.description for m in merged]
    assert descs == ["Consulting"]
    assert merged[0].unit_price == Decimal("100")


def test_resolve_line_items_layout_primary_vs_gap_fill() -> None:
    payload = {
        "di_line_items": [
            {
                "description": "DI Item",
                "qty": "1",
                "amount": "50.00",
                "unit_price": "50.00",
            }
        ],
        "table_line_items": [
            {
                "description": "Layout Item",
                "qty": "2",
                "amount": "80.00",
                "unit_price": "40.00",
            }
        ],
    }
    gap = resolve_line_items_for_strategy(payload, layout_mode="gap_fill")
    assert len(gap) == 1
    assert gap[0].description == "DI Item"

    primary = resolve_line_items_for_strategy(payload, layout_mode="primary")
    assert len(primary) == 1
    assert primary[0].description == "Layout Item"

    # Layout-primary must not fall back to DI rows when tables are empty
    di_only = resolve_line_items_for_strategy(
        {"di_line_items": payload["di_line_items"], "table_line_items": []},
        layout_mode="primary",
    )
    assert di_only == []


def test_confidence_metadata_none_when_absent() -> None:
    from app.services.extraction.document_intelligence import _field_confidence

    assert _field_confidence(None) is None
    field = MagicMock()
    field.confidence = None
    assert _field_confidence(field) is None
    field.confidence = 0.87
    assert _field_confidence(field) == pytest.approx(0.87)


def test_unknown_route_review_hints() -> None:
    decision = route_document_for_extraction(
        "DT-99", _dt("DT-99", title="Mysterious doc")
    )
    assert decision.route == ER.UNKNOWN
    assert decision.review_hints


def test_normalized_schema_round_trip_four_routes() -> None:
    invoice_like = {ER.INVOICE, ER.CREDIT_NOTE}
    routes = [
        (ER.INVOICE, "INV-1"),
        (ER.CREDIT_NOTE, "CN-1"),
        (ER.GRN, "GRN-1"),
        (ER.STATEMENT, "STMT-1"),
    ]
    for route, doc_no in routes:
        data = InvoiceData(
            vendor="Vendor Co",
            invoice_no=doc_no,
            total=Decimal("10.00"),
            gst=Decimal("1.00"),
            subtotal=Decimal("9.00"),
            currency="AUD",
            line_items=[
                ParsedLineItem(description="Line", amount=Decimal("9.00"), source="di")
            ],
            extracted_fields={"seller_name": "Vendor Co", "buyer_name": "Buyer"},
            raw_fields={
                "field_confidence": {"total": 0.9},
                "field_sources": {"total": "semantic_di"},
            },
        )
        decision = DocumentRouteDecision(route=route, confirmed_dt="DT-01")
        doc = finance_document_from_invoice_data(
            data, decision=decision, source_model="prebuilt-invoice"
        )
        assert isinstance(doc, FinanceDocumentNormalized)
        assert doc.document_type == route.value
        assert doc.document_number == doc_no
        if route in invoice_like:
            assert doc.tax == Decimal("1.00")
            assert doc.amount_due == Decimal("10.00")
        else:
            assert doc.tax is None
            assert doc.amount_due is None
            assert doc.total == Decimal("10.00")
        back = invoice_data_from_finance_document(doc)
        assert back.invoice_no == doc_no
        if route in invoice_like:
            assert back.gst == Decimal("1.00")
        else:
            assert back.gst is None
        assert back.vendor == "Vendor Co"


def test_strategy_registry_names() -> None:
    assert get_extraction_strategy(ER.INVOICE).config.name == "invoice_family"
    assert get_extraction_strategy(ER.GRN).config.name == "layout_primary"
    assert get_extraction_strategy(ER.UNKNOWN).config.name == "layout_only_review"
    assert get_extraction_strategy(ER.EXPENSE_CLAIM).config.name == "receipt_or_claim"


def test_field_confidence_gate_uses_di_payload() -> None:
    from app.schemas.llm_document import LlmDocumentResult
    from app.schemas.rule_book_config import AiClassificationConfig
    from app.services.invoice.invoice_pipeline_phases import evaluate_field_confidence_gate

    result = evaluate_field_confidence_gate(
        LlmDocumentResult(suggested_dt="DT-01", confidence=0.9, field_confidence={}),
        ai_cfg=AiClassificationConfig(),
        dt_definition=_dt("DT-01", playbook="po_goods", title="Invoice"),
        confirmed_dt="DT-01",
        ocr_payload={"field_confidence": {"total": 0.2, "vendor": 0.9}},
    )
    assert result.passed is False
    assert any(k.startswith("di:") for k in result.low_confidence_fields)


def test_remittance_title_hint_under_supporting_playbook() -> None:
    decision = route_document_for_extraction(
        "DT-18",
        _dt("DT-18", playbook="supporting", title="Remittance Advice"),
    )
    assert decision.route == ER.REMITTANCE


def test_layout_adapter_does_not_revive_raw_unsanitized_table_rows() -> None:
    from app.services.extraction.finance_document_adapters import invoice_data_from_layout_payload

    data = invoice_data_from_layout_payload(
        {
            "layout_line_mode": "gap_fill",
            "table_line_items": [
                {
                    "description": "Ship To: Acme Corp",
                    "qty": "1",
                    "amount": "10.00",
                    "unit_price": "10.00",
                },
                {
                    "description": "Widget",
                    "qty": "2",
                    "amount": "20.00",
                    "unit_price": "10.00",
                },
            ],
        }
    )
    descs = [item.description for item in data.line_items]
    assert "Widget" in descs
    assert not any(d and d.startswith("Ship To:") for d in descs)