"""Verify invoice blob paths are scoped under tenants/{tenant_id}/.

Usage (from backend/):
    python scripts/check_tenant_blob_paths.py

Exit code 0 = all checks passed, 1 = failures found.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

from app.database import async_session_factory
from app.models.invoice import Invoice
from app.models.tenant import Tenant
from app.services.tenant.tenant_storage_paths import blob_name_from_stored, tenant_root


async def main() -> int:
    failures: list[str] = []
    legacy: list[str] = []
    ok = 0

    async with async_session_factory() as session:
        rows = (
            await session.execute(
                select(Invoice.id, Invoice.tenant_id, Invoice.raw_file_path).where(
                    Invoice.raw_file_path.isnot(None)
                )
            )
        ).all()

        tenant_slugs = {
            t.id: t.slug
            for t in (await session.execute(select(Tenant))).scalars().all()
        }

    print(f"Checking {len(rows)} invoice file path(s).\n")

    for invoice_id, tenant_id, stored in rows:
        blob_name = blob_name_from_stored(stored)
        if not blob_name:
            failures.append(f"invoice {invoice_id}: could not parse path {stored!r}")
            continue
        expected_prefix = f"{tenant_root(tenant_id)}/"
        if blob_name.startswith(expected_prefix):
            ok += 1
            continue
        if blob_name.startswith("invoice/") or blob_name.startswith("rejected/"):
            legacy.append(
                f"invoice {invoice_id} (tenant {tenant_slugs.get(tenant_id, tenant_id)}): "
                f"legacy path {blob_name}"
            )
            continue
        failures.append(
            f"invoice {invoice_id}: path {blob_name!r} not under {expected_prefix}"
        )

    print(f"OK (tenant-prefixed): {ok}")
    if legacy:
        print(f"\nLegacy paths (run migrate_tenant_blob_prefix.py): {len(legacy)}")
        for line in legacy[:20]:
            print(f"  - {line}")
        if len(legacy) > 20:
            print(f"  ... and {len(legacy) - 20} more")
    if failures:
        print(f"\nFailures: {len(failures)}")
        for line in failures:
            print(f"  - {line}")

    if failures:
        return 1
    if legacy:
        print("\nPass with warnings — legacy paths remain until migration runs.")
    else:
        print("\nAll stored paths are tenant-scoped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
