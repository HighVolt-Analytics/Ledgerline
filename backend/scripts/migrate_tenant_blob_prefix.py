"""Migrate legacy blob paths and shared JSON stores to tenants/{uuid}/ layout.

Usage (from backend/):
    python scripts/migrate_tenant_blob_prefix.py --dry-run
    python scripts/migrate_tenant_blob_prefix.py
    python scripts/migrate_tenant_blob_prefix.py --tenant-id <uuid>
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

from app.config import get_settings
from app.database import async_session_factory
from app.models.invoice import Invoice
from app.models.tenant import Tenant
from app.services.approval_policy_io import (
    _legacy_policy_path,
    _load_legacy_store as _load_legacy_policy_store,
    _policy_path,
    _save_tenant_policy,
)
from app.services.billing_io import (
    _billing_path,
    _legacy_billing_path,
    _load_legacy_store as _load_legacy_billing_store,
    _save_tenant_state,
)
from app.services.file_storage import relocate_stored_pdf
from app.services.tenant_storage_paths import (
    blob_name_from_stored,
    is_legacy_blob_path,
    legacy_to_tenant_path,
    tenant_root,
)


def _migrate_billing_json(tenant_id: uuid.UUID, *, dry_run: bool) -> bool:
    if _billing_path(tenant_id).is_file():
        return False
    if not _legacy_billing_path().is_file():
        return False
    orgs = _load_legacy_billing_store().get("orgs") or {}
    raw = orgs.get(str(tenant_id))
    if raw is None:
        return False
    state = {
        "balance": int(raw.get("balance", 500)),
        "current_pack": str(raw.get("current_pack", "starter")),
        "auto_recharge": bool(raw.get("auto_recharge", False)),
        "threshold": int(raw.get("threshold", 100)),
    }
    if dry_run:
        print(f"  would migrate billing.json -> tenants/{tenant_id}/billing.json")
        return True
    _save_tenant_state(tenant_id, state)
    print(f"  migrated billing.json -> tenants/{tenant_id}/billing.json")
    return True


def _migrate_policy_json(tenant_id: uuid.UUID, *, dry_run: bool) -> bool:
    if _policy_path(tenant_id).is_file():
        return False
    if not _legacy_policy_path().is_file():
        return False
    orgs = _load_legacy_policy_store().get("orgs") or {}
    raw = orgs.get(str(tenant_id))
    if raw is None:
        return False
    if dry_run:
        print(f"  would migrate approval_policy.json -> tenants/{tenant_id}/approval_policy.json")
        return True
    _save_tenant_policy(tenant_id, raw)
    print(f"  migrated approval_policy.json -> tenants/{tenant_id}/approval_policy.json")
    return True


def _move_report_file(tenant: Tenant, *, dry_run: bool) -> int:
    upload = Path(get_settings().upload_dir)
    legacy_dir = upload / "reports"
    if not legacy_dir.is_dir():
        return 0
    moved = 0
    slug = tenant.slug or "org"
    for path in legacy_dir.glob("*.xlsx"):
        if slug not in path.name:
            continue
        dest_dir = upload / tenant_root(tenant.id) / "reports"
        dest = dest_dir / path.name
        if dest.is_file():
            continue
        if dry_run:
            print(f"  would move report {path.name} -> {dest}")
        else:
            dest_dir.mkdir(parents=True, exist_ok=True)
            path.replace(dest)
            print(f"  moved report {path.name} -> {dest}")
        moved += 1
    return moved


async def _migrate_invoices(tenant_id: uuid.UUID, *, dry_run: bool) -> tuple[int, int]:
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
            if not is_legacy_blob_path(blob_name):
                skipped += 1
                continue
            new_name = legacy_to_tenant_path(tenant_id, blob_name)
            if dry_run:
                print(f"  invoice {inv.id}: would move {blob_name} -> {new_name}")
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

    total_moved = 0
    for tenant in tenants:
        print(f"\nTenant {tenant.slug} ({tenant.id})")
        moved, skipped = await _migrate_invoices(tenant.id, dry_run=dry_run)
        total_moved += moved
        print(f"  invoices: moved={moved} skipped={skipped}")
        _migrate_billing_json(tenant.id, dry_run=dry_run)
        _migrate_policy_json(tenant.id, dry_run=dry_run)
        reports = _move_report_file(tenant, dry_run=dry_run)
        if reports:
            print(f"  reports moved: {reports}")

    print(f"\nDone. invoice blobs moved: {total_moved} dry_run={dry_run}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Migrate storage to tenants/{uuid}/ prefix")
    parser.add_argument("--dry-run", action="store_true", help="Print actions without writing")
    parser.add_argument("--tenant-id", type=str, default=None, help="Limit to one tenant UUID")
    args = parser.parse_args()

    tenant_filter = uuid.UUID(args.tenant_id) if args.tenant_id else None
    return asyncio.run(_run(tenant_filter, dry_run=args.dry_run))


if __name__ == "__main__":
    raise SystemExit(main())
