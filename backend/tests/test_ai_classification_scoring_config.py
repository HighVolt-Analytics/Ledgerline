"""Configurable DT scoring weights and policy gaps on AiClassificationConfig."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.models.invoice import Invoice, InvoiceStatus
from app.schemas.document_type import DocumentTypeClassifier, DocumentTypeDefinition
from app.schemas.rule_book_config import AiClassificationConfig, RuleBookConfigPayload
from app.services.classification.document_type_scoring_service import (
    DocumentTypeScoreWeights,
    compute_document_type_confidence,
    score_weights_from_ai_config,
)
from app.services.invoice.invoice_data import InvoiceData
from app.services.invoice.invoice_post_classification_phases import apply_policy_scorer_after_extract
from app.tenant_ids import TESTING_TENANT_UUID


def test_score_weights_defaults_match_hardcoded() -> None:
    weights = score_weights_from_ai_config(AiClassificationConfig())
    assert weights.rule == pytest.approx(0.45)
    assert weights.fields == pytest.approx(0.30)
    assert weights.parse == pytest.approx(0.15)
    assert weights.heading == pytest.approx(0.10)
    assert weights.parse_fallback == pytest.approx(0.6)
    assert weights.heading_catalogue_match_min == pytest.approx(0.82)


def test_custom_heading_weight_changes_blended_confidence() -> None:
    baseline = compute_document_type_confidence(
        rule_strength=0.5,
        field_completeness=0.5,
        parse_confidence=None,
        heading_alignment=1.0,
        parse_score=0.6,
        weights=DocumentTypeScoreWeights(),
    )
    heavy_heading = compute_document_type_confidence(
        rule_strength=0.5,
        field_completeness=0.5,
        parse_confidence=None,
        heading_alignment=1.0,
        parse_score=0.6,
        weights=DocumentTypeScoreWeights(heading=0.5, rule=0.2, fields=0.2, parse=0.1),
    )
    assert heavy_heading > baseline


@pytest.mark.asyncio
async def test_custom_auto_correct_gap_controls_fire() -> None:
    invoice = Invoice(
        id=701,
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.VALIDATING,
        document_type_code="DT-01",
        document_type_confidence=0.70,
        vendor="Acme",
        document_text="PACKING LIST",
    )
    packing = DocumentTypeDefinition.model_validate(
        {
            "code": "DT-PL",
            "title": "Packing list",
            "shortTitle": "Packing list",
            "klass": "Non-actionable",
            "posting": "NEVER",
            "recognition_mode": "signals",
            "recognition_signals": [],
            "llm_prompt": "",
            "routeTarget": "Vault",
            "enabled": True,
            "extractionFields": ["vendor"],
            "classifier": DocumentTypeClassifier(
                enabled=True,
                priority=10,
                confidence=0.95,
                root={
                    "type": "group",
                    "operator": "AND",
                    "children": [
                        {
                            "type": "condition",
                            "field": "document_text",
                            "operator": "contains",
                            "value": "PACKING LIST",
                        }
                    ],
                },
            ),
        }
    )
    invoice_dt = DocumentTypeDefinition.model_validate(
        {
            "code": "DT-01",
            "title": "Invoice",
            "shortTitle": "Invoice",
            "klass": "Transactional",
            "posting": "Yes",
            "recognition_mode": "signals",
            "recognition_signals": ["heading_invoice"],
            "llm_prompt": "",
            "routeTarget": "Purchase Management",
            "enabled": True,
            "extractionFields": ["vendor", "invoice_no"],
            "classifier": DocumentTypeClassifier(enabled=False),
        }
    )
    parsed = InvoiceData(vendor="Acme", document_text="PACKING LIST", document_heading="PACKING LIST")
    config = RuleBookConfigPayload(document_types=[invoice_dt, packing])
    session = AsyncMock()

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
        # Gap small with default 0.12 → no auto-correct
        no_flip = await apply_policy_scorer_after_extract(
            session,
            invoice=invoice,
            loaded=invoice,
            parsed=parsed,
            config=config,
            llm_dt="DT-01",
            llm_confidence=0.88,
            force=True,
            auto_correct_gap=0.12,
            review_gap=0.05,
        )
        assert no_flip.auto_corrected is False

        invoice.document_type_code = "DT-01"
        invoice.document_type_confidence = 0.88
        # Lower gap → auto-correct fires for same confidence pair
        flipped = await apply_policy_scorer_after_extract(
            session,
            invoice=invoice,
            loaded=invoice,
            parsed=parsed,
            config=config,
            llm_dt="DT-01",
            llm_confidence=0.88,
            force=True,
            auto_correct_gap=0.01,
            review_gap=0.005,
        )
        assert flipped.auto_corrected is True
        assert flipped.corrected_dt == "DT-PL"
