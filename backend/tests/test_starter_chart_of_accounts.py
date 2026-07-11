"""Starter chart of accounts seeded at tenant provisioning."""

import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import Invoice
from app.models.tenant import Tenant
from app.models.tenant_rule_book_config import TenantRuleBookConfig
from app.schemas.rule_book_config import PostingDefaults, validate_rule_book_config_payload
from app.services.master_data.starter_chart_of_accounts import (
    GENERIC_EXPENSE_ACCOUNT,
    GENERIC_REVENUE_ACCOUNT,
    SALES_RECEIVABLE_ACCOUNT,
    SALES_TAX_ACCOUNT,
    build_starter_chart_of_accounts,
    merge_missing_starter_accounts,
)
from app.services.payments.journal_generator import (
    generate_entries,
    get_unresolved_control_accounts,
    is_balanced,
)
from app.services.rule_book.account_mapper import AccountMapping, category_resolved_in_coa
from app.services.rule_book.rule_book_config_repository import (
    ensure_default_config,
    fetch_config_dict,
    upgrade_tenant_coa_if_needed,
)
from app.services.rule_book.rule_book_mapper import ROUTE_SALES


async def _add_tenant(
    session: AsyncSession,
    *,
    country: str,
    slug_suffix: str,
) -> uuid.UUID:
    tenant_id = uuid.uuid4()
    session.add(
        Tenant(
            id=tenant_id,
            name=f"Starter COA {slug_suffix}",
            slug=f"starter-{slug_suffix}-{tenant_id.hex[:8]}",
            settings_json={"country": country},
        )
    )
    await session.flush()
    return tenant_id


@pytest.mark.asyncio
async def test_new_tenant_starter_coa_resolves_posting_defaults(db_session: AsyncSession) -> None:
    tenant_id = await _add_tenant(db_session, country="GB", slug_suffix="gb")

    raw = await ensure_default_config(db_session, tenant_id)
    config = validate_rule_book_config_payload(raw)

    assert category_resolved_in_coa(config.posting_defaults.payable_account, config)
    assert category_resolved_in_coa(config.posting_defaults.tax_account, config)
    assert category_resolved_in_coa(config.posting_defaults.fallback_account, config)


@pytest.mark.asyncio
async def test_starter_coa_country_specific_tax_account_names(db_session: AsyncSession) -> None:
    gb_id = await _add_tenant(db_session, country="GB", slug_suffix="gb-tax")
    au_id = await _add_tenant(db_session, country="AU", slug_suffix="au-tax")

    gb_config = validate_rule_book_config_payload(await ensure_default_config(db_session, gb_id))
    au_config = validate_rule_book_config_payload(await ensure_default_config(db_session, au_id))

    gb_names = {entry.name for entry in gb_config.chart_of_accounts}
    au_names = {entry.name for entry in au_config.chart_of_accounts}

    assert "VAT Input" in gb_names
    assert gb_config.posting_defaults.tax_account == "VAT Input"
    assert "GST Paid" in au_names
    assert au_config.posting_defaults.tax_account == "GST Paid"


def test_build_starter_chart_of_accounts_includes_both_routes() -> None:
    entries = build_starter_chart_of_accounts("AU")
    names = {entry.name for entry in entries}

    assert SALES_RECEIVABLE_ACCOUNT in names
    assert SALES_TAX_ACCOUNT in names
    assert GENERIC_EXPENSE_ACCOUNT in names
    assert GENERIC_REVENUE_ACCOUNT in names
    assert "GST Paid" in names
    assert "Accounts Payable" in names
    assert "Bank Account" in names
    assert "Suspense Account" in names
    assert len(entries) == 8


