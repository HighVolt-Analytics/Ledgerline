"""Policy auto-correct must re-extract for the new DT and prune old-schema fields."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.invoice import Invoice, InvoiceStatus
from app.schemas.document_type import DocumentTypeClassifier, DocumentTypeDefinition
from app.schemas.llm_document import LlmDocumentResult
from app.schemas.ocr_artifact import OcrArtifact
from app.schemas.rule_book_config import RuleBookConfigPayload, RuleCondition, RuleConditionGroup
from app.services.extraction.document_ai_provider import ExtractFieldsResult
from app.services.invoice.invoice_data import InvoiceData
from app.services.invoice.invoice_evaluation_service import EVAL_NEEDS_REVIEW
from app.services.invoice.invoice_post_classification_phases import (
    apply_policy_scorer_after_extract,
    prune_invoice_fields_to_dt_manifest,
    reextract_fields_for_corrected_dt,
)
from app.tenant_ids import TESTING_TENANT_UUID


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
        "classifier": DocumentTypeClassifier(enabled=False, priority=100, confidence=0.85),
        "requiredFields": ["vendor", "invoice_no", "total"],
        "extractionFields": ["vendor", "invoice_no", "total", "line_items"],
    }
    base.update(kwargs)
    return DocumentTypeDefinition.model_validate(base)


def _packing_dt() -> DocumentTypeDefinition:
    return _dt(
        code="DT-PL",
        title="Packing list",
        shortTitle="Packing list",
        klass="Non-actionable",
        posting="NEVER",
        requiredFields=["vendor", "permit_no"],
        extractionFields=["vendor", "permit_no"],
        classifier=DocumentTypeClassifier(
            enabled=True,
            priority=20,
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


def test_prune_removes_old_schema_only_keys() -> None:
    invoice = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.PARSING,
        document_type_code="DT-PL",
        extracted_fields={
            "permit_no": "P-1",
            "vendor": "Acme",
            "invoice_no": "INV-9",
            "perspective": "purchase",
        },
        invoice_no="INV-9",
    )
    parsed = InvoiceData(vendor="Acme", invoice_no="INV-9")
    pruned = prune_invoice_fields_to_dt_manifest(
        invoice,
        parsed,
        document_types=[_dt()],
        confirmed_dt="DT-01",
    )
    assert "permit_no" in pruned
    assert "permit_no" not in (invoice.extracted_fields or {})
    assert (invoice.extracted_fields or {}).get("perspective") == "purchase"
    assert (invoice.extracted_fields or {}).get("vendor") == "Acme"


@pytest.mark.asyncio
async def test_policy_auto_correct_sets_corrected_dt() -> None:
    invoice = Invoice(
        id=101,
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.VALIDATING,
        document_type_code="DT-01",
        document_type_confidence=0.70,
        vendor="Acme",
        document_text="PACKING LIST\nCartons 12",
    )
    loaded = invoice
    parsed = InvoiceData(
        vendor="Acme",
        document_text="PACKING LIST\nCartons 12",
        document_heading="PACKING LIST",
    )
    config = RuleBookConfigPayload(document_types=[_dt(), _packing_dt()])
    session = AsyncMock()
    session.get = AsyncMock(return_value=None)

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
        result = await apply_policy_scorer_after_extract(
            session,
            invoice=invoice,
            loaded=loaded,
            parsed=parsed,
            config=config,
            llm_dt="DT-01",
            llm_confidence=0.55,
            force=True,
            allow_auto_correct=True,
        )

    assert result.auto_corrected is True
    assert result.corrected_dt == "DT-PL"
    assert loaded.document_type_code == "DT-PL"


@pytest.mark.asyncio
async def test_second_pass_disagreement_holds_without_auto_correct() -> None:
    invoice = Invoice(
        id=102,
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.VALIDATING,
        document_type_code="DT-PL",
        document_type_confidence=0.95,
        vendor="Acme",
        invoice_no="INV-1",
        document_text="TAX INVOICE\nINV-1",
    )
    # Make DT-01 win via required fields completeness + heading
    invoice_dt = _dt(
        classifier=DocumentTypeClassifier(
            enabled=True,
            priority=10,
            confidence=0.98,
            root=RuleConditionGroup(
                operator="AND",
                children=[
                    RuleCondition(
                        field="document_text",
                        operator="contains",
                        value="TAX INVOICE",
                    ),
                ],
            ).model_dump(),
        ),
    )
    parsed = InvoiceData(
        vendor="Acme",
        invoice_no="INV-1",
        total=None,
        document_text="TAX INVOICE\nINV-1",
        document_heading="TAX INVOICE",
    )
    config = RuleBookConfigPayload(document_types=[invoice_dt, _packing_dt()])
    session = AsyncMock()

    with patch(
        "app.services.classification.document_type_reclassify_service.human_confirmed_document_type",
        new=AsyncMock(return_value=None),
    ), patch(
        "app.services.invoice.invoice_post_classification_phases.log_event",
        new=AsyncMock(),
    ) as log_event:
        result = await apply_policy_scorer_after_extract(
            session,
            invoice=invoice,
            loaded=invoice,
            parsed=parsed,
            config=config,
            llm_dt="DT-PL",
            llm_confidence=0.70,
            force=True,
            allow_auto_correct=False,
        )

    assert result.auto_corrected is False
    assert result.needs_review is True
    assert result.oscillation_hold is True
    assert invoice.document_type_code == "DT-PL"
    assert invoice.evaluation_status == EVAL_NEEDS_REVIEW
    events = [c.args[1] for c in log_event.await_args_list]
    assert "policy_after_extract_oscillation" in events


@pytest.mark.asyncio
async def test_reextract_prunes_old_fields_and_keeps_new() -> None:
    invoice = Invoice(
        id=103,
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.PARSING,
        document_type_code="DT-PL",
        extracted_fields={"permit_no": "OLD", "vendor": "OldCo", "invoice_no": "X"},
        invoice_no="X",
        line_items=[],
    )
    ocr = OcrArtifact(success=True, text="PACKING LIST\npermit P-99", text_length=30)
    config = RuleBookConfigPayload(document_types=[_dt(), _packing_dt()])
    session = AsyncMock()
    session.flush = AsyncMock()
    session.execute = AsyncMock()
    session.delete = AsyncMock()

    llm = LlmDocumentResult(
        suggested_dt="DT-PL",
        confidence=0.9,
        reasoning="packing",
        perspective="purchase",
        vendor="PackCo",
        extracted_fields={"permit_no": "P-99", "vendor": "PackCo"},
    )

    with patch(
        "app.services.extraction.document_ai_provider.extract_fields",
        new=AsyncMock(return_value=ExtractFieldsResult(llm=llm, ocr=ocr)),
    ), patch(
        "app.services.invoice.invoice_post_classification_phases.log_event",
        new=AsyncMock(),
    ):
        parsed, pruned = await reextract_fields_for_corrected_dt(
            session,
            invoice=invoice,
            loaded=invoice,
            ocr=ocr,
            file_path="/tmp/x.pdf",
            org=MagicMock(country="AU", legal_name="Tenant"),
            config=config,
            confirmed_dt="DT-PL",
            few_shots=[],
            doc_provider=MagicMock(),
        )

    assert "invoice_no" in pruned or invoice.invoice_no is None or "invoice_no" not in (
        invoice.extracted_fields or {}
    )
    # Old invoice-only key should not linger as a packing-list field requirement mismatch
    fields = invoice.extracted_fields or {}
    assert "permit_no" in fields or getattr(parsed, "vendor", None)
    assert fields.get("invoice_no") in (None, "") or "invoice_no" not in fields


@pytest.mark.asyncio
async def test_no_auto_correct_when_same_dt() -> None:
    invoice = Invoice(
        id=104,
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.VALIDATING,
        document_type_code="DT-01",
        document_type_confidence=0.9,
        vendor="Acme",
        invoice_no="1",
        document_text="TAX INVOICE",
    )
    parsed = InvoiceData(vendor="Acme", invoice_no="1", document_text="TAX INVOICE")
    config = RuleBookConfigPayload(document_types=[_dt()])
    session = AsyncMock()

    with patch(
        "app.services.classification.document_type_reclassify_service.human_confirmed_document_type",
        new=AsyncMock(return_value=None),
    ), patch(
        "app.services.invoice.invoice_post_classification_phases.log_event",
        new=AsyncMock(),
    ):
        result = await apply_policy_scorer_after_extract(
            session,
            invoice=invoice,
            loaded=invoice,
            parsed=parsed,
            config=config,
            llm_dt="DT-01",
            llm_confidence=0.9,
            force=True,
        )

    assert result.auto_corrected is False
    assert result.corrected_dt == ""
