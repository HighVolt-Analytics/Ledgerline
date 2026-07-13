"""Heading-based classification reconcile for import supporting documents."""

from __future__ import annotations

import pytest

from app.models.invoice import Invoice, InvoiceStatus
from app.schemas.document_type import DocumentTypeClassifier, DocumentTypeDefinition
from app.schemas.llm_document import LlmDocumentResult
from app.schemas.ocr_artifact import OcrArtifact
from app.schemas.rule_book_config import AiClassificationConfig
from app.services.classification.segment_heading_classification import (
    filter_configured_matches_for_heading,
    heading_conflicts_with_definition,
    list_heading_aware_document_type_matches,
)
from app.services.invoice.invoice_data import InvoiceData
from app.services.invoice.invoice_pipeline_phases import reconcile_llm_dt_with_heading
from app.tenant_ids import TESTING_TENANT_UUID


def _classifier(**kwargs) -> DocumentTypeClassifier:
    base = {
        "enabled": True,
        "priority": 50,
        "confidence": 0.88,
        "root": {"type": "group", "operator": "AND", "children": []},
    }
    base.update(kwargs)
    return DocumentTypeClassifier.model_validate(base)


def _dt(**kwargs) -> DocumentTypeDefinition:
    base = {
        "code": "DT-01",
        "title": "PO-based goods invoice",
        "shortTitle": "Goods invoice",
        "klass": "Transactional",
        "posting": "Yes",
        "recognition_mode": "signals",
        "recognition_signals": [],
        "llm_prompt": "",
        "routeTarget": "Purchase Management",
        "enabled": True,
        "playbookProfile": "po_goods",
        "classifier": _classifier(priority=180),
        "requiredFields": ["vendor", "invoice_no", "total", "line_items"],
        "extractionFields": ["vendor", "invoice_no", "total", "line_items"],
    }
    base.update(kwargs)
    return DocumentTypeDefinition.model_validate(base)


def _coo_dt() -> DocumentTypeDefinition:
    return _dt(
        code="DT-26",
        title="Certificate of Origin",
        shortTitle="Certificate of Origin",
        klass="Non-actionable",
        posting="NEVER",
        playbookProfile="supporting",
        validationProfile="non_actionable",
        requiredFields=[],
        extractionFields=["vendor", "invoice_no"],
        classifier=_classifier(priority=65),
    )


def _ccp_dt() -> DocumentTypeDefinition:
    return _dt(
        code="DT-CCP",
        title="Cargo Clearance Permit",
        shortTitle="Cargo Clearance Permit",
        klass="Non-actionable",
        posting="NEVER",
        playbookProfile="supporting",
        validationProfile="non_actionable",
        requiredFields=[],
        extractionFields=["permit_no", "vendor"],
        classifier=_classifier(priority=40),
    )


def _dt02() -> DocumentTypeDefinition:
    return _dt(
        code="DT-02",
        title="PO-based services invoice",
        shortTitle="Services invoice",
        playbookProfile="po_services",
        classifier=_classifier(priority=25),
    )


def test_heading_conflicts_rejects_dt01_for_coo() -> None:
    coo_heading = "certificate_of_origin"
    assert heading_conflicts_with_definition(coo_heading, _dt()) is True
    assert heading_conflicts_with_definition(coo_heading, _coo_dt()) is False


def test_heading_conflicts_rejects_dt02_for_customs_permit() -> None:
    assert heading_conflicts_with_definition("customs_permit", _dt02()) is True
    assert heading_conflicts_with_definition("customs_permit", _ccp_dt()) is False


def test_filter_configured_matches_excludes_transactional_for_coo_heading() -> None:
    invoice = Invoice(tenant_id=TESTING_TENANT_UUID, status=InvoiceStatus.PENDING)
    parsed = InvoiceData(
        document_text="CERTIFICATE OF ORIGIN\nINVOICE NO. 260371344",
        invoice_no="260371344",
    )
    matches = [
        (_dt(), "classifier"),
        (_coo_dt(), "classifier"),
    ]
    filtered = filter_configured_matches_for_heading(
        matches,
        heading_kind="certificate_of_origin",
        invoice=invoice,
        parsed=parsed,
    )
    codes = {row[0].code for row in filtered}
    assert "DT-01" not in codes
    assert "DT-26" in codes