@pytest.mark.asyncio
async def test_starter_coa_supports_purchase_and_sales_journals(db_session: AsyncSession) -> None:
    tenant_id = await _add_tenant(db_session, country="AU", slug_suffix="journal")

    raw = await ensure_default_config(db_session, tenant_id)
    config = validate_rule_book_config_payload(raw)

    purchase = Invoice(
        tenant_id=tenant_id,
        invoice_date=date(2026, 6, 14),
        subtotal=Decimal("1000"),
        gst=Decimal("100"),
        total=Decimal("1100"),
        route_target="Purchase Management",
        currency="AUD",
    )
    sales = Invoice(
        tenant_id=tenant_id,
        invoice_date=date(2026, 6, 14),
        subtotal=Decimal("500"),
        gst=Decimal("50"),
        total=Decimal("550"),
        route_target=ROUTE_SALES,
        currency="AUD",
    )
    expense_mapping = AccountMapping("6100", GENERIC_EXPENSE_ACCOUNT)
    revenue_mapping = AccountMapping("4100", GENERIC_REVENUE_ACCOUNT)

    assert get_unresolved_control_accounts(invoice=purchase, config=config) == []
    assert get_unresolved_control_accounts(invoice=sales, config=config) == []

    purchase_lines = generate_entries(purchase, expense_mapping, config=config)
    sales_lines = generate_entries(sales, revenue_mapping, config=config)

    assert is_balanced(purchase_lines)
    assert is_balanced(sales_lines)


@pytest.mark.asyncio
async def test_ensure_default_config_leaves_existing_custom_coa_untouched(
    db_session: AsyncSession,
) -> None:
    tenant_id = await _add_tenant(db_session, country="AU", slug_suffix="custom")
    custom_coa = [
        {"code": "1000", "name": "Legacy Expense", "type": "Expense"},
        {"code": "2000", "name": "Legacy Payable", "type": "Liability"},
    ]
    db_session.add(
        TenantRuleBookConfig(
            tenant_id=tenant_id,
            config={
                "schema_version": 1,
                "posting_defaults": {
                    "tax_account": "Legacy Tax",
                    "payable_account": "Legacy Payable",
                    "fallback_account": "Legacy Suspense",
                },
                "chart_of_accounts": custom_coa,
            },
            schema_version=1,
        )
    )
    await db_session.flush()

    loaded = await ensure_default_config(db_session, tenant_id)

    assert len(loaded["chart_of_accounts"]) == 2
    assert loaded["chart_of_accounts"] == custom_coa
    stored = await fetch_config_dict(db_session, tenant_id)
    assert stored is not None
    assert stored["chart_of_accounts"] == custom_coa


def test_merge_missing_starter_accounts_preserves_custom_entries() -> None:
    thin = [
        build_starter_chart_of_accounts("AU")[0].model_copy(update={"code": "1000", "name": "Bank Account"}),
        build_starter_chart_of_accounts("AU")[0].model_copy(
            update={"code": "6130", "name": "Marketing Expense", "type": "Expense"}
        ),
    ]
    merged = merge_missing_starter_accounts(thin, "AU")
    names = {entry.name for entry in merged}
    assert "Marketing Expense" in names
    assert SALES_RECEIVABLE_ACCOUNT in names
    assert "Accounts Payable" in names
    assert "GST Paid" in names
    assert len(merged) >= 8


@pytest.mark.asyncio
async def test_upgrade_tenant_coa_if_needed_merges_thin_coa(db_session: AsyncSession) -> None:
    tenant_id = await _add_tenant(db_session, country="AU", slug_suffix="thin-upgrade")
    custom_coa = [
        {"code": "1000", "name": "Bank Account", "type": "Asset"},
        {"code": "6130", "name": "Marketing Expense", "type": "Expense"},
        {"code": "6140", "name": "R&D Expense", "type": "Expense"},
    ]
    db_session.add(
        TenantRuleBookConfig(
            tenant_id=tenant_id,
            config={
                "schema_version": 1,
                "posting_defaults": PostingDefaults.for_country("AU").model_dump(),
                "chart_of_accounts": custom_coa,
            },
            schema_version=1,
        )
    )
    await db_session.flush()

    changed = await upgrade_tenant_coa_if_needed(db_session, tenant_id)
    assert changed is True
    stored = validate_rule_book_config_payload(await fetch_config_dict(db_session, tenant_id) or {})
    assert category_resolved_in_coa(stored.posting_defaults.payable_account, stored)
    assert category_resolved_in_coa(SALES_RECEIVABLE_ACCOUNT, stored)


@pytest.mark.asyncio
async def test_upgrade_tenant_coa_if_needed_is_idempotent(db_session: AsyncSession) -> None:
    tenant_id = await _add_tenant(db_session, country="AU", slug_suffix="idempotent")
    await ensure_default_config(db_session, tenant_id)
    assert await upgrade_tenant_coa_if_needed(db_session, tenant_id) is False
