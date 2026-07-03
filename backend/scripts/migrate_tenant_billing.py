"""Seed tenant billing rows, assign countries, and set Free/Studio plans for existing clients.

Run after migration 053:

    cd backend && python -m scripts.migrate_tenant_billing
"""

from __future__ import annotations

import asyncio
import random
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

from app.database import async_session_factory
from app.models.tenant import Tenant
from app.models.tenant_billing import TenantBilling
from app.services.credit_catalog import PLAN_FREE, PLAN_STUDIO, monthly_credits_for_plan
from app.services.credit_service import ensure_tenant_billing
from app.tenant_settings import merge_institution_settings, tenant_country

COUNTRIES = ["IN", "SG", "AU"]


async def migrate() -> None:
    random.shuffle(COUNTRIES)
    async with async_session_factory() as session:
        tenants = (
            await session.execute(
                select(Tenant).where(Tenant.is_platform.is_(False)).order_by(Tenant.created_at)
            )
        ).scalars().all()

        migrated = 0
        for index, tenant in enumerate(tenants):
            country = COUNTRIES[index % len(COUNTRIES)]
            if tenant_country(tenant) not in {"IN", "SG", "AU"}:
                tenant.settings_json = merge_institution_settings(
                    tenant.settings_json,
                    country=country,
                )
            else:
                country = tenant_country(tenant)

            plan = PLAN_STUDIO if index % 2 == 0 else PLAN_FREE
            await ensure_tenant_billing(session, tenant.id, plan=plan)
            credits = monthly_credits_for_plan(country_code=country, plan=plan)
            billing = await session.get(TenantBilling, tenant.id)
            if billing:
                billing.credit_balance = credits
                billing.plan = plan
                billing.billing_anchor_date = date.today()
                billing.last_monthly_grant_at = date.today()
            migrated += 1

        await session.commit()
        print(f"Migrated billing for {migrated} tenant(s).")


if __name__ == "__main__":
    asyncio.run(migrate())