def test_reconcile_heading_adopts_coo_dt() -> None:
    ocr = OcrArtifact(
        success=True,
        text="REPUBLIC OF SINGAPORE CERTIFICATE OF ORIGIN/PROCESSING\nINVOICE NO. 260371344",
        text_length=80,
    )
    llm = LlmDocumentResult(
        suggested_dt="DT-02",
        confidence=0.95,
        reasoning="looked like invoice",
        perspective="purchase",
        document_heading="CERTIFICATE OF ORIGIN",
    )
    invoice = Invoice(tenant_id=TESTING_TENANT_UUID, status=InvoiceStatus.PENDING)
    updated, detail = reconcile_llm_dt_with_heading(
        llm,
        invoice=invoice,
        ocr=ocr,
        document_types=[_dt02(), _coo_dt()],
        ai_cfg=AiClassificationConfig(auto_route_min_confidence=0.65),
    )
    assert detail is not None
    assert detail["adopted_dt"] == "DT-26"
    assert detail["heading_kind"] == "certificate_of_origin"
    assert updated is not None
    assert updated.suggested_dt == "DT-26"


def test_reconcile_heading_fills_empty_dt_for_ccp() -> None:
    ocr = OcrArtifact(
        success=True,
        text="CARGO CLEARANCE PERMIT\nPERMIT NO: OD6F479670G",
        text_length=50,
    )
    llm = LlmDocumentResult(
        suggested_dt="",
        confidence=0.95,
        reasoning="",
        perspective="purchase",
    )
    invoice = Invoice(tenant_id=TESTING_TENANT_UUID, status=InvoiceStatus.PENDING)
    updated, detail = reconcile_llm_dt_with_heading(
        llm,
        invoice=invoice,
        ocr=ocr,
        document_types=[_dt(), _ccp_dt()],
        ai_cfg=AiClassificationConfig(auto_route_min_confidence=0.65),
    )
    assert detail is not None
    assert detail["adopted_dt"] == "DT-CCP"
    assert detail["reason"] == "empty_llm_suggested_dt"
    assert updated is not None
    assert updated.suggested_dt == "DT-CCP"


def test_list_heading_aware_matches_skips_po_goods_for_coo() -> None:
    invoice = Invoice(tenant_id=TESTING_TENANT_UUID, status=InvoiceStatus.PENDING)
    parsed = InvoiceData(
        document_text="CERTIFICATE OF ORIGIN\nInvoice 260371344",
        invoice_no="260371344",
    )
    matches = list_heading_aware_document_type_matches(
        [_dt(), _coo_dt()],
        invoice=invoice,
        parsed=parsed,
    )
    codes = {row[0].code for row in matches}
    assert "DT-01" not in codes


def test_body_keyword_role_label_does_not_override_llm() -> None:
    """Shipper's Name and Address is body noise — must not override a real LLM DT."""
    ocr = OcrArtifact(
        success=True,
        text=(
            "ACME FREIGHT\n"
            "Shipper's Name and Address\n"
            "Acme Pty Ltd\n"
            "Consignee's Name and Address\n"
            "Buyer Co\n"
        ),
        text_length=120,
    )
    llm = LlmDocumentResult(
        suggested_dt="DT-02",
        confidence=0.92,
        reasoning="tax invoice layout",
        perspective="purchase",
        document_heading="",
    )
    invoice = Invoice(tenant_id=TESTING_TENANT_UUID, status=InvoiceStatus.PENDING)
    transport = _dt(
        code="DT-AWB",
        title="Air waybill",
        shortTitle="AWB",
        klass="Non-actionable",
        posting="NEVER",
        playbookProfile="freight_logistics",
        requiredFields=[],
        extractionFields=["vendor"],
        classifier=_classifier(priority=30),
    )
    updated, detail = reconcile_llm_dt_with_heading(
        llm,
        invoice=invoice,
        ocr=ocr,
        document_types=[_dt02(), transport],
        ai_cfg=AiClassificationConfig(auto_route_min_confidence=0.65),
    )
    assert detail is None
    assert updated is not None
    assert updated.suggested_dt == "DT-02"


