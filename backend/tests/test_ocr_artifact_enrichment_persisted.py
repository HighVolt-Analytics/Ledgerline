"""OCR artifact enrichment persistence after DI enrich."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.classification_learning import InvoiceOcrArtifact
from app.models.invoice import Invoice
from app.schemas.ocr_artifact import OcrArtifact
from app.services.classification.classification_learning_service import (
    load_cached_ocr,
    store_ocr_artifact,
    upsert_ocr_artifact_enrichment,
)
from app.tenant_ids import TESTING_TENANT_UUID


@pytest.mark.asyncio
async def test_upsert_ocr_artifact_enrichment_merges_invoice_fields(
    db_session: AsyncSession,
) -> None:
    invoice = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status="pending",
        file_hash="abc123hash",
    )
    db_session.add(invoice)
    await db_session.flush()

    layout_ocr = OcrArtifact(
        text="INVOICE NO: INV-1",
        text_length=16,
        di_model="prebuilt-layout",
        payload_json={"layout_kv": {}},
    )
    await store_ocr_artifact(
        db_session,
        tenant_id=TESTING_TENANT_UUID,
        invoice_id=invoice.id,
        file_hash=invoice.file_hash,
        ocr=layout_ocr,
    )

    enriched = OcrArtifact(
        text="INVOICE NO: INV-1",
        text_length=16,
        di_model="prebuilt-invoice",
        payload_json={
            "layout_kv": {},
            "invoice_fields": {"invoice_no": "INV-1", "vendor": "Acme"},
        },
    )
    await upsert_ocr_artifact_enrichment(
        db_session,
        tenant_id=TESTING_TENANT_UUID,
        invoice_id=invoice.id,
        file_hash=invoice.file_hash,
        ocr=enriched,
    )
    await db_session.commit()

    cached = await load_cached_ocr(
        db_session,
        tenant_id=TESTING_TENANT_UUID,
        invoice_id=invoice.id,
        file_hash=invoice.file_hash,
    )
    assert cached is not None
    assert cached.payload_json.get("invoice_fields", {}).get("invoice_no") == "INV-1"

    row = (
        await db_session.execute(
            select(InvoiceOcrArtifact).where(InvoiceOcrArtifact.invoice_id == invoice.id)
        )
    ).scalar_one()
    assert row.payload_json is not None
    assert row.payload_json.get("invoice_fields", {}).get("invoice_no") == "INV-1"
