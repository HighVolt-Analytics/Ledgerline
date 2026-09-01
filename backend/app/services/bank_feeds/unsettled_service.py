"""Unsettled cash settlements — paid payments / received collections without verified bank linkage."""

from __future__ import annotations

import calendar
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Literal
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.bank_feed import (
    BankMatchEntityType,
    BankMatchMethod,
    BankTransaction,
    BankTransactionMatch,
    BankTxnMatchStatus,
)
from app.models.collection import Collection, CollectionStatus
from app.models.invoice import Invoice
from app.models.payment import Payment, PaymentStatus
from app.models.tenant import Tenant
from app.services.reports.dashboard_service import _institution_today
from app.tenant_settings import tenant_currency, tenant_timezone

DEFAULT_GRACE_DAYS = 7
MIN_GRACE_DAYS = 1
MAX_GRACE_DAYS = 90
LOOKBACK_MONTHS = 12
SETTINGS_KEY = "bank_cash_verification_grace_days"

_ZERO = Decimal("0")


def _quantize(value: Decimal | float | int) -> Decimal:
    return Decimal(value).quantize(Decimal("0.01"))


def bank_cash_verification_grace_days(tenant: Tenant | None) -> int:
    """Tenant-configurable grace window (days) before flagging unsettled cash."""
    if tenant is None or not isinstance(tenant.settings_json, dict):
        return DEFAULT_GRACE_DAYS
    raw = tenant.settings_json.get(SETTINGS_KEY)
    try:
        days = int(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return DEFAULT_GRACE_DAYS
    return max(MIN_GRACE_DAYS, min(MAX_GRACE_DAYS, days))


def _months_before(anchor: date, months: int) -> date:
    y, m = anchor.year, anchor.month - months
    while m <= 0:
        m += 12
        y -= 1
    d = min(anchor.day, calendar.monthrange(y, m)[1])
    return date(y, m, d)


def _anchor_local_date(dt: datetime | None, tz_name: str) -> date | None:
    if dt is None:
        return None
    aware = dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)
    try:
        return aware.astimezone(ZoneInfo(tz_name)).date()
    except Exception:
        return aware.date()


def payment_gross_for_cash_verification(
    payment: Payment, *, books_currency: str
) -> Decimal | None:
    """Gross compare amount for cash verification (mirrors match_service payment path)."""
    pay_ccy = (payment.currency or "").strip().upper()
    books = (books_currency or "").strip().upper()
    if pay_ccy and books and pay_ccy == books:
        return _quantize(payment.amount)
    if payment.bank_payment_amount is not None:
        return _quantize(payment.bank_payment_amount)
    return None


def collection_gross_for_cash_verification(
    collection: Collection, *, books_currency: str
) -> Decimal | None:
    """Gross compare amount for cash verification (same-currency collections only)."""
    col_ccy = (collection.currency or "").strip().upper()
    books = (books_currency or "").strip().upper()
    if col_ccy and books and col_ccy == books:
        return _quantize(collection.amount)
    return None


def _is_verified_match(match: BankTransactionMatch, txn_match_status: str) -> bool:
    if match.unmatched_at is not None:
        return False
    if match.match_method in (
        BankMatchMethod.AUTO.value,
        BankMatchMethod.MANUAL.value,
    ):
        return True
    if (
        match.match_method == BankMatchMethod.SUGGESTED.value
        and txn_match_status == BankTxnMatchStatus.MATCHED.value
    ):
        return True
    return False


@dataclass(frozen=True)
class _MatchAgg:
    verified_allocated: Decimal
    has_suggested: bool


async def _load_match_aggs(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
) -> dict[tuple[str, int], _MatchAgg]:
    rows = (
        await session.execute(
            select(BankTransactionMatch, BankTransaction.match_status)
            .join(
                BankTransaction,
                BankTransaction.id == BankTransactionMatch.bank_transaction_id,
            )
            .where(
                BankTransactionMatch.tenant_id == tenant_id,
                BankTransactionMatch.unmatched_at.is_(None),
                BankTransactionMatch.matched_type.in_(
                    (
                        BankMatchEntityType.PAYMENT.value,
                        BankMatchEntityType.COLLECTION.value,
                    )
                ),
            )
        )
    ).all()

    out: dict[tuple[str, int], _MatchAgg] = {}
    for match, txn_status in rows:
        key = (match.matched_type, match.matched_id)
        agg = out.get(key, _MatchAgg(verified_allocated=_ZERO, has_suggested=False))
        verified_allocated = agg.verified_allocated
        has_suggested = agg.has_suggested
        if match.match_method == BankMatchMethod.SUGGESTED.value:
            has_suggested = True
        if _is_verified_match(match, txn_status):
            verified_allocated = _quantize(verified_allocated + match.allocated_amount)
        out[key] = _MatchAgg(
            verified_allocated=verified_allocated,
            has_suggested=has_suggested,
        )
    return out


@dataclass(frozen=True)
class UnsettledSettlementRow:
    entity_type: Literal["payment", "collection"]
    entity_id: int
    invoice_id: int
    invoice_no: str | None
    party_name: str | None
    amount: Decimal
    currency: str
    settled_date: date
    days_since_settled: int
    has_suggested_bank_match: bool
    allocated_bank_amount: Decimal
    gross_amount: Decimal | None
    grace_days: int


