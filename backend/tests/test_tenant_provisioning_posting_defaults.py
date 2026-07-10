"""Tenant provisioning — jurisdiction-aware posting defaults."""

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tenant import Tenant
from app.models.tenant_rule_book_config import TenantRuleBookConfig
from app.services.rule_book.rule_book_config_repository import ensure_default_config, fetch_config_dict


async def _add_tenant(
    session: AsyncSession,
    *,
    country: str | None,
    slug_suffix: str,
) -> uuid.UUID:
    tenant_id = uuid.uuid4()
    settings: dict[str, str] = {}
    if country is not None:
        settings["country"] = country
    session.add(
        Tenant(
            id=tenant_id,
            name=f"Provision Test {slug_suffix}",
            slug=f"provision-{slug_suffix}-{tenant_id.hex[:8]}",
            settings_json=settings,
        )
    )
    await session.flush()
    return tenant_id


@pytest.mark.asyncio
async def test_ensure_default_config_gb_posting_defaults(db_session: AsyncSession) -> None:
    tenant_id = await _add_tenant(db_session, country="GB", slug_suffix="gb")

    config = await ensure_default_config(db_session, tenant_id)

    assert config["posting_defaults"]["tax_account"] == "VAT Input"
    assert config["posting_defaults"]["payable_account"] == "Accounts Payable"
    assert config["posting_defaults"]["fallback_account"] == "Suspense Account"


@pytest.mark.asyncio
async def test_ensure_default_config_unknown_country_uses_generic_posting_defaults(
    db_session: AsyncSession,
) -> None:
    tenant_id = await _add_tenant(db_session, country="ZZ", slug_suffix="zz")

    config = await ensure_default_config(db_session, tenant_id)

    assert config["posting_defaults"]["tax_account"] == "Tax Paid"
    assert config["posting_defaults"]["payable_account"] == "Accounts Payable"


@pytest.mark.asyncio
async def test_ensure_default_config_does_not_mutate_existing_tenant(
    db_session: AsyncSession,
) -> None:
    tenant_id = await _add_tenant(db_session, country="AU", slug_suffix="existing")
    custom = {
        "schema_version": 1,
        "posting_defaults": {
            "tax_account": "Custom Tax",
            "payable_account": "Custom Payable",
            "fallback_account": "Custom Suspense",
        },
        "chart_of_accounts": [
            {"code": "1000", "name": "Custom Expense", "type": "Expense"},
            {"code": "2000", "name": "Custom Payable", "type": "Liability"},
        ],
    }
    db_session.add(
        TenantRuleBookConfig(
            tenant_id=tenant_id,
            config=custom,
            schema_version=1,
        )
    )
    await db_session.flush()

    loaded = await ensure_default_config(db_session, tenant_id)

    assert loaded["posting_defaults"]["tax_account"] == "Custom Tax"
    assert len(loaded["chart_of_accounts"]) == 2
    assert loaded["chart_of_accounts"][0]["name"] == "Custom Expense"

    stored = await fetch_config_dict(db_session, tenant_id)
    assert stored == loaded
