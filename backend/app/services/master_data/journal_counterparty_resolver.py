"""Resolve vendor/customer registry IDs for journal control-account lines."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import Invoice
from app.services.invoice.invoice_evaluation_service import ROUTE_SALES
from app.services.master_data.customer_registry_service import (
    resolve_customer_registry_id_for_invoice,
)
from app.services.master_data.vendor_payout_method_service import (
    resolve_vendor_registry_id_for_invoice,
)


async def resolve_counterparty_registry_ids_for_journal(
    session: AsyncSession,
    invoice: Invoice,
) -> tuple[int | None, int | None]:
    """Return (vendor_registry_id, customer_registry_id) for AP/AR control lines."""
    route = (invoice.route_target or "").strip()
    if route == ROUTE_SALES:
        customer_id = await resolve_customer_registry_id_for_invoice(
            session,
            invoice.tenant_id,
            customer_name=invoice.vendor,
            storage_slug=invoice.storage_vendor_slug,
        )
        return None, customer_id

    vendor_id = await resolve_vendor_registry_id_for_invoice(
        session,
        invoice.tenant_id,
        vendor_name=invoice.vendor,
        storage_vendor_slug=invoice.storage_vendor_slug,
    )
    return vendor_id, None
