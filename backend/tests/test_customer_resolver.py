"""Customer capture slug resolution and registry promotion sync."""

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.customer import CustomerRegistry
from app.models.invoice import Invoice, InvoiceStatus
from app.models.vendor import VendorRegistry
from app.services.master_data.customer_resolver import (
    resolve_capture_slug,
    resolve_customer_slug,
)
from app.services.master_data.registry_promotion_service import (
    sync_customer_registry_after_promotion,
    sync_vendor_registry_after_promotion,
)
from app.services.master_data.vendor_resolver import UNKNOWN_SLUG
from app.tenant_ids import TESTING_TENANT_UUID


@pytest.mark.asyncio
async def test_resolve_customer_slug_domain(db_session: AsyncSession) -> None:
    db_session.add(
        CustomerRegistry(
            tenant_id=TESTING_TENANT_UUID,
            customer_slug="acme-corp",
            customer_name="Acme Corp",
            sender_pattern="@acme.com",
            approved=False,
        )
    )
    await db_session.flush()

    slug = await resolve_customer_slug(
        db_session, "billing@acme.com", tenant_id=TESTING_TENANT_UUID
    )
    assert slug == "acme-corp"


@pytest.mark.asyncio
async def test_resolve_capture_slug_falls_back_to_customer(db_session: AsyncSession) -> None:
    db_session.add(
        CustomerRegistry(
            tenant_id=TESTING_TENANT_UUID,
            customer_slug="retail-co",
            customer_name="Retail Co",
            sender_pattern="orders@retail.co",
            approved=False,
        )
    )
    await db_session.flush()

    slug = await resolve_capture_slug(
        db_session, "orders@retail.co", tenant_id=TESTING_TENANT_UUID
    )
    assert slug == "retail-co"


@pytest.mark.asyncio
async def test_resolve_capture_slug_unknown(db_session: AsyncSession) -> None:
    slug = await resolve_capture_slug(
        db_session, "nobody@example.com", tenant_id=TESTING_TENANT_UUID
    )
    assert slug == UNKNOWN_SLUG


@pytest.mark.asyncio
async def test_sync_vendor_registry_after_promotion(db_session: AsyncSession) -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="New Supplier",
        email_sender="ap@newsupplier.com",
        status=InvoiceStatus.EXCEPTION,
        currency="AUD",
        file_hash="reg-promo-v1",
    )
    db_session.add(inv)
    await db_session.flush()

    await sync_vendor_registry_after_promotion(
        db_session,
        tenant_id=TESTING_TENANT_UUID,
        name="New Supplier Pty Ltd",
        abn="51824753556",
        source_invoice_id=inv.id,
    )
    await db_session.flush()

    row = (
        await db_session.execute(
            select(VendorRegistry).where(
                VendorRegistry.tenant_id == TESTING_TENANT_UUID,
                VendorRegistry.vendor_slug == "new-supplier-pty-ltd",
            )
        )
    ).scalar_one_or_none()
    assert row is not None
    assert row.sender_pattern == "ap@newsupplier.com"
    assert row.vendor_name == "New Supplier Pty Ltd"


@pytest.mark.asyncio
async def test_sync_customer_registry_after_promotion(db_session: AsyncSession) -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Buyer Inc",
        email_sender="finance@buyer.inc",
        status=InvoiceStatus.EXCEPTION,
        currency="AUD",
        file_hash="reg-promo-c1",
    )
    db_session.add(inv)
    await db_session.flush()

    await sync_customer_registry_after_promotion(
        db_session,
        tenant_id=TESTING_TENANT_UUID,
        name="Buyer Inc",
        abn=None,
        source_invoice_id=inv.id,
    )
    await db_session.flush()

    row = (
        await db_session.execute(
            select(CustomerRegistry).where(
                CustomerRegistry.tenant_id == TESTING_TENANT_UUID,
                CustomerRegistry.customer_slug == "buyer-inc",
            )
        )
    ).scalar_one_or_none()
    assert row is not None
    assert row.sender_pattern == "finance@buyer.inc"
