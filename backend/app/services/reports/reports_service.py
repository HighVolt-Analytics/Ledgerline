"""Spend analytics for the Reports page — all active document statuses."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import load_only, noload

from app.models.invoice import Invoice, InvoiceStatus
from app.schemas.reports import (
    GlAccountSpendRow,
    ReportDocumentRow,
    ReportsAnalytics,
    ReportsKpiTrends,
    VendorSpendRow,
)
from app.services.shared.currency import BASE_CURRENCY, convert_to_base
from app.services.reports.dashboard_service import parse_period, _institution_today
from app.jurisdiction.packs import jurisdiction_pack_for_country
from app.models.tenant import Tenant
from app.tenant_settings import tenant_country, tenant_currency

# Match workbook export: include vaulted/exception/pipeline docs; skip terminal rejects.
_REPORTABLE_STATUSES = frozenset(
    status
    for status in InvoiceStatus
    if status not in {InvoiceStatus.REJECTED, InvoiceStatus.DUPLICATE_SKIPPED}
)
_SUSPENSE_ACCOUNT = "Suspense Account"

_ANALYTICS_INVOICE_LOAD = (
    load_only(
        Invoice.id,
        Invoice.tenant_id,
        Invoice.vendor,
        Invoice.account_name,
        Invoice.subtotal,
        Invoice.gst,
        Invoice.total,
        Invoice.currency,
        Invoice.invoice_date,
        Invoice.created_at,
        Invoice.status,
    ),
    noload(Invoice.line_items),
    noload(Invoice.journal_entries),
)


def _effective_invoice_date():
    return func.coalesce(Invoice.invoice_date, func.date(Invoice.created_at))


def _period_key_from_date(value: date | None) -> str:
    if value is None:
        today = date.today()
        return f"{today.year:04d}-{today.month:02d}"
    return f"{value.year:04d}-{value.month:02d}"


def _period_label(month_start: date) -> str:
    return month_start.strftime("%B %Y")


from app.services.dossier.document_ref_service import display_document_ref


def _document_ref(invoice: Invoice) -> str:
    return display_document_ref(invoice)


def _account_name(invoice: Invoice) -> str:
    name = (invoice.account_name or "").strip()
    return name or _SUSPENSE_ACCOUNT


def _tax_label_for_tenant(tenant: Tenant | None) -> str:
    return jurisdiction_pack_for_country(tenant_country(tenant)).tax_label


async def _tenant_reporting_currency(db: AsyncSession, tenant_id) -> tuple[str, str]:
    tenant = await db.get(Tenant, tenant_id)
    currency = tenant_currency(tenant)
    return currency, _tax_label_for_tenant(tenant)


def _delta_pct(current: Decimal, prior: Decimal) -> float | None:
    if prior <= 0:
        return None
    return float(((current - prior) / prior) * 100)


def _prior_month(month_start: date) -> tuple[date, date, str]:
    if month_start.month == 1:
        start = date(month_start.year - 1, 12, 1)
    else:
        start = date(month_start.year, month_start.month - 1, 1)
    if start.month == 12:
        end = date(start.year + 1, 1, 1) - timedelta(days=1)
    else:
        end = date(start.year, start.month + 1, 1) - timedelta(days=1)
    return start, end, f"{start.year:04d}-{start.month:02d}"


async def _load_invoices(
    db: AsyncSession,
    *,
    tenant_id: int,
    month_start: date | None = None,
    month_end: date | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    lean: bool = False,
) -> list[Invoice]:
    stmt = select(Invoice).where(
        Invoice.tenant_id == tenant_id,
        Invoice.status.in_(_REPORTABLE_STATUSES),
    )
    if lean:
        stmt = stmt.options(*_ANALYTICS_INVOICE_LOAD)
    effective = _effective_invoice_date()
    if month_start is not None and month_end is not None:
        stmt = stmt.where(effective >= month_start, effective <= month_end)
    if date_from is not None:
        stmt = stmt.where(effective >= date_from)
    if date_to is not None:
        stmt = stmt.where(effective <= date_to)
    stmt = stmt.order_by(effective.desc(), Invoice.id.desc())
    return list((await db.execute(stmt)).scalars().all())


def _aggregate_gl(
    invoices: list[Invoice],
    *,
    base: str = BASE_CURRENCY,
) -> list[GlAccountSpendRow]:
    totals: dict[str, dict[str, Decimal | int]] = {}
    for inv in invoices:
        account = _account_name(inv)
        bucket = totals.setdefault(account, {"amount": Decimal("0"), "count": 0})
        bucket["amount"] = Decimal(str(bucket["amount"])) + convert_to_base(
            inv.subtotal, inv.currency, base=base
        )
        bucket["count"] = int(bucket["count"]) + 1
    rows = [
        GlAccountSpendRow(
            account=account,
            amount=Decimal(str(data["amount"])),
            count=int(data["count"]),
        )
        for account, data in totals.items()
    ]
    return sorted(rows, key=lambda row: row.amount, reverse=True)


def _aggregate_vendors(
    invoices: list[Invoice],
    limit: int = 8,
    *,
    base: str = BASE_CURRENCY,
) -> list[VendorSpendRow]:
    totals: dict[str, dict[str, Decimal | int]] = {}
    for inv in invoices:
        vendor = (inv.vendor or "Unknown").strip() or "Unknown"
        bucket = totals.setdefault(vendor, {"amount": Decimal("0"), "count": 0})
        bucket["amount"] = Decimal(str(bucket["amount"])) + convert_to_base(
            inv.total, inv.currency, base=base
        )
        bucket["count"] = int(bucket["count"]) + 1
    rows = [
        VendorSpendRow(
            vendor=vendor,
            amount=Decimal(str(data["amount"])),
            count=int(data["count"]),
        )
        for vendor, data in totals.items()
    ]
    return sorted(rows, key=lambda row: row.amount, reverse=True)[:limit]


def _totals(
    invoices: list[Invoice],
    *,
    base: str = BASE_CURRENCY,
) -> tuple[Decimal, Decimal, Decimal]:
    net = Decimal("0")
    tax = Decimal("0")
    gross = Decimal("0")
    for inv in invoices:
        net += convert_to_base(inv.subtotal, inv.currency, base=base)
        tax += convert_to_base(inv.gst, inv.currency, base=base)
        gross += convert_to_base(inv.total, inv.currency, base=base)
    return net, tax, gross


def invoice_to_document_row(
    invoice: Invoice,
    *,
    base: str = BASE_CURRENCY,
) -> ReportDocumentRow:
    effective = invoice.invoice_date
    if effective is None and invoice.created_at is not None:
        effective = invoice.created_at.date()
    return ReportDocumentRow(
        id=invoice.id,
        document_ref=_document_ref(invoice),
        vendor=(invoice.vendor or "Unknown").strip() or "Unknown",
        account=_account_name(invoice),
        invoice_date=invoice.invoice_date,
        period_key=_period_key_from_date(effective),
        subtotal=convert_to_base(invoice.subtotal, invoice.currency, base=base),
        gst=convert_to_base(invoice.gst, invoice.currency, base=base),
        total=convert_to_base(invoice.total, invoice.currency, base=base),
        currency=base,
    )


async def build_analytics(
    db: AsyncSession,
    *,
    tenant_id: int,
    month: str | None = None,
) -> ReportsAnalytics:
    today = await _institution_today(db, tenant_id)
    month_start, month_end, period_key = parse_period(month, today=today)
    base, tax_label = await _tenant_reporting_currency(db, tenant_id)
    invoices = await _load_invoices(
        db,
        tenant_id=tenant_id,
        month_start=month_start,
        month_end=month_end,
        lean=True,
    )
    net, tax, gross = _totals(invoices, base=base)

    prior_start, prior_end, _ = _prior_month(month_start)
    prior_invoices = await _load_invoices(
        db,
        tenant_id=tenant_id,
        month_start=prior_start,
        month_end=prior_end,
        lean=True,
    )
    prior_net, prior_tax, prior_gross = _totals(prior_invoices, base=base)

    return ReportsAnalytics(
        base_currency=base,
        tax_label=tax_label,
        period_key=period_key,
        period_label=_period_label(month_start),
        net_spend=net,
        tax_total=tax,
        gross_spend=gross,
        document_count=len(invoices),
        by_gl_account=_aggregate_gl(invoices, base=base),
        top_vendors=_aggregate_vendors(invoices, base=base),
        kpi_trends=ReportsKpiTrends(
            net_spend_delta_pct=_delta_pct(net, prior_net),
            tax_delta_pct=_delta_pct(tax, prior_tax),
            gross_spend_delta_pct=_delta_pct(gross, prior_gross),
            documents_delta=len(invoices) - len(prior_invoices),
        ),
        period_has_data=len(invoices) > 0,
    )


async def list_documents(
    db: AsyncSession,
    *,
    tenant_id: int,
    date_from: date | None = None,
    date_to: date | None = None,
) -> list[ReportDocumentRow]:
    if date_from is not None and date_to is not None and date_from > date_to:
        raise ValueError("date_from must be on or before date_to")
    invoices = await _load_invoices(
        db, tenant_id=tenant_id, date_from=date_from, date_to=date_to
    )
    return [invoice_to_document_row(inv) for inv in invoices]
