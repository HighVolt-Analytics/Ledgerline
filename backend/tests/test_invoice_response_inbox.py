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
from app.services.invoice.invoice_response_service import (
    _document_text_if_loaded,
    _legacy_awaiting_maps_to_vision_vaulted,
    invoice_to_response,
)
from app.tenant_ids import TESTING_TENANT_UUID


def _vault_permit_type() -> DocumentTypeDefinition:
    return DocumentTypeDefinition(
        code="DT-02",
        title="Clearance permit",
        shortTitle="Clearance permit",
        klass="Non-transactional",
        posting="No",
        recognition_mode="signals", recognition_signals=["heading_invoice"], llm_prompt="",
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
        recognition_mode="signals", recognition_signals=["heading_invoice"], llm_prompt="",
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


def test_legacy_awaiting_with_vision_markers_maps_to_vaulted() -> None:
    inv = Invoice(
        id=903,
        tenant_id=TESTING_TENANT_UUID,
        created_at=datetime.now(timezone.utc),
        status=InvoiceStatus.EXCEPTION,
        evaluation_status="awaiting_classification",
        document_heading="TAX INVOICE",
        extracted_fields={
            "vision_bundle_kind": "invoice_no",
            "vision_bundle_key": "INV-1",
        },
        currency="AUD",
    )
    response = invoice_to_response(inv, for_list=True)
    assert response.evaluation_status == EvaluationStatus.VISION_VAULTED


def test_legacy_awaiting_heading_empty_body_maps_to_vaulted() -> None:
    inv = Invoice(
        id=904,
        tenant_id=TESTING_TENANT_UUID,
        created_at=datetime.now(timezone.utc),
        status=InvoiceStatus.EXCEPTION,
        evaluation_status="awaiting_classification",
        document_heading="AIR WAYBILL",
        document_text="",
        currency="AUD",
    )
    assert _legacy_awaiting_maps_to_vision_vaulted(inv) is True
    response = invoice_to_response(inv, for_list=True)
    assert response.evaluation_status == EvaluationStatus.VISION_VAULTED


def test_document_text_if_loaded_returns_none_when_deferred() -> None:
    class _State:
        dict: dict = {}

    class _Inv:
        document_text = "should not be read"

    import app.services.invoice.invoice_response_service as svc

    mp = pytest.MonkeyPatch()
    mp.setattr("sqlalchemy.inspect", lambda _o: _State())
    try:
        assert svc._document_text_if_loaded(_Inv()) is None  # type: ignore[arg-type]
    finally:
        mp.undo()


def test_document_text_if_loaded_returns_value_when_in_dict() -> None:
    class _State:
        dict = {"document_text": "TAX BODY"}

    class _Inv:
        document_text = "TAX BODY"

    import app.services.invoice.invoice_response_service as svc

    mp = pytest.MonkeyPatch()
    mp.setattr("sqlalchemy.inspect", lambda _o: _State())
    try:
        assert svc._document_text_if_loaded(_Inv()) == "TAX BODY"  # type: ignore[arg-type]
    finally:
        mp.undo()


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


@pytest.mark.asyncio
async def test_list_invoices_deferred_document_text_no_missing_greenlet(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """List defers document_text; legacy awaiting + heading must not lazy-load it."""
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Vision Vendor Co",
        status=InvoiceStatus.EXCEPTION,
        evaluation_status="awaiting_classification",
        document_heading="TAX INVOICE",
        document_text="large body that must stay deferred on list " * 50,
        extracted_fields={
            "canonical_document_type": "Tax Invoice",
            "vision_header_confidence": "0.9100",
        },
        currency="AUD",
        file_hash="inbox-vision-deferred-text",
        capture_source="upload",
    )
    db_session.add(inv)
    await db_session.flush()

    # Expire so document_text is not in the instance dict (mirrors list defer).
    await db_session.refresh(inv, attribute_names=["id"])
    from sqlalchemy import inspect as sa_inspect

    sa_inspect(inv).session.expire(inv, ["document_text"])
    assert _document_text_if_loaded(inv) is None
    assert _legacy_awaiting_maps_to_vision_vaulted(inv) is True

    res = await client.get("/api/invoices?page=1&page_size=50&capture_source=upload")
    assert res.status_code == 200
    data = res.json()["data"]
    match = next(item for item in data if item["file_hash"] == "inbox-vision-deferred-text")
    assert match["evaluation_status"] == "vision_vaulted"
