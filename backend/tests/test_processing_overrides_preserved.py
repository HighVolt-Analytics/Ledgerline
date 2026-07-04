"""Processing overrides survive requeue."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import Invoice, InvoiceStatus
from app.services.invoice.invoice_reset import requeue_invoice_for_pipeline
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

    assert inv.processing_overrides == {"skip_steps": ["validation"]}
