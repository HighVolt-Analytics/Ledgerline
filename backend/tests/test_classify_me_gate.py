"""Classify-me gate and document AI provider tests."""

from __future__ import annotations

from contextlib import contextmanager

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import Invoice, InvoiceStatus
from app.schemas.classification_decision import PolicyScoreResult
from app.schemas.document_type import DocumentTypeDefinition
from app.schemas.llm_document import LlmDocumentResult, LlmParty
from app.schemas.ocr_artifact import OcrArtifact
from app.services.classification.classification_compare_service import compare_classification
from app.services.invoice.invoice_data import InvoiceData
from app.services.invoice.invoice_evaluation_service import EVAL_AWAITING_CLASSIFICATION
from app.services.invoice.pipeline import process_invoice
from tests.pipeline_test_helpers import patch_confidence_gate_pass
from app.services.tenant.tenant_org_context import OrgContext
from app.tenant_ids import TESTING_TENANT_UUID


def _dt03() -> DocumentTypeDefinition:
    return DocumentTypeDefinition.model_validate(
        {
            "code": "DT-03",
            "title": "Tax Invoice",
            "shortTitle": "Tax Inv",
            "klass": "Transactional",
            "posting": "Yes",
            "recognition_mode": "signals", "recognition_signals": ["heading_invoice"], "llm_prompt": "Tax invoice",
            "routeTarget": "Purchase Management",
            "enabled": True,
            "requiredFields": ["vendor", "invoice_no", "total"],
            "extractionFields": ["vendor", "invoice_no", "total"],
            "classifier": {
                "enabled": True,
                "priority": 10,
                "confidence": 0.65,
                "root": {"type": "group", "operator": "AND", "children": []},
            },
        }
    )


def _ocr() -> OcrArtifact:
    text = "TAX INVOICE from Acme Pty Ltd ABN 12 345 678 901 invoice #INV-001 total $120.00 GST included"
    return OcrArtifact(
        success=True,
        sparse=False,
        text=text,
        text_length=len(text),
        di_model="prebuilt-layout",
    )


@pytest.mark.asyncio
async def test_classify_gate_blocks_extraction(
    db_session: AsyncSession,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pdf_path = tmp_path / "invoice.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 minimal")

    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.PENDING,
        raw_file_path=str(pdf_path),
        file_hash="gate-low-conf",
        currency="AUD",
    )
    db_session.add(inv)
    await db_session.flush()

    ocr = _ocr()

    @contextmanager
    def _fake_open(path: str, **_kwargs):
        yield path

    async def _fake_read(*_args, **_kwargs) -> OcrArtifact:
        return ocr

    async def _fake_classify(*_args, **_kwargs) -> LlmDocumentResult:
        return LlmDocumentResult(
            suggested_dt="DT-03",
            confidence=0.51,
            reasoning="Uncertain invoice",
            perspective="purchase",
            seller=LlmParty(name="Acme Pty Ltd"),
        )

    async def _fake_extract(*_args, **_kwargs) -> LlmDocumentResult:
        raise AssertionError("extract_fields must not run when classify gate fails")

    monkeypatch.setattr("app.services.pipeline.open_pdf_for_reading", _fake_open)
    monkeypatch.setattr("app.services.invoice_pipeline_phases.open_pdf_for_reading", _fake_open)
    monkeypatch.setattr(
        "app.services.invoice_pipeline_phases.read_for_classification",
        _fake_read,
    )
    monkeypatch.setattr(
        "app.services.invoice_pipeline_phases.classify_only",
        _fake_classify,
    )
    monkeypatch.setattr("app.services.pipeline.extract_fields", _fake_extract)

    await process_invoice(db_session, inv)
    await db_session.flush()

    assert inv.status == InvoiceStatus.EXCEPTION
    assert inv.evaluation_status == EVAL_AWAITING_CLASSIFICATION
    assert inv.vendor is None
    assert inv.total is None
    assert inv.llm_confidence == pytest.approx(0.51, rel=1e-3)


