"""Analyze document-type samples API."""

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from httpx import AsyncClient

from app.models.invoice import Invoice, InvoiceStatus
from app.schemas.document_type import DocumentTypeDefinition
from app.services.invoice.invoice_data import InvoiceData


@pytest.mark.asyncio
async def test_analyze_samples_with_pdf(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parsed = InvoiceData(
        vendor="Acme",
        invoice_no="INV-1",
        invoice_date=date(2026, 3, 1),
        total=Decimal("110"),
        document_text="TAX INVOICE",
        document_heading="TAX INVOICE",
    )
    invoice = Invoice(
        id=0,
        tenant_id=0,
        status=InvoiceStatus.PARSING,
        currency="AUD",
        email_attachment_name="sample.pdf",
    )

    def fake_parse(filename: str, content: bytes):
        _ = content
        return invoice, parsed, "high", None, None

    monkeypatch.setattr(
        "app.services.document_type_sample_analyzer._parse_sample",
        fake_parse,
    )

    pdf = Path(__file__).resolve().parents[2] / "test-assets" / "test-invoice-PO-MKT-2026-TEST.pdf"
    if not pdf.is_file():
        pytest.skip("test PDF missing")

    draft = DocumentTypeDefinition.model_validate(
        {
            "code": "DT-01",
            "title": "PO goods invoice",
            "shortTitle": "PO goods",
            "klass": "Transactional",
            "posting": "Yes",
            "recognition_mode": "signals", "recognition_signals": ["heading_invoice"], "llm_prompt": "",
            "routeTarget": "Vault",
            "enabled": True,
            "classifier": {
                "enabled": False,
                "priority": 100,
                "confidence": 0.85,
                "root": {"type": "group", "operator": "AND", "children": []},
            },
            "requiredFields": [],
            "absentFields": [],
            "minRouteConfidence": 0.65,
            "validationProfile": "",
            "playbookProfile": "standard_transactional",
            "matchPolicy": {"mode": "none"},
            "approvalPolicy": {"mode": "touchless_on_clean_match"},
            "validationRules": [],
            "customValidationRules": [],
            "extractionFields": [],
            "extraction": [],
            "checks": [],
            "match": [],
            "approval": [],
            "accounting": [],
            "special": [],
            "bundleMandatory": [],
            "bundleConditional": [],
            "purchaseBundleRole": "",
        }
    )

    res = await client.post(
        "/api/rule-book/document-types/analyze-samples",
        files=[("files", (pdf.name, pdf.read_bytes(), "application/pdf"))],
        data={
            "expected_document_type_code": draft.code,
            "draft_document_type_json": draft.model_dump_json(by_alias=True),
        },
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["data"]["recognition_signals"]
    assert body["data"]["samples"]
