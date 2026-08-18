"""Processing overrides survive requeue."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import Invoice, InvoiceStatus
from app.services.invoice.invoice_reset import requeue_invoice_for_pipeline
from app.services.invoice.processing_override_catalog import normalise_processing_overrides
from app.tenant_ids import TESTING_TENANT_UUID


@pytest.mark.asyncio
async def test_processing_overrides_preserved_on_requeue(
    db_session: AsyncSession,
) -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.EXCEPTION,
        currency="AUD",
        file_hash="override-preserve-1",
        processing_overrides={"skip_steps": ["validation"]},
        vendor="Acme",
        total=100,
    )
    db_session.add(inv)
    await db_session.flush()

    await requeue_invoice_for_pipeline(db_session, inv, preserve_extracted_fields=True)
    await db_session.flush()

    assert inv.processing_overrides == {
        "skip_steps": ["validation"],
        "preserve_extracted_fields": True,
    }


@pytest.mark.asyncio
async def test_full_requeue_preserves_processing_overrides(
    db_session: AsyncSession,
) -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.REJECTED,
        currency="AUD",
        file_hash="override-preserve-full-1",
        processing_overrides={"skip_steps": ["validation", "playbook"]},
    )
    db_session.add(inv)
    await db_session.flush()

    await requeue_invoice_for_pipeline(db_session, inv, preserve_extracted_fields=False)
    await db_session.flush()

    assert normalise_processing_overrides(inv.processing_overrides).skip_steps == [
        "playbook",
        "validation",
    ]
    assert inv.processing_overrides.get("deferred_full_reset") is True
    assert inv.status == InvoiceStatus.PENDING


@pytest.mark.asyncio
async def test_classification_skip_preserves_document_type_on_full_requeue(
    db_session: AsyncSession,
) -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.REJECTED,
        currency="AUD",
        file_hash="override-classification-dt-1",
        document_type_code="DT-01",
        document_type_confidence=0.9,
        processing_overrides={"skip_steps": ["classification"]},
    )
    db_session.add(inv)
    await db_session.flush()

    await requeue_invoice_for_pipeline(db_session, inv, preserve_extracted_fields=False)
    await db_session.flush()

    assert inv.processing_overrides == {
        "skip_steps": ["classification"],
        "deferred_full_reset": True,
    }
    assert inv.document_type_code == "DT-01"
    assert inv.document_type_confidence == 0.9
