"""Backfill invoice.so_reference for Sales Management documents.

Usage (from backend/):
    python scripts/backfill_so_references.py
    python scripts/backfill_so_references.py --tenant 550e8400-e29b-41d4-a716-446655440001
    python scripts/backfill_so_references.py --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import uuid

from sqlalchemy import or_, select

from app.database import async_session_factory
from app.models.invoice import Invoice
from app.services.invoice_evaluation_service import ROUTE_SALES
from app.services.sales_document_service import sync_sales_document
from app.services.so_reference import ensure_invoice_so_reference, resolve_so_reference_from_invoice


async def backfill(*, tenant_id: uuid.UUID | None, dry_run: bool, resync: bool) -> None:
    async with async_session_factory() as session:
        stmt = select(Invoice).where(Invoice.route_target == ROUTE_SALES)
        if tenant_id is not None:
            stmt = stmt.where(Invoice.tenant_id == tenant_id)
        if not resync:
            stmt = stmt.where(
                or_(Invoice.so_reference.is_(None), Invoice.so_reference == "")
            )
        invoices = (await session.execute(stmt)).scalars().all()

        updated = 0
        synced = 0
        for inv in invoices:
            before = inv.so_reference
            resolved = resolve_so_reference_from_invoice(inv)
            if not resolved:
                if resync:
                    continue
                print(
                    f"  skip id={inv.id} attach={inv.email_attachment_name!r} "
                    f"invoice_no={inv.invoice_no!r}"
                )
                continue
            ensure_invoice_so_reference(inv)
            if inv.so_reference != before:
                updated += 1
                print(f"  set id={inv.id} so_reference={inv.so_reference!r}")
            elif resync:
                print(f"  resync id={inv.id} so_reference={inv.so_reference!r}")
            if not dry_run:
                await sync_sales_document(session, inv)
                synced += 1

        if dry_run:
            print(f"Dry run: would update {updated} invoice(s), sync {synced}")
            await session.rollback()
            return

        await session.commit()
        print(f"Done: updated {updated} invoice(s), synced {synced}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant", type=uuid.UUID, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--resync",
        action="store_true",
        help="Re-run sales register sync for all sales-route invoices",
    )
    args = parser.parse_args()
    asyncio.run(backfill(tenant_id=args.tenant, dry_run=args.dry_run, resync=args.resync))


if __name__ == "__main__":
    main()
