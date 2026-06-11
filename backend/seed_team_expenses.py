"""Seed demo team expense claims for /team-expenses UI testing.

Run from backend/:
    python seed_team_expenses.py

Safe to re-run — skips if team expense demo rows already exist.
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

ROUTE_TEAM = "Team Expenses"
DEMO_HASH_PREFIX = "team_expense_demo_"

_MIN_PDF = b"%PDF-1.4 team-expense-demo"

DEMO_CLAIMS = [
    {
        "hash": f"{DEMO_HASH_PREFIX}001",
        "vendor": "Cafe Milano",
        "invoice_no": "TE-1001",
        "email_sender": "priya@acme-hospitality.com.au",
        "description": "Site supervisor team lunch meal",
        "total": Decimal("42.50"),
        "status": InvoiceStatus.EXCEPTION,
        "evaluation_status": "needs_review",
        "account_name": "Site supervisor meals",
        "cost_centre": "SITE-042",
        "matched_rule_ids": ["team:tr-1"],
    },
    {
        "hash": f"{DEMO_HASH_PREFIX}002",
        "vendor": "Uber",
        "invoice_no": "TE-1002",
        "email_sender": "+61412345678",
        "description": "Client site Uber trip",
        "total": Decimal("28.90"),
        "status": InvoiceStatus.EXCEPTION,
        "evaluation_status": "needs_review",
        "account_name": "Taxi & rideshare",
        "cost_centre": "OPS-101",
        "matched_rule_ids": ["team:tr-2"],
    },
    {
        "hash": f"{DEMO_HASH_PREFIX}003",
        "vendor": "Officeworks",
        "invoice_no": "TE-1003",
        "email_sender": "marcus.webb@acme-hospitality.com.au",
        "description": "Stationery and coffee supplies",
        "total": Decimal("67.20"),
        "status": InvoiceStatus.VALIDATING,
        "evaluation_status": "auto_coded",
        "account_name": "Office supplies",
        "cost_centre": "HQ-001",
        "matched_rule_ids": ["team:tr-3"],
    },
    {
        "hash": f"{DEMO_HASH_PREFIX}004",
        "vendor": "Grill House",
        "invoice_no": "TE-1004",
        "email_sender": "james@acme-hospitality.com.au",
        "description": "Client dinner — approved claim",
        "total": Decimal("95.00"),
        "status": InvoiceStatus.PROCESSED,
        "evaluation_status": "auto_coded",
        "account_name": "Client entertainment",
        "cost_centre": "MKT-220",
        "matched_rule_ids": ["team:tr-4"],
    },
]


async def seed_team_expenses() -> None:
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
            print("Team expense demo data already exists — skipping.")
            print(f"Open /team-expenses in the UI (invoice ids may include {existing.id}).")
            return

        today = date.today()
        created_ids: list[int] = []

        for i, row in enumerate(DEMO_CLAIMS):
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
                route_target=ROUTE_TEAM,
                evaluation_status=row["evaluation_status"],
                account_name=row["account_name"],
                cost_centre=row["cost_centre"],
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
                    event="team_expense_seeded",
                    invoice_id=inv.id,
                    detail={"demo": True, "route_target": ROUTE_TEAM},
                )
            )
            created_ids.append(inv.id)

        await session.commit()
        print(f"Seeded {len(created_ids)} team expense demo claims: {created_ids}")
        print("Refresh /team-expenses — you should see claims, KPIs, and routed docs.")


if __name__ == "__main__":
    asyncio.run(seed_team_expenses())
