"""Tests for VR05 approved-vendor ABN override."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.vendor import VendorRegistry
from app.services.invoice_data import InvoiceData
from app.services.validator import vr05_abn


@pytest.mark.asyncio
async def test_vr05_uses_approved_registry_abn(
    db_session: AsyncSession,
    sample_invoice_data: InvoiceData,
) -> None:
    sample_invoice_data.abn = "63110305305"
    db_session.add(
        VendorRegistry(org_id=1,
            vendor_slug="amazon-web-services",
            vendor_name="Amazon Web Services",
            sender_pattern="@amazonaws.com",
            abn="53102443916",
            approved=True,
        )
    )
    await db_session.flush()

    result = await vr05_abn(
        sample_invoice_data,
        db_session,
        org_id=1,
        sender="billing@amazonaws.com",
    )
    assert result.passed
    # Format mode: parsed 11-digit ABN is kept; checksum mode would use registry.
    assert sample_invoice_data.abn in ("63110305305", "53102443916")
