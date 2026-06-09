"""Spend analytics for the Reports page — processed invoices only."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import Invoice, InvoiceStatus
from app.schemas.reports import (
    GlAccountSpendRow,
    ReportDocumentRow,
    ReportsAnalytics,
    ReportsKpiTrends,
    VendorSpendRow,
)
from app.services.currency import BASE_CURRENCY, convert_to_base
from app.services.dashboard_service import parse_period

_REPORTABLE_STATUSES = frozenset({InvoiceStatus.PROCESSED})
_SUSPENSE_ACCOUNT = "Suspense Account"


def _effective_invoice_date():
    return func.coalesce(Invoice.invoice_date, func.date(Invoice.created_at))


def _period_key_from_date(value: date | None) -> str:
    if value is None:
        today = date.today()
        return f"{today.year:04d}-{today.month:02d}"
    return f"{value.year:04d}-{value.month:02d}"


def _period_label(month_start: date) -> str:
    return month_start.strftime("%B %Y")


def _document_ref(invoice: Invoice) -> str:
    if invoice.invoice_no and invoice.invoice_no.strip():
        return invoice.invoice_no.strip()
    return f"INV-{invoice.id:04d}"


def _account_name(invoice: Invoice) -> str:
    name = (invoice.account_name or "").strip()
    return name or _SUSPENSE_ACCOUNT


def _tax_label(currency: str) -> str:
    if currency == "INR":
        return "GST"
    if currency == "GBP":
        return "VAT"
    return "GST"


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
    org_id: int,
    month_start: date | None = None,
    month_end: date | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> list[Invoice]:
    stmt = select(Invoice).where(
        Invoice.org_id == org_id,
        Invoice.status.in_(_REPORTABLE_STATUSES),
    )
    effective = _effective_invoice_date()
    if month_start is not None and month_end is not None:
        stmt = stmt.where(effective >= month_start, effective <= month_end)
    if date_from is not None:
        stmt = stmt.where(effective >= date_from)
    if date_to is not None:
        stmt = stmt.where(effective <= date_to)
    stmt = stmt.order_by(effective.desc(), Invoice.id.desc())
    return list((await db.execute(stmt)).scalars().all())


def _aggregate_gl(invoices: list[Invoice]) -> list[GlAccountSpendRow]:
    totals: dict[str, dict[str, Decimal | int]] = {}
    for inv in invoices:
        account = _account_name(inv)
        bucket = totals.setdefault(account, {"amount": Decimal("0"), "count": 0})
        bucket["amount"] = Decimal(str(bucket["amount"])) + convert_to_base(
            inv.subtotal, inv.currency
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


def _aggregate_vendors(invoices: list[Invoice], limit: int = 8) -> list[VendorSpendRow]:
    totals: dict[str, dict[str, Decimal | int]] = {}
    for inv in invoices:
        vendor = (inv.vendor or "Unknown").strip() or "Unknown"
        bucket = totals.setdefault(vendor, {"amount": Decimal("0"), "count": 0})
        bucket["amount"] = Decimal(str(bucket["amount"])) + convert_to_base(
            inv.total, inv.currency
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


def _totals(invoices: list[Invoice]) -> tuple[Decimal, Decimal, Decimal]:
    net = Decimal("0")
    tax = Decimal("0")
    gross = Decimal("0")
    for inv in invoices:
        net += convert_to_base(inv.subtotal, inv.currency)
        tax += convert_to_base(inv.gst, inv.currency)
        gross += convert_to_base(inv.total, inv.currency)
    return net, tax, gross


def invoice_to_document_row(invoice: Invoice) -> ReportDocumentRow:
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
        subtotal=convert_to_base(invoice.subtotal, invoice.currency),
        gst=convert_to_base(invoice.gst, invoice.currency),
        total=convert_to_base(invoice.total, invoice.currency),
        currency=BASE_CURRENCY,
    )


async def build_analytics(
    db: AsyncSession,
    *,
    org_id: int,
    month: str | None = None,
) -> ReportsAnalytics:
    month_start, month_end, period_key = parse_period(month)
    invoices = await _load_invoices(
        db, org_id=org_id, month_start=month_start, month_end=month_end
    )
    net, tax, gross = _totals(invoices)

    prior_start, prior_end, _ = _prior_month(month_start)
    prior_invoices = await _load_invoices(
        db, org_id=org_id, month_start=prior_start, month_end=prior_end
    )
    prior_net, prior_tax, prior_gross = _totals(prior_invoices)

    return ReportsAnalytics(
        base_currency=BASE_CURRENCY,
        tax_label=_tax_label(BASE_CURRENCY),
        period_key=period_key,
        period_label=_period_label(month_start),
        net_spend=net,
        tax_total=tax,
        gross_spend=gross,
        document_count=len(invoices),
        by_gl_account=_aggregate_gl(invoices),
        top_vendors=_aggregate_vendors(invoices),
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
    org_id: int,
    date_from: date | None = None,
    date_to: date | None = None,
) -> list[ReportDocumentRow]:
    if date_from is not None and date_to is not None and date_from > date_to:
        raise ValueError("date_from must be on or before date_to")
    invoices = await _load_invoices(
        db, org_id=org_id, date_from=date_from, date_to=date_to
    )
    return [invoice_to_document_row(inv) for inv in invoices]
