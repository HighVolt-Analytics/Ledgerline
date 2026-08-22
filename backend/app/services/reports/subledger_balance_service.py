"""Per-vendor AP and per-customer AR balances from journal entries."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.customer import CustomerRegistry
from app.models.invoice import Invoice, InvoiceStatus
from app.models.journal import JournalEntry
from app.models.tenant import Tenant
from app.models.vendor import VendorRegistry
from app.schemas.subledger import (
    SubledgerBalanceRow,
    SubledgerBalancesResponse,
    SubledgerTotals,
    SubledgerUnregisteredBucket,
)
from app.services.invoice.invoice_evaluation_service import load_posting_config_for_tenant
from app.services.master_data.party_coa_subledger_service import control_account_codes_for_parent
from app.services.reports.dashboard_service import _institution_today
from app.services.rule_book.rule_book_mapper import (
    get_payable_account_mapping,
    get_receivable_account_mapping,
)
from app.tenant_settings import tenant_currency


async def _tenant_base_currency(db: AsyncSession, tenant_id: uuid.UUID) -> str:
    tenant = await db.get(Tenant, tenant_id)
    return tenant_currency(tenant)


def _balance_expr_ap():
    return func.coalesce(func.sum(JournalEntry.credit - JournalEntry.debit), 0)


def _balance_expr_ar():
    return func.coalesce(func.sum(JournalEntry.debit - JournalEntry.credit), 0)


async def fetch_ap_balances(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    as_of: date | None = None,
    include_unregistered: bool = True,
    limit: int = 100,
    offset: int = 0,
) -> SubledgerBalancesResponse:
    if as_of is None:
        as_of = await _institution_today(db, tenant_id)
    config = await load_posting_config_for_tenant(db, tenant_id)
    payable = get_payable_account_mapping(config)
    control_codes = control_account_codes_for_parent(config, payable)
    base_currency = await _tenant_base_currency(db, tenant_id)

    base_filters = [
        JournalEntry.tenant_id == tenant_id,
        JournalEntry.date <= as_of,
        JournalEntry.account_code.in_(control_codes),
        Invoice.status == InvoiceStatus.PROCESSED,
    ]

    registered_stmt = (
        select(
            JournalEntry.vendor_registry_id,
            VendorRegistry.vendor_slug,
            VendorRegistry.vendor_name,
            VendorRegistry.abn,
            VendorRegistry.approved,
            _balance_expr_ap().label("balance"),
            func.count(func.distinct(JournalEntry.invoice_id)).label("document_count"),
            func.max(JournalEntry.date).label("last_activity_date"),
        )
        .join(Invoice, Invoice.id == JournalEntry.invoice_id)
        .join(VendorRegistry, VendorRegistry.id == JournalEntry.vendor_registry_id)
        .where(*base_filters, JournalEntry.vendor_registry_id.is_not(None))
        .group_by(
            JournalEntry.vendor_registry_id,
            VendorRegistry.vendor_slug,
            VendorRegistry.vendor_name,
            VendorRegistry.abn,
            VendorRegistry.approved,
        )
        .having(_balance_expr_ap() != 0)
        .order_by(_balance_expr_ap().desc())
        .limit(limit)
        .offset(offset)
    )
    registered_rows = (await db.execute(registered_stmt)).all()

    rows = [
        SubledgerBalanceRow(
            registry_id=int(vendor_id),
            slug=str(slug or ""),
            name=str(name or ""),
            abn=abn,
            approved=bool(approved),
            balance=Decimal(str(balance or 0)),
            document_count=int(document_count or 0),
            last_activity_date=last_activity,
        )
        for vendor_id, slug, name, abn, approved, balance, document_count, last_activity in registered_rows
    ]

    unregistered = SubledgerUnregisteredBucket()
    if include_unregistered:
        unreg_stmt = (
            select(
                _balance_expr_ap(),
                func.count(func.distinct(JournalEntry.invoice_id)),
            )
            .join(Invoice, Invoice.id == JournalEntry.invoice_id)
            .where(*base_filters, JournalEntry.vendor_registry_id.is_(None))
        )
        unreg_balance, unreg_count = (await db.execute(unreg_stmt)).one()
        unregistered = SubledgerUnregisteredBucket(
            balance=Decimal(str(unreg_balance or 0)),
            document_count=int(unreg_count or 0),
        )

    # Totals over all counterparties (not just the current page).
    party_balances = (
        select(
            JournalEntry.vendor_registry_id.label("party_id"),
            _balance_expr_ap().label("balance"),
        )
        .join(Invoice, Invoice.id == JournalEntry.invoice_id)
        .where(*base_filters, JournalEntry.vendor_registry_id.is_not(None))
        .group_by(JournalEntry.vendor_registry_id)
        .having(_balance_expr_ap() != 0)
        .subquery()
    )
    totals_row = (
        await db.execute(
            select(
                func.coalesce(func.sum(party_balances.c.balance), 0),
                func.count(),
            )
        )
    ).one()
    total_balance = Decimal(str(totals_row[0] or 0))
    party_count = int(totals_row[1] or 0)
    if include_unregistered:
        total_balance += unregistered.balance

    return SubledgerBalancesResponse(
        base_currency=base_currency,
        as_of=as_of,
        control_account_code=payable.account_code,
        control_account_name=payable.account_name,
        rows=rows,
        unregistered=unregistered,
        totals=SubledgerTotals(
            balance=total_balance,
            counterparty_count=party_count
            + (1 if include_unregistered and unregistered.balance != 0 else 0),
        ),
    )


async def fetch_ar_balances(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    as_of: date | None = None,
    include_unregistered: bool = True,
    limit: int = 100,
    offset: int = 0,
) -> SubledgerBalancesResponse:
    if as_of is None:
        as_of = await _institution_today(db, tenant_id)
    config = await load_posting_config_for_tenant(db, tenant_id)
    receivable = get_receivable_account_mapping(config)
    control_codes = control_account_codes_for_parent(config, receivable)
    base_currency = await _tenant_base_currency(db, tenant_id)

    base_filters = [
        JournalEntry.tenant_id == tenant_id,
        JournalEntry.date <= as_of,
        JournalEntry.account_code.in_(control_codes),
        Invoice.status == InvoiceStatus.PROCESSED,
    ]

    registered_stmt = (
        select(
            JournalEntry.customer_registry_id,
            CustomerRegistry.customer_slug,
            CustomerRegistry.customer_name,
            CustomerRegistry.abn,
            CustomerRegistry.approved,
            _balance_expr_ar().label("balance"),
            func.count(func.distinct(JournalEntry.invoice_id)).label("document_count"),
            func.max(JournalEntry.date).label("last_activity_date"),
        )
        .join(Invoice, Invoice.id == JournalEntry.invoice_id)
        .join(CustomerRegistry, CustomerRegistry.id == JournalEntry.customer_registry_id)
        .where(*base_filters, JournalEntry.customer_registry_id.is_not(None))
        .group_by(
            JournalEntry.customer_registry_id,
            CustomerRegistry.customer_slug,
            CustomerRegistry.customer_name,
            CustomerRegistry.abn,
            CustomerRegistry.approved,
        )
        .having(_balance_expr_ar() != 0)
        .order_by(_balance_expr_ar().desc())
        .limit(limit)
        .offset(offset)
    )
    registered_rows = (await db.execute(registered_stmt)).all()

    rows = [
        SubledgerBalanceRow(
            registry_id=int(customer_id),
            slug=str(slug or ""),
            name=str(name or ""),
            abn=abn,
            approved=bool(approved),
            balance=Decimal(str(balance or 0)),
            document_count=int(document_count or 0),
            last_activity_date=last_activity,
        )
        for customer_id, slug, name, abn, approved, balance, document_count, last_activity in registered_rows
    ]

    unregistered = SubledgerUnregisteredBucket()
    if include_unregistered:
        unreg_stmt = (
            select(
                _balance_expr_ar(),
                func.count(func.distinct(JournalEntry.invoice_id)),
            )
            .join(Invoice, Invoice.id == JournalEntry.invoice_id)
            .where(*base_filters, JournalEntry.customer_registry_id.is_(None))
        )
        unreg_balance, unreg_count = (await db.execute(unreg_stmt)).one()
        unregistered = SubledgerUnregisteredBucket(
            balance=Decimal(str(unreg_balance or 0)),
            document_count=int(unreg_count or 0),
        )

    party_balances = (
        select(
            JournalEntry.customer_registry_id.label("party_id"),
            _balance_expr_ar().label("balance"),
        )
        .join(Invoice, Invoice.id == JournalEntry.invoice_id)
        .where(*base_filters, JournalEntry.customer_registry_id.is_not(None))
        .group_by(JournalEntry.customer_registry_id)
        .having(_balance_expr_ar() != 0)
        .subquery()
    )
    totals_row = (
        await db.execute(
            select(
                func.coalesce(func.sum(party_balances.c.balance), 0),
                func.count(),
            )
        )
    ).one()
    total_balance = Decimal(str(totals_row[0] or 0))
    party_count = int(totals_row[1] or 0)
    if include_unregistered:
        total_balance += unregistered.balance

    return SubledgerBalancesResponse(
        base_currency=base_currency,
        as_of=as_of,
        control_account_code=receivable.account_code,
        control_account_name=receivable.account_name,
        rows=rows,
        unregistered=unregistered,
        totals=SubledgerTotals(
            balance=total_balance,
            counterparty_count=party_count
            + (1 if include_unregistered and unregistered.balance != 0 else 0),
        ),
    )