def test_glued_packinglist_underdetect_unchanged() -> None:
    ocr = OcrArtifact(
        success=True,
        text="PACKINGLIST\nQty Cartons 4",
        text_length=28,
    )
    llm = LlmDocumentResult(
        suggested_dt="DT-02",
        confidence=0.9,
        reasoning="invoice",
        perspective="purchase",
    )
    invoice = Invoice(tenant_id=TESTING_TENANT_UUID, status=InvoiceStatus.PENDING)
    packing = _dt(
        code="DT-PL",
        title="Packing list",
        shortTitle="Packing list",
        klass="Non-actionable",
        posting="NEVER",
        requiredFields=[],
        extractionFields=["vendor"],
        classifier=_classifier(priority=40),
    )
    updated, detail = reconcile_llm_dt_with_heading(
        llm,
        invoice=invoice,
        ocr=ocr,
        document_types=[_dt02(), packing],
        ai_cfg=AiClassificationConfig(auto_route_min_confidence=0.65),
    )
    assert detail is None
    assert updated is not None
    assert updated.suggested_dt == "DT-02"


def test_title_line_commercial_invoice_still_adopts() -> None:
    ocr = OcrArtifact(
        success=True,
        text="COMMERCIAL INVOICE\nSeller Acme\nTotal 100",
        text_length=40,
    )
    llm = LlmDocumentResult(
        suggested_dt="",
        confidence=0.5,
        reasoning="",
        perspective="purchase",
        document_heading="COMMERCIAL INVOICE",
    )
    invoice = Invoice(tenant_id=TESTING_TENANT_UUID, status=InvoiceStatus.PENDING)
    commercial = _dt(
        code="DT-CI",
        title="Commercial invoice",
        shortTitle="Commercial invoice",
        requiredFields=[],
        extractionFields=["vendor", "total"],
        classifier=_classifier(priority=40),
    )
    updated, detail = reconcile_llm_dt_with_heading(
        llm,
        invoice=invoice,
        ocr=ocr,
        document_types=[_dt(), commercial],
        ai_cfg=AiClassificationConfig(auto_route_min_confidence=0.65),
    )
    assert detail is not None
    assert detail["adopted_dt"] == "DT-CI"
    assert detail.get("heading_source") == "title_line"
    assert updated is not None
    assert updated.suggested_dt == "DT-CI"


_GRN_PROMPT = (
    "Goods Receipt Note (GRN), delivery docket, delivery note, or goods received note "
    "confirming physical receipt of goods. Typically shows GRN/delivery number, "
    "receipt/delivery date, PO reference, and received quantities per line. It records "
    "what was received, not what is owed — usually no invoice number, tax invoice wording, "
    "payment terms, or amount due. Do not classify purchase orders, tax invoices, packing "
    "lists alone, or credit notes as this type."
)


def test_grn_negative_prompt_does_not_score_tax_invoice_heading() -> None:
    from app.services.classification.segment_heading_classification import (
        score_document_type_for_heading,
    )

    grn = _dt(
        code="DT-02",
        title="Goods receipt note (GRN) / delivery docket",
        shortTitle="GRN",
        purchaseBundleRole="grn",
        recognition_mode="prompt",
        llm_prompt=_GRN_PROMPT,
        playbookProfile="supporting",
        klass="Non-transactional",
        posting="No",
    )
    assert score_document_type_for_heading(grn, "tax_invoice") < 0.82
    assert score_document_type_for_heading(grn, "grn") >= 0.82
    assert heading_conflicts_with_definition("tax_invoice", grn) is True


def test_heading_scores_via_recognition_signals_not_title() -> None:
    from app.services.classification.segment_heading_classification import (
        classify_from_segment_heading,
        score_document_type_for_heading,
    )

    # Title says invoice, but recognition is GRN-only — must not adopt on invoice heading.
    mislabeled = _dt(
        code="DT-MIS",
        title="Looks like invoice",
        shortTitle="Invoice copy",
        recognition_mode="signals",
        recognition_signals=["heading_grn", "text_grn"],
        playbookProfile="supporting",
        klass="Non-transactional",
        posting="No",
        purchaseBundleRole="grn",
        requiredFields=[],
        extractionFields=["vendor"],
    )
    real_invoice = _dt(
        code="DT-INV",
        title="Standard AP bill",
        shortTitle="AP bill",
        recognition_mode="signals",
        recognition_signals=["heading_invoice", "text_invoice"],
        playbookProfile="direct_expense",
        requiredFields=[],
        extractionFields=["vendor", "total"],
    )
    assert score_document_type_for_heading(mislabeled, "invoice") < 0.82
    assert score_document_type_for_heading(real_invoice, "invoice") >= 0.82

    invoice = Invoice(tenant_id=TESTING_TENANT_UUID, status=InvoiceStatus.PENDING)
    match = classify_from_segment_heading(
        heading_kind="invoice",
        document_types=[mislabeled, real_invoice],
        invoice=invoice,
        parsed=InvoiceData(document_text="INVOICE\nTotal 10"),
    )
    assert match is not None
    assert match.code == "DT-INV"
    assert "recognition signals" in (match.reason or "")


