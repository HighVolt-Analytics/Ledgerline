"""List probable duplicate vendor_masters for manual merge review (Layer 3).

Usage:
  python -m scripts.report_probable_duplicate_vendors --tenant-id <uuid>
"""

from __future__ import annotations

import argparse
import asyncio
import json
import uuid

from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models.tenant import Tenant
from app.services.master_data.vendor_duplicate_report import find_probable_duplicate_vendors


async def _run(tenant_id: uuid.UUID) -> None:
    async with AsyncSessionLocal() as session:
        tenant = await session.get(Tenant, tenant_id)
        if tenant is None:
            raise SystemExit(f"Tenant not found: {tenant_id}")
        pairs = await find_probable_duplicate_vendors(session, tenant_id=tenant_id)
        payload = [
            {
                "left_id": p.left_id,
                "right_id": p.right_id,
                "left_master_id": p.left_master_id,
                "right_master_id": p.right_master_id,
                "left_name": p.left_name,
                "right_name": p.right_name,
                "reasons": list(p.reasons),
                "score": p.score,
            }
            for p in pairs
        ]
        print(json.dumps({"tenant_id": str(tenant_id), "count": len(payload), "pairs": payload}, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description="Report probable duplicate vendors")
    parser.add_argument("--tenant-id", required=True, type=uuid.UUID)
    args = parser.parse_args()
    asyncio.run(_run(args.tenant_id))


if __name__ == "__main__":
    main()
