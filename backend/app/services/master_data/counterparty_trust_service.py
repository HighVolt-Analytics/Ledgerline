"""Read-only counterparty trust checks for approval routing."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import Invoice
from app.services.invoice.invoice_evaluation_service import ROUTE_SALES


async def counterparty_requires_registration(
    session: AsyncSession,
    invoice: Invoice,
) -> bool:
    """True when vendor/customer is not yet an established master record."""
    if (invoice.route_target or "").strip() == ROUTE_SALES:
        from app.services.master_data.customer_hold_service import (
            _unknown_customer_needs_registration,
        )

        return await _unknown_customer_needs_registration(session, invoice)

    from app.services.master_data.vendor_hold_service import (
        _unknown_vendor_needs_registration,
    )

    return await _unknown_vendor_needs_registration(session, invoice)
