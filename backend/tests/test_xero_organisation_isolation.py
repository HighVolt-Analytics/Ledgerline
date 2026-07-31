"""Organisation isolation: mapping scope, switch deactivate, reconnect counts."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.models.accounting_entity_mapping import (
    MAPPING_GL_ACCOUNT,
    MAPPING_SUPPLIER,
    AccountingEntityMapping,
)
from app.models.accounting_export_ledger import STATUS_SUCCESS, AccountingExportLedger
from app.models.accounting_integration import (
    AccountingIntegration,
    AccountingIntegrationStatus,
    AccountingProvider,
)
from app.models.invoice import Invoice, InvoiceStatus
from app.models.xero_account import XeroAccount
from app.models.xero_connection import XeroConnection
from app.models.xero_contact import XeroContact
from app.models.xero_currency import XeroCurrency
from app.models.xero_tax_rate import XeroTaxRate
from app.services.integration.accounting_integration_service import select_xero_connection
from app.services.integration.accounting_mapping_service import (
    get_mapping,
    list_mappings,
    upsert_mapping,
)
from app.services.integration.xero_master_data_service import get_master_data_totals
from app.services.shared.token_vault import encrypt_secret
from app.tenant_ids import TESTING_TENANT_UUID


async def _seed_integration_with_orgs(
    db_session,
    *,
    selected: str = "org-a",
) -> AccountingIntegration:
    integration = AccountingIntegration(
        tenant_id=TESTING_TENANT_UUID,
        provider=AccountingProvider.XERO.value,
        status=AccountingIntegrationStatus.CONNECTED.value,
        provider_tenant_id=selected,
        display_name="Org A" if selected == "org-a" else "Org B",
        access_token_encrypted=encrypt_secret("access"),
        refresh_token_encrypted=encrypt_secret("refresh"),
        expires_at=datetime.now(timezone.utc),
    )
    db_session.add(integration)
    await db_session.flush()
    for conn_id, tenant_id, name, is_selected in (
        ("conn-a", "org-a", "Org A", selected == "org-a"),
        ("conn-b", "org-b", "Org B", selected == "org-b"),
    ):
        db_session.add(
            XeroConnection(
                accounting_integration_id=integration.id,
                tenant_id=TESTING_TENANT_UUID,
                xero_connection_id=conn_id,
                xero_tenant_id=tenant_id,
                xero_tenant_type="ORGANISATION",
                xero_tenant_name=name,
                active=True,
                selected=is_selected,
            )
        )
    await db_session.flush()
    return integration


async def _seed_org_master(
    db_session,
    *,
    integration_id: int,
    xero_tenant_id: str,
    account_code: str,
) -> None:
    db_session.add(
        XeroAccount(
            tenant_id=TESTING_TENANT_UUID,
            accounting_integration_id=integration_id,
            xero_tenant_id=xero_tenant_id,
            xero_account_id=f"acc-{xero_tenant_id}-{account_code}",
            code=account_code,
            name=f"Account {account_code}",
            status="ACTIVE",
            sync_status="active",
        )
    )
    db_session.add(
        XeroTaxRate(
            tenant_id=TESTING_TENANT_UUID,
            accounting_integration_id=integration_id,
            xero_tenant_id=xero_tenant_id,
            tax_type=f"INPUT-{xero_tenant_id}",
            name="GST",
            status="ACTIVE",
            sync_status="active",
        )
    )
    db_session.add(
        XeroContact(
            tenant_id=TESTING_TENANT_UUID,
            accounting_integration_id=integration_id,
            xero_tenant_id=xero_tenant_id,
            xero_contact_id=f"contact-{xero_tenant_id}",
            name=f"Supplier {xero_tenant_id}",
            sync_status="active",
        )
    )
    db_session.add(
        XeroCurrency(
            tenant_id=TESTING_TENANT_UUID,
            accounting_integration_id=integration_id,
            xero_tenant_id=xero_tenant_id,
            code="AUD",
            description="Australian Dollar",
            sync_status="active",
        )
    )
    await db_session.flush()


@pytest.mark.asyncio
async def test_mappings_are_scoped_by_xero_tenant_id(db_session):
    integration = await _seed_integration_with_orgs(db_session, selected="org-a")
    await _seed_org_master(
        db_session, integration_id=integration.id, xero_tenant_id="org-a", account_code="400"
    )
    await _seed_org_master(
        db_session, integration_id=integration.id, xero_tenant_id="org-b", account_code="400"
    )

    await upsert_mapping(
        db_session,
        tenant_id=TESTING_TENANT_UUID,
        mapping_type=MAPPING_GL_ACCOUNT,
        source_key="400",
        external_code="400",
        user_id=1,
        xero_tenant_id="org-a",
    )
    await upsert_mapping(
        db_session,
        tenant_id=TESTING_TENANT_UUID,
        mapping_type=MAPPING_GL_ACCOUNT,
        source_key="400",
        external_code="400",
        user_id=1,
        xero_tenant_id="org-b",
    )

    a_rows = await list_mappings(
        db_session,
        tenant_id=TESTING_TENANT_UUID,
        xero_tenant_id="org-a",
        active_only=True,
    )
    b_rows = await list_mappings(
        db_session,
        tenant_id=TESTING_TENANT_UUID,
        xero_tenant_id="org-b",
        active_only=True,
    )
    assert len(a_rows) == 1
    assert len(b_rows) == 1
    assert a_rows[0].xero_tenant_id == "org-a"
    assert b_rows[0].xero_tenant_id == "org-b"

    assert (
        await get_mapping(
            db_session,
            tenant_id=TESTING_TENANT_UUID,
            mapping_type=MAPPING_GL_ACCOUNT,
            source_key="400",
            xero_tenant_id="org-a",
        )
    ) is not None


@pytest.mark.asyncio
async def test_same_org_reconnect_keeps_active_master_and_mappings(db_session):
    integration = await _seed_integration_with_orgs(db_session, selected="org-a")
    await _seed_org_master(
        db_session, integration_id=integration.id, xero_tenant_id="org-a", account_code="200"
    )
    await upsert_mapping(
        db_session,
        tenant_id=TESTING_TENANT_UUID,
        mapping_type=MAPPING_GL_ACCOUNT,
        source_key="200",
        external_code="200",
        user_id=1,
        xero_tenant_id="org-a",
    )

    before = await get_master_data_totals(db_session, TESTING_TENANT_UUID)
    assert before["accounts"] == 1

    await select_xero_connection(
        db_session,
        tenant_id=TESTING_TENANT_UUID,
        xero_connection_id="conn-a",
    )

    after = await get_master_data_totals(db_session, TESTING_TENANT_UUID)
    assert after["accounts"] == 1
    assert after["tax_rates"] == 1
    assert after["contacts"] == 1
    assert after["currencies"] == 1

    mapping = await get_mapping(
        db_session,
        tenant_id=TESTING_TENANT_UUID,
        mapping_type=MAPPING_GL_ACCOUNT,
        source_key="200",
        xero_tenant_id="org-a",
    )
    assert mapping is not None
    assert mapping.is_active is True


@pytest.mark.asyncio
async def test_different_org_switch_deactivates_prior_and_preserves_exports(db_session):
    integration = await _seed_integration_with_orgs(db_session, selected="org-a")
    await _seed_org_master(
        db_session, integration_id=integration.id, xero_tenant_id="org-a", account_code="200"
    )
    await _seed_org_master(
        db_session, integration_id=integration.id, xero_tenant_id="org-b", account_code="300"
    )
    await upsert_mapping(
        db_session,
        tenant_id=TESTING_TENANT_UUID,
        mapping_type=MAPPING_GL_ACCOUNT,
        source_key="200",
        external_code="200",
        user_id=1,
        xero_tenant_id="org-a",
    )
    await upsert_mapping(
        db_session,
        tenant_id=TESTING_TENANT_UUID,
        mapping_type=MAPPING_SUPPLIER,
        source_key="acme",
        external_id="contact-org-a",
        user_id=1,
        xero_tenant_id="org-a",
    )

    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Acme",
        invoice_no="INV-ORG-1",
        invoice_date=date(2026, 1, 15),
        currency="AUD",
        subtotal=Decimal("100.00"),
        gst=Decimal("10.00"),
        total=Decimal("110.00"),
        status=InvoiceStatus.PROCESSED,
        account_code="200",
    )
    db_session.add(inv)
    await db_session.flush()

    ledger = AccountingExportLedger(
        tenant_id=TESTING_TENANT_UUID,
        provider="xero",
        qll_transaction_id=str(uuid.uuid4()),
        source_invoice_id=inv.id,
        source_document_id=f"DOC-{inv.id}",
        transaction_type="SUPPLIER_INVOICE",
        direction="OUTBOUND",
        status=STATUS_SUCCESS,
        payload_version=1,
        payload_hash="hash-preserve",
        idempotency_key="idem-preserve",
        external_id="xero-invoice-1",
        external_status="DRAFT",
        attempt_count=1,
    )
    db_session.add(ledger)
    await db_session.flush()
    ledger_id = ledger.id

    totals_a = await get_master_data_totals(db_session, TESTING_TENANT_UUID)
    assert totals_a["accounts"] == 1

    await select_xero_connection(
        db_session,
        tenant_id=TESTING_TENANT_UUID,
        xero_connection_id="conn-b",
    )

    inactive_accounts = int(
        (
            await db_session.execute(
                select(func.count()).select_from(XeroAccount).where(
                    XeroAccount.tenant_id == TESTING_TENANT_UUID,
                    XeroAccount.xero_tenant_id == "org-a",
                    XeroAccount.sync_status == "inactive",
                )
            )
        ).scalar_one()
        or 0
    )
    assert inactive_accounts == 1

    mapping_a = (
        await db_session.execute(
            select(AccountingEntityMapping).where(
                AccountingEntityMapping.tenant_id == TESTING_TENANT_UUID,
                AccountingEntityMapping.xero_tenant_id == "org-a",
                AccountingEntityMapping.mapping_type == MAPPING_GL_ACCOUNT,
            )
        )
    ).scalar_one()
    assert mapping_a.is_active is False

    totals_b = await get_master_data_totals(db_session, TESTING_TENANT_UUID)
    assert totals_b["accounts"] == 1
    assert totals_b["contacts"] == 1
    listed = await list_mappings(
        db_session,
        tenant_id=TESTING_TENANT_UUID,
        xero_tenant_id="org-b",
        active_only=True,
    )
    assert listed == []

    preserved = (
        await db_session.execute(
            select(AccountingExportLedger).where(AccountingExportLedger.id == ledger_id)
        )
    ).scalar_one()
    assert preserved.status == STATUS_SUCCESS
    assert preserved.external_id == "xero-invoice-1"


@pytest.mark.asyncio
async def test_master_totals_ignore_other_organisation_active_rows(db_session):
    integration = await _seed_integration_with_orgs(db_session, selected="org-a")
    await _seed_org_master(
        db_session, integration_id=integration.id, xero_tenant_id="org-a", account_code="200"
    )
    await _seed_org_master(
        db_session, integration_id=integration.id, xero_tenant_id="org-b", account_code="300"
    )
    totals = await get_master_data_totals(db_session, TESTING_TENANT_UUID)
    assert totals["accounts"] == 1
    assert totals["tax_rates"] == 1
    assert totals["contacts"] == 1
    assert totals["currencies"] == 1

    other = await get_master_data_totals(
        db_session, TESTING_TENANT_UUID, xero_tenant_id="org-b"
    )
    assert other["accounts"] == 1
