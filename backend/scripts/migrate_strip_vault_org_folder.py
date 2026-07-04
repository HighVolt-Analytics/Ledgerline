"""Strip redundant org folder from tenant-scoped vault blob paths.

Before: tenants/{uuid}/invoice/Testing/Unrouted/...
After:  tenants/{uuid}/invoice/Unrouted/...

Usage (from backend/):
    python scripts/migrate_strip_vault_org_folder.py --dry-run
    python scripts/migrate_strip_vault_org_folder.py
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

from app.database import async_session_factory
from app.models.invoice import Invoice
from app.models.tenant import Tenant
from app.services.shared.file_storage import relocate_stored_pdf
from app.services.tenant.tenant_storage_paths import blob_name_from_stored
from app.services.vault.vault_paths import strip_org_segment_from_blob_path


async def _migrate_tenant(tenant_id: uuid.UUID, *, dry_run: bool) -> tuple[int, int]:
    moved = 0
    skipped = 0
    async with async_session_factory() as session:
        rows = (
            await session.execute(
                select(Invoice).where(
                    Invoice.tenant_id == tenant_id,
                    Invoice.raw_file_path.isnot(None),
                )
            )
        ).scalars().all()

        for inv in rows:
            stored = inv.raw_file_path
            if not stored:
                skipped += 1
                continue
            blob_name = blob_name_from_stored(stored)
            if not blob_name:
                skipped += 1
                continue
            new_name = strip_org_segment_from_blob_path(blob_name)
            if not new_name or new_name == blob_name:
                skipped += 1
                continue
            if dry_run:
                print(f"  invoice {inv.id}: would move")
                print(f"    from {blob_name}")
                print(f"    to   {new_name}")
                moved += 1
                continue
            try:
                new_stored = relocate_stored_pdf(stored, new_name)
            except Exception as exc:
                print(f"  invoice {inv.id}: FAIL {exc}")
                skipped += 1
                continue
            if new_stored != stored:
                inv.raw_file_path = new_stored
                moved += 1
                print(f"  invoice {inv.id}: moved -> {new_name}")
            else:
                skipped += 1

        if not dry_run and moved:
            await session.commit()
    return moved, skipped


async def _run(tenant_filter: uuid.UUID | None, *, dry_run: bool) -> int:
    async with async_session_factory() as session:
        stmt = select(Tenant)
        if tenant_filter is not None:
            stmt = stmt.where(Tenant.id == tenant_filter)
        tenants = list((await session.execute(stmt)).scalars().all())

    if not tenants:
        print("No tenants found.")
        return 1

    total = 0
    for tenant in tenants:
        print(f"\nTenant {tenant.slug} ({tenant.id})")
        moved, skipped = await _migrate_tenant(tenant.id, dry_run=dry_run)
        total += moved
        print(f"  moved={moved} skipped={skipped}")

    print(f"\nDone. org folders stripped: {total} dry_run={dry_run}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Remove redundant org folder from vault blob paths")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--tenant-id", type=str, default=None)
    args = parser.parse_args()
    tenant_filter = uuid.UUID(args.tenant_id) if args.tenant_id else None
    return asyncio.run(_run(tenant_filter, dry_run=args.dry_run))


if __name__ == "__main__":
    raise SystemExit(main())
