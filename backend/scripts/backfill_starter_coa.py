#!/usr/bin/env python3
"""Merge missing starter COA control accounts for one or all tenants."""

from __future__ import annotations

import argparse
import asyncio
import uuid

from sqlalchemy import select

from app.database import async_session_factory
from app.models.tenant import Tenant
from app.services.rule_book.rule_book_config_repository import (
    fetch_config_dict,
    upgrade_tenant_coa_if_needed,
)
from app.schemas.rule_book_config import validate_rule_book_config_payload
from app.services.rule_book.account_mapper import coa_functional_for_journaling


async def _run(*, tenant_id: uuid.UUID | None, dry_run: bool) -> None:
    async with async_session_factory() as session:
        if tenant_id is not None:
            tenant_ids = [tenant_id]
        else:
            tenant_ids = list(
                (
                    await session.execute(
                        select(Tenant.id).where(Tenant.is_active.is_(True))
                    )
                ).scalars().all()
            )

        upgraded = 0
        for tid in tenant_ids:
            before = await fetch_config_dict(session, tid)
            if before is None:
                print(f"skip {tid}: no rule book config")
                continue
            before_cfg = validate_rule_book_config_payload(before)
            functional_before = coa_functional_for_journaling(before_cfg)
            if dry_run:
                print(
                    f"{tid}: coa_accounts={len(before_cfg.chart_of_accounts)} "
                    f"functional={functional_before}"
                )
                continue
            changed = await upgrade_tenant_coa_if_needed(session, tid)
            if changed:
                upgraded += 1
                after = await fetch_config_dict(session, tid)
                after_cfg = validate_rule_book_config_payload(after or {})
                print(
                    f"upgraded {tid}: {len(before_cfg.chart_of_accounts)} -> "
                    f"{len(after_cfg.chart_of_accounts)} accounts "
                    f"functional={coa_functional_for_journaling(after_cfg)}"
                )
            else:
                print(f"unchanged {tid}: functional={functional_before}")

        if not dry_run:
            await session.commit()
        print(f"done: upgraded={upgraded} tenants={len(tenant_ids)}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tenant", type=uuid.UUID, default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    asyncio.run(_run(tenant_id=args.tenant, dry_run=args.dry_run))


if __name__ == "__main__":
    main()
