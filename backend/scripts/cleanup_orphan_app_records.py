"""Remove application records whose stored PDF/blob no longer exists.

Usage (from backend/):
    python scripts/cleanup_orphan_app_records.py --dry-run
    python scripts/cleanup_orphan_app_records.py
    python scripts/cleanup_orphan_app_records.py --legacy-local
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import delete, or_, select, update

from app.config import get_settings
from app.database import async_session_factory
from app.models.audit import AuditLog
from app.models.dossier_manual_link import DossierManualLink
from app.models.goods_receipt import GoodsReceipt
from app.models.invoice import Invoice
from app.models.journal import JournalEntry
from app.models.line_item import LineItem
from app.models.payment import Payment
from app.models.purchase_order import PurchaseOrder
from app.services.audit.audit_service import log_event
from app.services.shared.file_storage import stored_file_available


async def _orphan_invoice_ids() -> list[tuple[int, str | None, str | None]]:
    async with async_session_factory() as session:
        rows = (
            await session.execute(
                select(
                    Invoice.id,
                    Invoice.invoice_no,
                    Invoice.vendor,
                    Invoice.raw_file_path,
                    Invoice.tenant_id,
                ).order_by(Invoice.id)
            )
        ).all()

    orphans: list[tuple[int, str | None, str | None]] = []
    for invoice_id, invoice_no, vendor, stored, tenant_id in rows:
        if not stored or not stored_file_available(stored, tenant_id=tenant_id):
            orphans.append((invoice_id, invoice_no, vendor))
    return orphans


async def _purge_invoices(invoice_ids: list[int], *, dry_run: bool) -> int:
    if not invoice_ids:
        return 0

    async with async_session_factory() as session:
        invoices = list(
            (await session.execute(select(Invoice).where(Invoice.id.in_(invoice_ids)))).scalars().all()
        )
        if dry_run:
            for inv in invoices:
                print(
                    f"  would delete invoice {inv.id}: "
                    f"{inv.invoice_no or '?'} / {inv.vendor or '?'} ({inv.status.value})"
                )
            return len(invoices)

        for inv in invoices:
            await log_event(
                session,
                "invoice_orphan_purged",
                invoice_id=inv.id,
                detail={
                    "invoice_no": inv.invoice_no,
                    "vendor": inv.vendor,
                    "status": inv.status.value,
                    "stored_path": inv.raw_file_path,
                },
            )

        await session.execute(
            delete(DossierManualLink).where(
                or_(
                    DossierManualLink.anchor_invoice_id.in_(invoice_ids),
                    DossierManualLink.linked_invoice_id.in_(invoice_ids),
                )
            )
        )
        await session.execute(delete(JournalEntry).where(JournalEntry.invoice_id.in_(invoice_ids)))
        await session.execute(delete(LineItem).where(LineItem.invoice_id.in_(invoice_ids)))
        await session.execute(delete(Payment).where(Payment.invoice_id.in_(invoice_ids)))
        await session.execute(
            update(PurchaseOrder)
            .where(PurchaseOrder.invoice_id.in_(invoice_ids))
            .values(invoice_id=None)
        )
        await session.execute(
            update(PurchaseOrder)
            .where(PurchaseOrder.po_document_id.in_(invoice_ids))
            .values(po_document_id=None)
        )
        await session.execute(
            update(GoodsReceipt)
            .where(GoodsReceipt.grn_invoice_id.in_(invoice_ids))
            .values(grn_invoice_id=None)
        )
        await session.execute(delete(AuditLog).where(AuditLog.invoice_id.in_(invoice_ids)))
        result = await session.execute(delete(Invoice).where(Invoice.id.in_(invoice_ids)))
        await session.commit()
        return result.rowcount or 0


def _cleanup_legacy_local_files(*, dry_run: bool) -> int:
    """Remove shared legacy JSON under upload root when per-tenant copies exist."""
    upload = Path(get_settings().upload_dir)
    removed = 0
    legacy_names = ("billing.json", "approval_policy.json")
    for name in legacy_names:
        legacy = upload / name
        if not legacy.is_file():
            continue
        tenant_root = upload / "tenants"
        has_tenant_copy = tenant_root.is_dir() and any(
            (path / name).is_file() for path in tenant_root.iterdir() if path.is_dir()
        )
        if not has_tenant_copy:
            continue
        if dry_run:
            print(f"  would remove local {legacy}")
        else:
            legacy.unlink()
            print(f"  removed local {legacy}")
        removed += 1

    for legacy_dir in ("invoice", "invoices", "rejected", "reports"):
        target = upload / legacy_dir
        if not target.exists():
            continue
        if dry_run:
            print(f"  would remove local tree {target}")
        else:
            if target.is_dir():
                import shutil

                shutil.rmtree(target, ignore_errors=True)
            else:
                target.unlink()
            print(f"  removed local tree {target}")
        removed += 1
    return removed


async def _run(*, dry_run: bool, legacy_local: bool) -> int:
    orphans = await _orphan_invoice_ids()
    print(f"Orphan invoices (missing stored file): {len(orphans)}")
    for invoice_id, invoice_no, vendor in orphans:
        print(f"  invoice {invoice_id}: {invoice_no or '?'} / {vendor or '?'}")

    removed = 0
    if orphans:
        removed = await _purge_invoices([row[0] for row in orphans], dry_run=dry_run)
        if dry_run:
            print(f"would purge {removed} invoice(s)")
        else:
            print(f"purged {removed} invoice(s)")

    if legacy_local:
        print("\nLegacy local files:")
        local_removed = _cleanup_legacy_local_files(dry_run=dry_run)
        if dry_run:
            print(f"would remove {local_removed} legacy local path(s)")
        else:
            print(f"removed {local_removed} legacy local path(s)")

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Purge orphan invoice rows and legacy local files")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--legacy-local",
        action="store_true",
        help="Also remove legacy upload-root invoice/, rejected/, reports/, shared JSON",
    )
    args = parser.parse_args()
    return asyncio.run(_run(dry_run=args.dry_run, legacy_local=args.legacy_local))


if __name__ == "__main__":
    raise SystemExit(main())
