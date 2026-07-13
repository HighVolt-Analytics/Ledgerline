"""Combined Part 1+2: title-line heading fill then post-extract policy auto-correct."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.invoice import Invoice, InvoiceStatus
from app.schemas.document_type import DocumentTypeClassifier, DocumentTypeDefinition
from app.schemas.llm_document import LlmDocumentResult
from app.schemas.ocr_artifact import OcrArtifact
from app.schemas.rule_book_config import (
    AiClassificationConfig,
    RuleBookConfigPayload,
    RuleCondition,
    RuleConditionGroup,
)
from app.services.extraction.document_ai_provider import ExtractFieldsResult
from app.services.invoice.invoice_data import InvoiceData
from app.services.invoice.invoice_pipeline_phases import reconcile_llm_dt_with_heading
from app.services.invoice.invoice_post_classification_phases import (
    apply_policy_scorer_after_extract,
    prune_invoice_fields_to_dt_manifest,
    reextract_fields_for_corrected_dt,
)
from app.tenant_ids import TESTING_TENANT_UUID


def _classifier(**kwargs) -> DocumentTypeClassifier:
    base = {"enabled": True, "priority": 50, "confidence": 0.9, "root": {"type": "group", "operator": "AND", "children": []}}
    base.update(kwargs)
    return DocumentTypeClassifier.model_validate(base)


def _dt(**kwargs) -> DocumentTypeDefinition:
    base = {
        "code": "DT-01",
        "title": "Goods invoice",
        "shortTitle": "Invoice",
        "klass": "Transactional",
        "posting": "Yes",
        "recognition_mode": "signals",
        "recognition_signals": ["heading_invoice"],
        "llm_prompt": "",
        "routeTarget": "Purchase Management",
        "enabled": True,
        "classifier": _classifier(enabled=False, priority=100),
        "requiredFields": ["vendor", "invoice_no", "total"],
        "extractionFields": ["vendor", "invoice_no", "total"],
    }
    base.update(kwargs)
    return DocumentTypeDefinition.model_validate(base)


@pytest.mark.asyncio
async def test_heading_title_then_policy_reextract_once() -> None:
    coo = _dt(
        code="DT-26",
        title="Certificate of Origin",
        shortTitle="Certificate of Origin",
        klass="Non-actionable",
        posting="NEVER",
        # Empty signals → heading adopt uses title; policy uses packing's classifier.
        recognition_signals=[],
        playbookProfile="import_dossier",
        requiredFields=[],
        extractionFields=["vendor", "invoice_no"],
        classifier=_classifier(priority=40),
    )
    packing = _dt(
        code="DT-PL",
        title="Packing list",
        shortTitle="Packing list",
        klass="Non-actionable",
        posting="NEVER",
        recognition_signals=[],
        playbookProfile="import_dossier",
        requiredFields=["vendor", "permit_no"],
        extractionFields=["vendor", "permit_no"],
        classifier=_classifier(
            priority=15,
            confidence=0.95,
            root=RuleConditionGroup(
                operator="AND",
                children=[
                    RuleCondition(
                        field="document_text",
                        operator="contains",
                        value="PACKING LIST",
                    ),
                ],
            ).model_dump(),
        ),
    )
    document_types = [coo, packing]
    config = RuleBookConfigPayload(document_types=document_types)

    # Part 2: title-line empty LLM fill → COO
    ocr = OcrArtifact(
        success=True,
        text="CERTIFICATE OF ORIGIN\nPACKING LIST\npermit later",
        text_length=60,
    )
    llm = LlmDocumentResult(
        suggested_dt="",
        confidence=0.4,
        reasoning="",
        perspective="purchase",
        document_heading="CERTIFICATE OF ORIGIN",
    )
    invoice = Invoice(
        id=501,
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.VALIDATING,
        vendor="Acme",
        document_text=ocr.text,
        extracted_fields={"vendor": "Acme", "invoice_no": "COO-1"},
        invoice_no="COO-1",
        line_items=[],
    )
    updated, detail = reconcile_llm_dt_with_heading(
        llm,
        invoice=invoice,
        ocr=ocr,
        document_types=document_types,
        ai_cfg=AiClassificationConfig(auto_route_min_confidence=0.65),
    )
    assert detail is not None
    assert detail["adopted_dt"] == "DT-26"
    assert detail.get("heading_source") == "title_line"
    assert updated is not None
    confirmed_dt = updated.suggested_dt
    assert confirmed_dt == "DT-26"

    # Simulate extract under COO then policy prefers packing list
    invoice.document_type_code = "DT-26"
    invoice.document_type_confidence = 0.55
    parsed = InvoiceData(
        vendor="Acme",
        document_text="CERTIFICATE OF ORIGIN\nPACKING LIST\npermit P-9",
        document_heading="CERTIFICATE OF ORIGIN",
    )
    session = AsyncMock()
    session.flush = AsyncMock()
    session.execute = AsyncMock()
    session.delete = AsyncMock()

    with patch(
        "app.services.classification.document_type_reclassify_service.human_confirmed_document_type",
        new=AsyncMock(return_value=None),
    ), patch(
        "app.services.invoice.invoice_post_classification_phases.apply_invoice_evaluation",
        new=AsyncMock(),
    ), patch(
        "app.services.invoice.invoice_post_classification_phases.log_event",
        new=AsyncMock(),
    ):
        policy1 = await apply_policy_scorer_after_extract(
            session,
            invoice=invoice,
            loaded=invoice,
            parsed=parsed,
            config=config,
            llm_dt="DT-26",
            llm_confidence=0.55,
            force=True,
            allow_auto_correct=True,
        )

    assert policy1.auto_corrected is True
    assert policy1.corrected_dt == "DT-PL"
    confirmed_dt = policy1.corrected_dt

    reextract_llm = LlmDocumentResult(
        suggested_dt="DT-PL",
        confidence=0.9,
        reasoning="packing",
        perspective="purchase",
        vendor="Acme",
        extracted_fields={"permit_no": "P-9", "vendor": "Acme"},
    )
    with patch(
        "app.services.extraction.document_ai_provider.extract_fields",
        new=AsyncMock(return_value=ExtractFieldsResult(llm=reextract_llm, ocr=ocr)),
    ), patch(
        "app.services.invoice.invoice_post_classification_phases.log_event",
        new=AsyncMock(),
    ):
        parsed2, pruned = await reextract_fields_for_corrected_dt(
            session,
            invoice=invoice,
            loaded=invoice,
            ocr=ocr,
            file_path="/tmp/x.pdf",
            org=MagicMock(country="AU", legal_name="T"),
            config=config,
            confirmed_dt=confirmed_dt,
            few_shots=[],
            doc_provider=MagicMock(),
        )

    assert "invoice_no" in pruned or "invoice_no" not in (invoice.extracted_fields or {})
    # Second pass agrees (or no flip) — allow_auto_correct False must not loop
    with patch(
        "app.services.classification.document_type_reclassify_service.human_confirmed_document_type",
        new=AsyncMock(return_value=None),
    ), patch(
        "app.services.invoice.invoice_post_classification_phases.log_event",
        new=AsyncMock(),
    ):
        policy2 = await apply_policy_scorer_after_extract(
            session,
            invoice=invoice,
            loaded=invoice,
            parsed=parsed2,
            config=config,
            llm_dt=confirmed_dt,
            llm_confidence=float(invoice.document_type_confidence or 0.95),
            force=True,
            allow_auto_correct=False,
        )

    assert policy2.auto_corrected is False
    assert policy2.oscillation_hold is False or policy2.policy_winner_dt in ("", "DT-PL")
    # confirmed_dt remains the corrected packing list for downstream
    assert confirmed_dt == "DT-PL"
    _ = prune_invoice_fields_to_dt_manifest(
        invoice,
        parsed2,
        document_types=document_types,
        confirmed_dt=confirmed_dt,
    )