@pytest.mark.asyncio
async def test_classify_gate_85_passes_to_extract(
    db_session: AsyncSession,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pdf_path = tmp_path / "invoice.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 minimal")

    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.PENDING,
        raw_file_path=str(pdf_path),
        file_hash="gate-high-conf",
        currency="AUD",
    )
    db_session.add(inv)
    await db_session.flush()

    ocr = _ocr()
    extract_called = {"value": False}

    @contextmanager
    def _fake_open(path: str, **_kwargs):
        yield path

    async def _fake_read(*_args, **_kwargs) -> OcrArtifact:
        return ocr

    async def _fake_classify(*_args, **_kwargs) -> LlmDocumentResult:
        return LlmDocumentResult(
            suggested_dt="DT-03",
            confidence=0.9,
            reasoning="Clear tax invoice",
            perspective="purchase",
            seller=LlmParty(name="Acme Pty Ltd"),
        )

    async def _fake_extract(*_args, **_kwargs) -> LlmDocumentResult:
        extract_called["value"] = True
        return LlmDocumentResult(
            suggested_dt="DT-03",
            confidence=0.9,
            perspective="purchase",
            vendor="Acme Pty Ltd",
            total="120.00",
            seller=LlmParty(name="Acme Pty Ltd"),
        )

    async def _noop_sync(*_args, **_kwargs) -> None:
        return None

    patch_confidence_gate_pass(monkeypatch)
    monkeypatch.setattr("app.services.pipeline.open_pdf_for_reading", _fake_open)
    monkeypatch.setattr("app.services.invoice_pipeline_phases.open_pdf_for_reading", _fake_open)
    monkeypatch.setattr(
        "app.services.invoice_pipeline_phases.read_for_classification",
        _fake_read,
    )
    monkeypatch.setattr(
        "app.services.invoice_pipeline_phases.classify_only",
        _fake_classify,
    )
    monkeypatch.setattr("app.services.pipeline.extract_fields", _fake_extract)
    monkeypatch.setattr("app.services.pipeline.sync_invoice_blob_path", _noop_sync)

    await process_invoice(db_session, inv)
    await db_session.flush()

    assert extract_called["value"] is True
    assert inv.vendor == "Acme Pty Ltd"
    assert inv.llm_suggested_dt == "DT-03"


def test_compare_skips_extraction_gap_pre_extract() -> None:
    inv = Invoice(id=1, tenant_id=TESTING_TENANT_UUID, status=InvoiceStatus.PARSING)
    parsed = InvoiceData(document_text="heading only")
    llm = LlmDocumentResult(
        suggested_dt="DT-03",
        confidence=0.92,
        perspective="purchase",
        seller=LlmParty(name="Acme"),
    )
    policy = PolicyScoreResult(winner_dt="DT-03", winner_confidence=0.9, scores=[])
    org = OrgContext(legal_name="Tenant Co")

    decision = compare_classification(
        llm=llm,
        policy=policy,
        invoice=inv,
        parsed=parsed,
        document_types=[_dt03()],
        org=org,
        auto_route_min_confidence=0.85,
        pre_extract=True,
    )
    assert decision.auto_eligible is True
    assert "EXTRACTION_GAP" not in [r.value for r in decision.review_reasons]


