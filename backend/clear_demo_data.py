"""Remove seeded/demo data so you can test with real emails and uploads.

Run from backend/:
    python clear_demo_data.py           # demo hash prefixes only
    python clear_demo_data.py --all     # all invoices + POs + payments for default org
    python clear_demo_data.py --reset-rules  # reset org rule book to empty template
"""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
from pathlib import Path

from sqlalchemy import delete, or_, select

from app.config import get_settings
from app.database import async_session_factory
from app.models.audit import AuditLog
from app.models.employee_master import EmployeeMasterRecord
from app.models.goods_receipt import GoodsReceipt
from app.models.invoice import Invoice
from app.models.journal import JournalEntry
from app.models.line_item import LineItem
from app.models.payment import Payment
from app.models.pending_vendor import PendingVendor
from app.models.purchase_order import PurchaseOrder
from app.models.reconciliation import DailyReconciliation
from app.models.vendor import VendorRegistry
from app.models.vendor_master import VendorMasterRecord
from app.schemas.rule_book_config import RuleBookConfigPayload
from app.services.org_context import get_or_create_default_org
from app.services.rule_book_config_io import (
    global_rule_book_config_path,
    org_rule_book_config_path,
    save_rule_book_config,
)
from app.services.rule_book_mapper import clear_classification_config_cache

_DEMO_HASH_PATTERNS = (
    "seed_%",
    "%_demo_%",
    "business_expense_demo_%",
    "purchase_demo_%",
    "team_expense_demo_%",
)


def _empty_rule_book_payload() -> RuleBookConfigPayload:
    template = global_rule_book_config_path()
    with template.open(encoding="utf-8") as fh:
        return RuleBookConfigPayload.model_validate(json.load(fh))


async def clear_demo_data(*, all_invoices: bool, reset_rules: bool) -> None:
    settings = get_settings()
    org = None
    removed_invoices = 0

    async with async_session_factory() as session:
        org = await get_or_create_default_org(session)

        if all_invoices:
            invoice_ids = (
                await session.execute(
                    select(Invoice.id).where(Invoice.org_id == org.id)
                )
            ).scalars().all()
        else:
            invoice_ids = (
                await session.execute(
                    select(Invoice.id).where(
                        Invoice.org_id == org.id,
                        or_(*[Invoice.file_hash.like(p) for p in _DEMO_HASH_PATTERNS]),
                    )
                )
            ).scalars().all()

        if invoice_ids:
            await session.execute(delete(JournalEntry).where(JournalEntry.invoice_id.in_(invoice_ids)))
            await session.execute(delete(LineItem).where(LineItem.invoice_id.in_(invoice_ids)))
            await session.execute(delete(AuditLog).where(AuditLog.invoice_id.in_(invoice_ids)))
            await session.execute(delete(Payment).where(Payment.invoice_id.in_(invoice_ids)))
            await session.execute(
                delete(PurchaseOrder).where(PurchaseOrder.invoice_id.in_(invoice_ids))
            )
            result = await session.execute(
                delete(Invoice).where(Invoice.id.in_(invoice_ids))
            )
            removed_invoices = result.rowcount or 0

        if all_invoices:
            await session.execute(delete(GoodsReceipt))
            await session.execute(delete(PurchaseOrder).where(PurchaseOrder.org_id == org.id))
            await session.execute(delete(Payment).where(Payment.org_id == org.id))
            await session.execute(delete(PendingVendor).where(PendingVendor.org_id == org.id))
            await session.execute(delete(DailyReconciliation))
            await session.execute(delete(VendorRegistry).where(VendorRegistry.org_id == org.id))
            await session.execute(
                delete(VendorMasterRecord).where(VendorMasterRecord.org_id == org.id)
            )
            await session.execute(
                delete(EmployeeMasterRecord).where(EmployeeMasterRecord.org_id == org.id)
            )
            await session.execute(
                delete(AuditLog).where(AuditLog.org_id == org.id)
            )

        await session.commit()

    if reset_rules and org is not None:
        payload = _empty_rule_book_payload()
        save_rule_book_config(payload, org.id)
        clear_classification_config_cache()
        org_path = org_rule_book_config_path(org.id)
        print(f"Reset rule book: {org_path}")

    upload_root = Path(settings.upload_dir)
    if upload_root.is_dir() and all_invoices:
        for sub in ("invoices", "hv-org"):
            target = upload_root / sub
            if target.is_dir():
                shutil.rmtree(target, ignore_errors=True)
                print(f"Removed uploaded files: {target}")

    print(
        f"Cleared {removed_invoices} invoice(s) for org {org.id if org else '?'}"
        + (" (all data)" if all_invoices else " (demo hashes only)")
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Remove demo/seed data from the database.")
    parser.add_argument(
        "--all",
        action="store_true",
        help="Delete ALL invoices, POs, payments, masters, and uploaded PDFs for the default org.",
    )
    parser.add_argument(
        "--reset-rules",
        action="store_true",
        help="Reset org rule book JSON to the empty template (no demo capture/category rules).",
    )
    args = parser.parse_args()
    if not args.all and not args.reset_rules:
        args.all = True
        args.reset_rules = True
    asyncio.run(
        clear_demo_data(all_invoices=args.all, reset_rules=args.reset_rules)
    )


if __name__ == "__main__":
    main()