def test_heading_scores_via_recognition_prompt() -> None:
    from app.services.classification.segment_heading_classification import (
        score_document_type_for_heading,
    )

    expense = _dt(
        code="DT-EXP",
        title="Miscellaneous spend",
        shortTitle="Misc",
        recognition_mode="prompt",
        llm_prompt=(
            "Tax invoice or commercial invoice for day-to-day expenses without a PO. "
            "Do not classify goods receipt notes or purchase orders as this type."
        ),
        playbookProfile="direct_expense",
        requiredFields=[],
        extractionFields=["vendor", "total"],
    )
    assert score_document_type_for_heading(expense, "tax_invoice") >= 0.82
    assert score_document_type_for_heading(expense, "grn") < 0.82


def test_tax_invoice_heading_clears_llm_grn_suggestion() -> None:
    ocr = OcrArtifact(
        success=True,
        text="TAX INVOICE\nVendor Acme\nLine item consulting\nTotal 450.00",
        text_length=60,
    )
    llm = LlmDocumentResult(
        suggested_dt="DT-02",
        confidence=0.95,
        reasoning="Looks like GRN",
        perspective="purchase",
        document_heading="TAX INVOICE",
    )
    invoice = Invoice(tenant_id=TESTING_TENANT_UUID, status=InvoiceStatus.PENDING)
    grn = _dt(
        code="DT-02",
        title="Goods receipt note (GRN) / delivery docket",
        shortTitle="GRN",
        purchaseBundleRole="grn",
        recognition_mode="prompt",
        llm_prompt=_GRN_PROMPT,
        playbookProfile="supporting",
        klass="Non-transactional",
        posting="No",
        requiredFields=[],
        extractionFields=["vendor"],
    )
    expense = _dt(
        code="DT-EXP",
        title="Expense bills",
        shortTitle="Expense bill",
        recognition_mode="prompt",
        llm_prompt=(
            "Expense bills will mostly be in the tenant's name with multiple line items "
            "showing the description of expenses."
        ),
        playbookProfile="direct_expense",
        requiredFields=[],
        extractionFields=["vendor", "total"],
    )
    updated, detail = reconcile_llm_dt_with_heading(
        llm,
        invoice=invoice,
        ocr=ocr,
        document_types=[grn, expense],
        ai_cfg=AiClassificationConfig(auto_route_min_confidence=0.65),
    )
    assert detail is not None
    assert detail["reason"] == "heading_conflicts_with_llm_dt"
    assert updated is not None
    assert (updated.suggested_dt or "") != "DT-02"


def test_recognition_gate_blocks_grn_on_tax_invoice_heading() -> None:
    from app.schemas.ocr_artifact import OcrArtifact as OA
    from app.services.invoice.invoice_pipeline_phases import (
        GatePhaseResult,
        apply_recognition_mode_gate,
    )

    grn = _dt(
        code="DT-02",
        title="Goods receipt note (GRN) / delivery docket",
        shortTitle="GRN",
        purchaseBundleRole="grn",
        recognition_mode="prompt",
        llm_prompt=_GRN_PROMPT,
        playbookProfile="supporting",
        klass="Non-transactional",
        posting="No",
    )
    gate = GatePhaseResult(
        passed=True,
        confirmed_dt="DT-02",
        confirmed_confidence=0.95,
        review_reasons=[],
        llm_suggested_dt="DT-02",
        llm_confidence=0.95,
        min_route_confidence=0.85,
        org_auto_route_min_confidence=0.85,
        dt_min_route_confidence=0.65,
    )
    result = apply_recognition_mode_gate(
        gate,
        invoice=Invoice(tenant_id=TESTING_TENANT_UUID, status=InvoiceStatus.PENDING),
        ocr=OA(success=True, text="TAX INVOICE\nExpense line\nTotal 100"),
        document_types=[grn],
    )
    assert result.passed is False
    assert "CLASSIFIER_RULE_MISMATCH" in result.review_reasons
