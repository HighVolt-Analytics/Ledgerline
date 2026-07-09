"""Load sample vendors, invoices, and one reconciliation run."""

import asyncio
import json
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select

from app.database import async_session_factory
from app.models.audit import AuditLog
from app.models.invoice import Invoice, InvoiceStatus
from app.services.org_context import get_or_create_default_org
from app.models.journal import EntryType, JournalEntry
from app.models.line_item import LineItem
from app.models.reconciliation import DailyReconciliation
from app.services.master_data.vendor_seed import seed_vendors

VENDORS = [
    ("Acme Pty Ltd", "51824753556", "6100", "Software Expenses"),
    ("Office Supplies Co", "53004085616", "6200", "Office Supplies"),
    ("CloudHost Pty Ltd", "83914571673", "6100", "Software Expenses"),
    ("Legal Partners", "83914571673", "6300", "Professional Fees"),
    ("Travel Express", "51824753556", "6400", "Travel Expenses"),
]

# Demo rows without raw_file_path — avoid EXCEPTION / DUPLICATE_SKIPPED (approval needs a file).
STATUSES = [
    InvoiceStatus.PROCESSED,
    InvoiceStatus.PROCESSED,
    InvoiceStatus.PENDING,
    InvoiceStatus.PENDING,
    InvoiceStatus.VALIDATING,
    InvoiceStatus.MAPPING,
    InvoiceStatus.JOURNALING,
    InvoiceStatus.RECONCILING,
    InvoiceStatus.PROCESSED,
    InvoiceStatus.PROCESSED,
]


async def seed() -> None:
    async with async_session_factory() as session:
        org = await get_or_create_default_org(session)
        vendor_count = await seed_vendors(session, org_id=org.id)
        if vendor_count:
            print(f"Seeded {vendor_count} vendor registry entries.")

        if (await session.execute(select(Invoice).limit(1))).scalar_one_or_none():
            print("Already seeded — skipping.")
            return

        base = date.today() - timedelta(days=7)

        for i in range(20):
            vendor, abn, code, name = VENDORS[i % len(VENDORS)]
            subtotal = Decimal("1000") + Decimal(i * 50)
            gst = (subtotal * Decimal("0.10")).quantize(Decimal("0.01"))
            total = subtotal + gst
            inv_date = base + timedelta(days=i % 7)
            status = STATUSES[i % len(STATUSES)]

            validation = None
            if status == InvoiceStatus.PROCESSED:
                validation = json.dumps([
                    {"rule": r, "passed": True, "message": "OK"}
                    for r in ("VR03", "VR08", "VR01", "VR02")
                ])

            inv = Invoice(
                org_id=org.id,
                vendor=vendor,
                abn=abn,
                invoice_no=f"INV-{1000 + i:04d}",
                invoice_date=inv_date,
                due_date=inv_date + timedelta(days=30),
                currency="AUD",
                subtotal=subtotal,
                gst=gst,
                total=total,
                status=status,
                file_hash=f"seed_{i:04d}",
                account_code=code if status == InvoiceStatus.PROCESSED else None,
                account_name=name if status == InvoiceStatus.PROCESSED else None,
                validation_results=validation,
            )
            session.add(inv)
            await session.flush()

            session.add(
                LineItem(
                    invoice_id=inv.id,
                    description=f"{vendor} — monthly",
                    qty=Decimal("1"),
                    unit_price=subtotal,
                    amount=subtotal,
                )
            )

            if status == InvoiceStatus.PROCESSED:
                for acct_code, acct_name, dr, cr, etype in [
                    (code, name, subtotal, Decimal("0"), EntryType.DEBIT),
                    ("1400", "GST Input", gst, Decimal("0"), EntryType.DEBIT),
                    ("2000", "Accounts Payable", Decimal("0"), total, EntryType.CREDIT),
                ]:
                    session.add(
                        JournalEntry(
                            invoice_id=inv.id,
                            date=inv_date,
                            account_code=acct_code,
                            account_name=acct_name,
                            debit=dr,
                            credit=cr,
                            entry_type=etype,
                        )
                    )

            session.add(AuditLog(event="invoice_seeded", invoice_id=inv.id))

        session.add(
            DailyReconciliation(
                date=base,
                total_invoices=8,
                total_ap_credits=Decimal("8800.00"),
                total_debits=Decimal("8800.00"),
                total_credits=Decimal("8800.00"),
                is_balanced=True,
                halted=False,
            )
        )
        await session.commit()
        print("Seeded 20 invoices, line items, journal entries, and 1 reconciliation.")


async def seed_vendors_only() -> None:
    async with async_session_factory() as session:
        count = await seed_vendors(session)
        await session.commit()
        print(f"Seeded {count} vendor registry entries.")


if __name__ == "__main__":
    asyncio.run(seed())