@pytest.mark.asyncio
async def test_gemini_provider_classify_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.extraction.document_ai_provider import DocumentAiProvider, classify_only

    ocr = OcrArtifact(
        success=True,
        sparse=False,
        text="Invoice heading",
        text_length=15,
        di_model="gemini-2.5-flash",
        payload_json={
            "provider": "gemini_vision",
            "classify_hint": {
                "suggested_dt": "DT-03",
                "confidence": 0.4,
                "reasoning": "Low confidence",
                "perspective": "purchase",
            },
        },
    )

    async def _fake_gemini_classify(*_args, **_kwargs) -> LlmDocumentResult:
        return LlmDocumentResult(suggested_dt="DT-03", confidence=0.4, perspective="purchase")

    monkeypatch.setattr(
        "app.services.document_ai_provider.classify_only_gemini",
        _fake_gemini_classify,
    )

    result = await classify_only(
        ocr,
        file_path="/tmp/invoice.pdf",
        org=OrgContext(),
        document_types=[_dt03()],
        few_shots=[],
        provider=DocumentAiProvider.GEMINI_VISION,
    )
    assert result is not None
    assert result.suggested_dt == "DT-03"
    assert result.confidence == pytest.approx(0.4)


def _custom_grn_dt() -> DocumentTypeDefinition:
    return DocumentTypeDefinition.model_validate(
        {
            "code": "DT-99",
            "title": "Custom GRN",
            "shortTitle": "GRN",
            "klass": "Non-transactional",
            "posting": "No",
            "recognition_mode": "signals", "recognition_signals": ["heading_grn"], "llm_prompt": "GRN only",
            "routeTarget": "Vault",
            "enabled": True,
            "minRouteConfidence": 0.75,
            "classifier": {
                "enabled": True,
                "priority": 100,
                "confidence": 0.85,
                "root": {
                    "type": "group",
                    "operator": "OR",
                    "children": [
                        {
                            "type": "condition",
                            "field": "document_text",
                            "operator": "contains",
                            "value": "GRN",
                        },
                    ],
                },
            },
        }
    )


def _bank_statement_ocr() -> OcrArtifact:
    text = (
        "BANK STATEMENT summary only — not a GRN document for classifier mismatch "
        "test padding length sufficient for quality gate"
    )
    return OcrArtifact(
        success=True,
        sparse=False,
        text=text,
        text_length=len(text),
        di_model="prebuilt-layout",
    )


@pytest.mark.asyncio
async def test_custom_type_classifier_mismatch_blocks_auto_route(
    db_session: AsyncSession,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.schemas.rule_book_config import RuleBookConfigPayload
    from app.services.invoice.invoice_evaluation_service import load_config_for_tenant

    base_config = await load_config_for_tenant(db_session, TESTING_TENANT_UUID)
    custom = _custom_grn_dt()
    merged_types = [
        *(dt for dt in base_config.document_types if dt.code != "DT-99"),
        custom,
    ]
    config = RuleBookConfigPayload.model_validate(
        {
            **base_config.model_dump(by_alias=True),
            "documentTypes": [dt.model_dump(by_alias=True) for dt in merged_types],
        }
    )

    async def _fake_load_config(_session, _tenant_id):
        return config

    pdf_path = tmp_path / "invoice.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 minimal")

    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.PENDING,
        raw_file_path=str(pdf_path),
        file_hash="classifier-mismatch",
        currency="AUD",
    )
    db_session.add(inv)
    await db_session.flush()

    ocr = _bank_statement_ocr()

    @contextmanager
    def _fake_open(path: str, **_kwargs):
        yield path

    async def _fake_read(*_args, **_kwargs) -> OcrArtifact:
        return ocr

    async def _fake_classify(*_args, **_kwargs) -> LlmDocumentResult:
        return LlmDocumentResult(
            suggested_dt="DT-99",
            confidence=0.92,
            reasoning="Looks like custom type",
            perspective="purchase",
            seller=LlmParty(name="Acme"),
        )

    async def _fake_extract(*_args, **_kwargs) -> LlmDocumentResult:
        raise AssertionError("extract must not run when classifier gate fails")

    monkeypatch.setattr("app.services.pipeline.load_config_for_tenant", _fake_load_config)
    monkeypatch.setattr("app.services.pipeline.open_pdf_for_reading", _fake_open)
    monkeypatch.setattr("app.services.invoice_pipeline_phases.open_pdf_for_reading", _fake_open)
    monkeypatch.setattr(
        "app.services.invoice_pipeline_phases.read_for_classification",
        _fake_read,
    )
    monkeypatch.setattr(
        "app.services.invoice_pipeline_phases.classify_only",
        _fake_classify,
    )
    monkeypatch.setattr("app.services.pipeline.extract_fields", _fake_extract)

    await process_invoice(db_session, inv)
    await db_session.flush()

    assert inv.evaluation_status == EVAL_AWAITING_CLASSIFICATION
    assert inv.status == InvoiceStatus.EXCEPTION
    assert inv.document_type_code is None