def _is_fully_verified(*, gross: Decimal | None, agg: _MatchAgg | None) -> bool:
    if gross is None:
        return False
    verified = agg.verified_allocated if agg else _ZERO
    return verified >= gross


def _is_unsettled(
    *,
    anchor_date: date,
    today: date,
    grace_days: int,
    lookback_start: date,
    gross: Decimal | None,
    agg: _MatchAgg | None,
    missing_anchor: bool = False,
) -> bool:
    if _is_fully_verified(gross=gross, agg=agg):
        return False
    if missing_anchor:
        return True
    if anchor_date < lookback_start:
        return False
    days_since = (today - anchor_date).days
    if days_since <= grace_days:
        return False
    if gross is None:
        return True
    return True


async def _collect_unsettled_rows(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    today: date | None = None,
) -> list[UnsettledSettlementRow]:
    tenant = await session.get(Tenant, tenant_id)
    anchor = today or await _institution_today(session, tenant_id)
    tz_name = tenant_timezone(tenant)
    grace_days = bank_cash_verification_grace_days(tenant)
    lookback_start = _months_before(anchor, LOOKBACK_MONTHS)
    books_currency = tenant_currency(tenant)
    match_aggs = await _load_match_aggs(session, tenant_id=tenant_id)

    payments = (
        await session.execute(
            select(Payment, Invoice.invoice_no)
            .join(Invoice, Invoice.id == Payment.invoice_id, isouter=True)
            .where(
                Payment.tenant_id == tenant_id,
                Payment.status == PaymentStatus.PAID,
            )
        )
    ).all()

    collections = (
        await session.execute(
            select(Collection, Invoice.invoice_no)
            .join(Invoice, Invoice.id == Collection.invoice_id, isouter=True)
            .where(
                Collection.tenant_id == tenant_id,
                Collection.status == CollectionStatus.RECEIVED,
            )
        )
    ).all()

    rows: list[UnsettledSettlementRow] = []

    for payment, invoice_no in payments:
        missing_anchor = payment.paid_date is None
        settled = _anchor_local_date(payment.paid_date, tz_name) or anchor
        gross = payment_gross_for_cash_verification(
            payment, books_currency=books_currency
        )
        agg = match_aggs.get((BankMatchEntityType.PAYMENT.value, payment.id))
        if not _is_unsettled(
            anchor_date=settled,
            today=anchor,
            grace_days=grace_days,
            lookback_start=lookback_start,
            gross=gross,
            agg=agg,
            missing_anchor=missing_anchor,
        ):
            continue
        rows.append(
            UnsettledSettlementRow(
                entity_type="payment",
                entity_id=payment.id,
                invoice_id=payment.invoice_id,
                invoice_no=invoice_no,
                party_name=payment.vendor,
                amount=payment.amount,
                currency=payment.currency,
                settled_date=settled,
                days_since_settled=0 if missing_anchor else (anchor - settled).days,
                has_suggested_bank_match=bool(agg and agg.has_suggested),
                allocated_bank_amount=agg.verified_allocated if agg else _ZERO,
                gross_amount=gross,
                grace_days=grace_days,
            )
        )

    for collection, invoice_no in collections:
        missing_anchor = collection.received_date is None
        settled = _anchor_local_date(collection.received_date, tz_name) or anchor
        gross = collection_gross_for_cash_verification(
            collection, books_currency=books_currency
        )
        agg = match_aggs.get((BankMatchEntityType.COLLECTION.value, collection.id))
        if not _is_unsettled(
            anchor_date=settled,
            today=anchor,
            grace_days=grace_days,
            lookback_start=lookback_start,
            gross=gross,
            agg=agg,
            missing_anchor=missing_anchor,
        ):
            continue
        rows.append(
            UnsettledSettlementRow(
                entity_type="collection",
                entity_id=collection.id,
                invoice_id=collection.invoice_id,
                invoice_no=invoice_no,
                party_name=collection.customer,
                amount=collection.amount,
                currency=collection.currency,
                settled_date=settled,
                days_since_settled=0 if missing_anchor else (anchor - settled).days,
                has_suggested_bank_match=bool(agg and agg.has_suggested),
                allocated_bank_amount=agg.verified_allocated if agg else _ZERO,
                gross_amount=gross,
                grace_days=grace_days,
            )
        )

    rows.sort(
        key=lambda r: (-r.days_since_settled, r.entity_type, r.entity_id),
    )
    return rows


async def count_unsettled_settlements(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    today: date | None = None,
) -> int:
    rows = await _collect_unsettled_rows(session, tenant_id=tenant_id, today=today)
    return len(rows)


async def list_unsettled_settlements(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    page: int = 1,
    page_size: int = 50,
    today: date | None = None,
) -> tuple[list[UnsettledSettlementRow], int]:
    all_rows = await _collect_unsettled_rows(session, tenant_id=tenant_id, today=today)
    total = len(all_rows)
    start = max(0, (page - 1) * page_size)
    end = start + page_size
    return all_rows[start:end], total
