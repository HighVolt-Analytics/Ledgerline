"""Inbox display normalization on invoice API responses."""

from __future__ import annotations

import json

from datetime import datetime, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import Invoice, InvoiceStatus
from app.schemas.document_type import DocumentTypeDefinition
from app.schemas.invoice import EvaluationStatus
from app.services.invoice.invoice_evaluation_service import EVAL_AUTO_CODED, EVAL_NEEDS_REVIEW
from app.services.invoice.invoice_response_service import invoice_to_response
from app.tenant_ids import TESTING_TENANT_UUID


def _vault_permit_type() -> DocumentTypeDefinition:
    return DocumentTypeDefinition(
        code="DT-02",
        title="Clearance permit",
        shortTitle="Clearance permit",
        klass="Non-transactional",
        posting="No",
        oneLine="test",
        routeTarget="Vault",
        validationProfile="non_actionable",
        playbookProfile="supporting",
    )


def test_inbox_response_hides_vr_and_vendor_for_vault_permit() -> None:
    inv = Invoice(
        id=901,
        tenant_id=TESTING_TENANT_UUID,
        created_at=datetime.now(timezone.utc),
        status=InvoiceStatus.PROCESSED,
        route_target="Vault",
        document_type_code="DT-02",
        vendor_confidence=42.0,
        evaluation_status=EVAL_NEEDS_REVIEW,
        validation_results=json.dumps(
            [{"rule": "VR03", "passed": False, "message": "missing", "skipped": False}]
        ),
        currency="AUD",
    )
    response = invoice_to_response(inv, document_types=[_vault_permit_type()])
    assert response.vendor_confidence is None
    assert response.validation_pass_rate is None
    assert response.evaluation_status == EvaluationStatus.AUTO_CODED


def test_inbox_response_exposes_payable_metrics() -> None:
    payable_type = DocumentTypeDefinition(
        code="DT-01",
        title="Invoice",
        shortTitle="Invoice",
        klass="Transactional",
        posting="Yes",
        oneLine="test",
        routeTarget="Purchase Management",
        validationProfile="standard",
    )
    inv = Invoice(
        id=902,
        tenant_id=TESTING_TENANT_UUID,
        created_at=datetime.now(timezone.utc),
        status=InvoiceStatus.EXCEPTION,
        route_target="Purchase Management",
        document_type_code="DT-01",
        vendor_confidence=88.0,
        evaluation_status=EVAL_AUTO_CODED,
        validation_results=json.dumps(
            [
                {"rule": "VR01", "passed": True, "message": "ok", "skipped": False},
                {"rule": "VR03", "passed": False, "message": "missing", "skipped": False},
            ]
        ),
        currency="AUD",
    )
    response = invoice_to_response(inv, document_types=[payable_type])
    assert response.vendor_confidence == 88.0
    assert response.validation_pass_rate == 50


@pytest.mark.asyncio
async def test_list_invoices_returns_normalized_inbox_fields(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Spectra Innovations",
        status=InvoiceStatus.PROCESSED,
        route_target="Vault",
        document_type_code="DT-02",
        evaluation_status=EVAL_NEEDS_REVIEW,
        vendor_confidence=0.0,
        validation_results=json.dumps(
            [{"rule": "VR03", "passed": False, "message": "missing", "skipped": False}]
        ),
        currency="AUD",
        file_hash="inbox-response-vault",
        capture_source="upload",
    )
    db_session.add(inv)
    await db_session.flush()

    res = await client.get("/api/invoices?page=1&page_size=20")
    assert res.status_code == 200
    row = next(item for item in res.json()["data"] if item["file_hash"] == "inbox-response-vault")
    assert row["vendor_confidence"] is None
    assert row["validation_pass_rate"] is None
    assert row["evaluation_status"] == "auto_coded"
    assert row["capture_source"] == "upload"