@pytest.mark.asyncio
async def test_gemini_ocr_read_does_not_classify(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    from app.services.extraction.gemini_vision_client import read_for_classification_gemini

    pdf_path = tmp_path / "invoice.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 minimal")

    async def _fake_generate(*, system: str, user_parts, timeout_seconds: int):
        assert "classify" not in system.lower()
        assert "suggested_dt" not in system
        assert "12000" in system
        return {
            "document_heading": "Tax Invoice",
            "text_excerpt": "Tax Invoice from Acme",
        }

    monkeypatch.setattr(
        "app.services.extraction.gemini_vision_client._generate_json",
        _fake_generate,
    )
    monkeypatch.setattr(
        "app.services.extraction.gemini_vision_client.pdf_page_images",
        lambda *_args, **_kwargs: [b"fake-png"],
    )

    ocr = await read_for_classification_gemini(
        pdf_path,
        org=OrgContext(),
        document_types=[_dt03()],
    )
    assert ocr.payload_json.get("document_heading") == "Tax Invoice"
    assert "classify_hint" not in ocr.payload_json


def test_ai_provider_rule_book_roundtrip() -> None:
    from app.schemas.rule_book_config import AiClassificationConfig, RuleBookConfigPayload

    cfg = RuleBookConfigPayload.model_validate(
        {
            "schema_version": 1,
            "aiClassification": {
                "documentAiProvider": "gemini_vision",
                "autoRouteMinConfidence": 0.88,
            },
            "document_types": [],
        }
    )
    assert cfg.ai_classification is not None
    assert cfg.ai_classification.document_ai_provider == "gemini_vision"
    assert cfg.ai_classification.auto_route_min_confidence == pytest.approx(0.88)

    default_cfg = AiClassificationConfig()
    assert default_cfg.document_ai_provider in {"azure_di", "azure_foundry_vision"}
    assert default_cfg.auto_route_min_confidence == pytest.approx(0.85)


def test_confidence_gate_uses_higher_org_and_dt_thresholds() -> None:
    from app.schemas.rule_book_config import AiClassificationConfig
    from app.schemas.llm_document import LlmDocumentResult, LlmParty
    from app.services.invoice.invoice_pipeline_phases import evaluate_confidence_gate, gate_audit_detail

    dt = _dt03()
    dt = dt.model_copy(update={"min_route_confidence": 0.65})
    ai_cfg = AiClassificationConfig(auto_route_min_confidence=0.85)

    result = evaluate_confidence_gate(
        LlmDocumentResult(
            suggested_dt="DT-03",
            confidence=0.846,
            reasoning="Borderline",
            perspective="purchase",
            seller=LlmParty(name="Acme"),
        ),
        document_types=[dt],
        ai_cfg=ai_cfg,
        provider_token="azure_di",
    )

    assert result.passed is False
    assert result.min_route_confidence == pytest.approx(0.85)
    assert result.org_auto_route_min_confidence == pytest.approx(0.85)
    assert result.dt_min_route_confidence == pytest.approx(0.65)
    assert "LLM_LOW_CONF" in result.review_reasons

    detail = gate_audit_detail(result, provider_token="azure_di")
    assert detail["org_auto_route_min_confidence"] == pytest.approx(0.85)
    assert detail["dt_min_route_confidence"] == pytest.approx(0.65)
    assert detail["compare_passed"] is False
