"""Seed demo business expense invoices for /expenses UI testing.

Run from backend/:
    python seed_expenses_management.py
"""

from __future__ import annotations

import asyncio
import json
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select

from app.database import async_session_factory
from app.models.audit import AuditLog
from app.models.invoice import Invoice, InvoiceStatus
from app.models.line_item import LineItem
from app.services.file_storage import store_invoice_pdf
from app.services.org_context import get_or_create_default_org

ROUTE_EXPENSES = "Expenses Management"
DEMO_HASH_PREFIX = "business_expense_demo_"

_MIN_PDF = b"%PDF-1.4 business-expense-demo"

DEMO_EXPENSES = [
    {
        "hash": f"{DEMO_HASH_PREFIX}001",
        "vendor": "Amazon Web Services",
        "invoice_no": "BE-2001",
        "email_sender": "billing@amazon.com",
        "description": "AWS cloud hosting subscription — May 2026",
        "total": Decimal("2831.00"),
        "status": InvoiceStatus.EXCEPTION,
        "evaluation_status": "needs_review",
        "account_name": "AWS subscription",
        "matched_rule_ids": ["expense:er-1"],
    },
    {
        "hash": f"{DEMO_HASH_PREFIX}002",
        "vendor": "Microsoft",
        "invoice_no": "BE-2002",
        "email_sender": "noreply@microsoft.com",
        "description": "Microsoft 365 Business Premium",
        "total": Decimal("412.50"),
        "status": InvoiceStatus.EXCEPTION,
        "evaluation_status": "needs_review",
        "account_name": "Microsoft 365",
        "matched_rule_ids": ["expense:er-2"],
    },
    {
        "hash": f"{DEMO_HASH_PREFIX}003",
        "vendor": "Telstra",
        "invoice_no": "BE-2003",
        "email_sender": None,
        "description": "Telstra business mobile plan",
        "total": Decimal("189.00"),
        "status": InvoiceStatus.VALIDATING,
        "evaluation_status": "auto_coded",
        "account_name": "Telstra phones",
        "matched_rule_ids": ["expense:er-3"],
    },
    {
        "hash": f"{DEMO_HASH_PREFIX}004",
        "vendor": "Smith & Co Lawyers",
        "invoice_no": "BE-2004",
        "email_sender": "accounts@smithco.com.au",
        "description": "Legal retainer — quarterly advisory",
        "total": Decimal("5500.00"),
        "status": InvoiceStatus.PROCESSED,
        "evaluation_status": "auto_coded",
        "account_name": "Legal — Smith & Co",
        "matched_rule_ids": ["expense:er-4"],
    },
]


async def seed_expenses_management() -> None:
    async with async_session_factory() as session:
        org = await get_or_create_default_org(session)
        existing = (
            await session.execute(
                select(Invoice).where(
                    Invoice.org_id == org.id,
                    Invoice.file_hash.like(f"{DEMO_HASH_PREFIX}%"),
                )
            )
        ).scalars().first()
        if existing:
            print("Business expense demo data already exists — skipping.")
            print(f"Open /expenses in the UI (invoice ids may include {existing.id}).")
            return

        today = date.today()
        created_ids: list[int] = []

        for i, row in enumerate(DEMO_EXPENSES):
            gst = (row["total"] * Decimal("0.10") / Decimal("1.10")).quantize(Decimal("0.01"))
            subtotal = row["total"] - gst
            inv_date = today - timedelta(days=i)

            inv = Invoice(
                org_id=org.id,
                vendor=row["vendor"],
                invoice_no=row["invoice_no"],
                invoice_date=inv_date,
                currency="AUD",
                subtotal=subtotal,
                gst=gst,
                total=row["total"],
                status=row["status"],
                file_hash=row["hash"],
                email_sender=row["email_sender"],
                storage_vendor_slug=row["vendor"].lower().replace(" ", "-")[:50],
                route_target=ROUTE_EXPENSES,
                evaluation_status=row["evaluation_status"],
                account_name=row["account_name"],
                matched_rule_ids=json.dumps(row["matched_rule_ids"]),
            )
            session.add(inv)
            await session.flush()

            stored = store_invoice_pdf(
                _MIN_PDF,
                org.slug,
                inv.storage_vendor_slug or "unknown",
                inv.id,
                row["hash"],
                f"{row['invoice_no']}.pdf",
                org_name=org.name,
                vendor_name=row["vendor"],
                invoice_no=row["invoice_no"],
                invoice_date=inv_date,
            )
            inv.raw_file_path = stored

            session.add(
                LineItem(
                    invoice_id=inv.id,
                    description=row["description"],
                    qty=Decimal("1"),
                    unit_price=subtotal,
                    amount=subtotal,
                )
            )
            session.add(
                AuditLog(
                    org_id=org.id,
                    event="business_expense_seeded",
                    invoice_id=inv.id,
                    detail={"demo": True, "route_target": ROUTE_EXPENSES},
                )
            )
            created_ids.append(inv.id)

        await session.commit()
        print(f"Seeded {len(created_ids)} business expense demo invoices: {created_ids}")
        print("Refresh /expenses — you should see expenses, KPIs, and routed docs.")


if __name__ == "__main__":
    asyncio.run(seed_expenses_management())
