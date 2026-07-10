"""Setup checklist — chart of accounts item reflects functional COA state."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tenant import Tenant
from app.schemas.rule_book_config import ChartOfAccountEntry, PostingDefaults, RuleBookConfigPayload
from app.services.rule_book.rule_book_config_repository import upsert_config
from app.services.tenant.tenant_setup_checklist_service import _coa_functional_for_journaling, _item_done
from app.tenant_ids import TESTING_TENANT_UUID


def _functional_coa_entries() -> list[dict]:
    posting = PostingDefaults(
        tax_account="GST Paid",
        payable_account="Accounts Payable",
        fallback_account="Suspense Account",
    )
    return [
        ChartOfAccountEntry(code="1200", name="Accounts Receivable", type="Asset"),
        ChartOfAccountEntry(code="1400", name=posting.tax_account, type="Asset"),
        ChartOfAccountEntry(code="2000", name=posting.payable_account, type="Liability"),
        ChartOfAccountEntry(code="2300", name="Tax Collected", type="Liability"),
        ChartOfAccountEntry(code="9999", name=posting.fallback_account, type="Liability"),
    ]


@pytest.mark.asyncio
async def test_chart_of_accounts_checklist_incomplete_when_coa_empty(
    db_session: AsyncSession,
) -> None:
    tenant = await db_session.get(Tenant, TESTING_TENANT_UUID)
    assert tenant is not None

    await upsert_config(
        db_session,
        TESTING_TENANT_UUID,
        {
            "schema_version": 1,
            "posting_defaults": PostingDefaults().model_dump(),
            "chart_of_accounts": [],
        },
    )

    done = await _item_done(db_session, tenant=tenant, item_id="chart_of_accounts")
    assert done is False


@pytest.mark.asyncio
async def test_chart_of_accounts_checklist_complete_when_control_accounts_resolve(
    db_session: AsyncSession,
) -> None:
    tenant = await db_session.get(Tenant, TESTING_TENANT_UUID)
    assert tenant is not None

    posting = PostingDefaults(
        tax_account="GST Paid",
        payable_account="Accounts Payable",
        fallback_account="Suspense Account",
    )
    await upsert_config(
        db_session,
        TESTING_TENANT_UUID,
        {
            "schema_version": 1,
            "posting_defaults": posting.model_dump(),
            "chart_of_accounts": [entry.model_dump() for entry in _functional_coa_entries()],
        },
    )

    done = await _item_done(db_session, tenant=tenant, item_id="chart_of_accounts")
    assert done is True


@pytest.mark.asyncio
async def test_chart_of_accounts_checklist_incomplete_when_payable_missing(
    db_session: AsyncSession,
) -> None:
    tenant = await db_session.get(Tenant, TESTING_TENANT_UUID)
    assert tenant is not None

    posting = PostingDefaults(
        tax_account="GST Paid",
        payable_account="Accounts Payable",
        fallback_account="Suspense Account",
    )
    partial = [
        ChartOfAccountEntry(code="1200", name="Accounts Receivable", type="Asset"),
        ChartOfAccountEntry(code="1400", name=posting.tax_account, type="Asset"),
        ChartOfAccountEntry(code="2300", name="Tax Collected", type="Liability"),
        ChartOfAccountEntry(code="9999", name=posting.fallback_account, type="Liability"),
    ]
    await upsert_config(
        db_session,
        TESTING_TENANT_UUID,
        {
            "schema_version": 1,
            "posting_defaults": posting.model_dump(),
            "chart_of_accounts": [entry.model_dump() for entry in partial],
        },
    )

    done = await _item_done(db_session, tenant=tenant, item_id="chart_of_accounts")
    assert done is False


def test_coa_functional_helper_requires_all_control_accounts() -> None:
    posting = PostingDefaults(
        tax_account="GST Paid",
        payable_account="Accounts Payable",
        fallback_account="Suspense Account",
    )
    complete = RuleBookConfigPayload(
        posting_defaults=posting,
        chart_of_accounts=_functional_coa_entries(),
    )
    assert _coa_functional_for_journaling(complete) is True

    missing_ar = RuleBookConfigPayload(
        posting_defaults=posting,
        chart_of_accounts=[
            ChartOfAccountEntry(code="1400", name="GST Paid", type="Asset"),
            ChartOfAccountEntry(code="2000", name="Accounts Payable", type="Liability"),
            ChartOfAccountEntry(code="2300", name="Tax Collected", type="Liability"),
            ChartOfAccountEntry(code="9999", name="Suspense Account", type="Liability"),
        ],
    )
    assert _coa_functional_for_journaling(missing_ar) is False
