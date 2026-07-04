"""Seed demo sales orders for /sales three-way match UI testing.

Run from backend/:
    python seed_sales_management.py
"""

from __future__ import annotations

import asyncio
from datetime import date
from decimal import Decimal

from sqlalchemy import select

from app.database import async_session_factory
from app.models.customer_master import CustomerMasterRecord
from app.models.sales_order import SalesOrder
from app.services.tenant.tenant_context_service import get_or_create_default_tenant


async def main() -> None:
    async with async_session_factory() as session:
        tenant = await get_or_create_default_tenant(session)
        existing = (
            await session.execute(
                select(SalesOrder).where(
                    SalesOrder.tenant_id == tenant.id,
                    SalesOrder.so_number == "SO-DEMO-100",
                )
            )
        ).scalar_one_or_none()
        if existing is None:
            session.add(
                SalesOrder(
                    tenant_id=tenant.id,
                    so_number="SO-DEMO-100",
                    customer="Harbour View Hotel",
                    so_date=date.today(),
                    item="Catering package",
                    so_qty=Decimal("10"),
                    so_unit_price=Decimal("45"),
                    ledger="Operating Revenue",
                    sub_ledger="Room Sales",
                    receivable_account="Accounts Receivable",
                )
            )
        cm = (
            await session.execute(
                select(CustomerMasterRecord).where(
                    CustomerMasterRecord.tenant_id == tenant.id,
                    CustomerMasterRecord.master_id == "cm-harbour",
                )
            )
        ).scalar_one_or_none()
        if cm is None:
            session.add(
                CustomerMasterRecord(
                    tenant_id=tenant.id,
                    master_id="cm-harbour",
                    name="Harbour View Hotel",
                    aliases=["HV Hotel"],
                    default_ledger="Operating Revenue",
                    payment_terms="Net 30",
                    status="Active",
                )
            )
        await session.commit()
        print("Sales demo seed complete.")


if __name__ == "__main__":
    asyncio.run(main())
