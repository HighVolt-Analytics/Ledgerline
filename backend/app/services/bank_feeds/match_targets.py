"""User-facing payment/collection targets for bank manual match picker."""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.bank_feed import BankMatchEntityType, BankTransactionMatch
from app.models.collection import Collection, CollectionStatus
from app.models.invoice import Invoice
from app.models.payment import Payment, PaymentStatus
from app.schemas.bank_feed import BankMatchTargetResponse, BankTransactionMatchResponse
from app.services.bank_feeds.match_service import (
    _allocated_sum,
    _collection_gross_compare,
    _payment_gross_compare,
)

_PAYMENT_STATUSES = (PaymentStatus.PAID, PaymentStatus.SCHEDULED)
_COLLECTION_STATUSES = (CollectionStatus.RECEIVED, CollectionStatus.AWAITING)
_ZERO = Decimal("0")


def format_match_target_label(
    *,
    party_name: str | None,
    invoice_no: str | None,
    amount: Decimal | float | int | str,
    currency: str | None,
) -> str:
    party = (party_name or "").strip() or "Unknown party"
    inv = (invoice_no or "").strip()
    ccy = (currency or "").strip().upper()
    amt = f"{Decimal(str(amount)).quantize(Decimal('0.01')):.2f}"
    money = f"{amt} {ccy}".strip() if ccy else amt
    if inv:
        return f"{party} · {inv} · {money}"
    return f"{party} · {money}"


async def search_match_targets(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    matched_type: str,
    q: str | None = None,
    limit: int = 50,
    bank_currency: str | None = None,
) -> list[BankMatchTargetResponse]:
    needle = (q or "").strip()
    limit = max(1, min(limit, 100))

    if matched_type == BankMatchEntityType.PAYMENT.value:
        stmt = (
            select(Payment, Invoice)
            .outerjoin(Invoice, Invoice.id == Payment.invoice_id)
            .where(
                Payment.tenant_id == tenant_id,
                Payment.status.in_(_PAYMENT_STATUSES),
            )
            .order_by(Payment.paid_date.desc().nullslast(), Payment.id.desc())
            .limit(limit * 3 if needle else limit)
        )
        rows = list((await session.execute(stmt)).all())
        out: list[BankMatchTargetResponse] = []
        for payment, invoice in rows:
            party = payment.vendor or (invoice.vendor if invoice else None)
            invoice_no = invoice.invoice_no if invoice else None
            if needle:
                blob = " ".join(
                    x
                    for x in (
                        party,
                        invoice_no,
                        payment.payment_intent,
                        f"{payment.amount}",
                    )
                    if x
                ).lower()
                if needle.lower() not in blob:
                    continue
            if bank_currency:
                gross = await _payment_gross_compare(
                    payment, bank_currency=bank_currency
                )
                if gross is None:
                    continue
                allocated = await _allocated_sum(
                    session,
                    tenant_id=tenant_id,
                    matched_type=BankMatchEntityType.PAYMENT.value,
                    matched_id=payment.id,
                )
                if gross[0] - allocated <= _ZERO:
                    continue
            out.append(
                BankMatchTargetResponse(
                    id=payment.id,
                    matched_type="payment",
                    party_name=party,
                    invoice_no=invoice_no,
                    amount=float(payment.amount),
                    currency=payment.currency or "",
                    status=payment.status.value
                    if hasattr(payment.status, "value")
                    else str(payment.status),
                    display_label=format_match_target_label(
                        party_name=party,
                        invoice_no=invoice_no,
                        amount=payment.amount,
                        currency=payment.currency,
                    ),
                )
            )
            if len(out) >= limit:
                break
        return out

    if matched_type == BankMatchEntityType.COLLECTION.value:
        stmt = (
            select(Collection, Invoice)
            .outerjoin(Invoice, Invoice.id == Collection.invoice_id)
            .where(
                Collection.tenant_id == tenant_id,
                Collection.status.in_(_COLLECTION_STATUSES),
            )
            .order_by(Collection.received_date.desc().nullslast(), Collection.id.desc())
            .limit(limit * 3 if needle else limit)
        )
        rows = list((await session.execute(stmt)).all())
        out = []
        for collection, invoice in rows:
            party = collection.customer or (invoice.vendor if invoice else None)
            invoice_no = invoice.invoice_no if invoice else None
            if needle:
                blob = " ".join(
                    x
                    for x in (party, invoice_no, f"{collection.amount}")
                    if x
                ).lower()
                if needle.lower() not in blob:
                    continue
            if bank_currency:
                gross = await _collection_gross_compare(
                    collection, bank_currency=bank_currency
                )
                if gross is None:
                    continue
                allocated = await _allocated_sum(
                    session,
                    tenant_id=tenant_id,
                    matched_type=BankMatchEntityType.COLLECTION.value,
                    matched_id=collection.id,
                )
                if gross[0] - allocated <= _ZERO:
                    continue
            out.append(
                BankMatchTargetResponse(
                    id=collection.id,
                    matched_type="collection",
                    party_name=party,
                    invoice_no=invoice_no,
                    amount=float(collection.amount),
                    currency=collection.currency or "",
                    status=collection.status.value
                    if hasattr(collection.status, "value")
                    else str(collection.status),
                    display_label=format_match_target_label(
                        party_name=party,
                        invoice_no=invoice_no,
                        amount=collection.amount,
                        currency=collection.currency,
                    ),
                )
            )
            if len(out) >= limit:
                break
        return out

    raise ValueError("matched_type must be payment or collection")


async def _party_invoice_for_match(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    matched_type: str,
    matched_id: int,
) -> tuple[str | None, str | None, Decimal | None, str | None]:
    if matched_type == BankMatchEntityType.PAYMENT.value:
        row = (
            await session.execute(
                select(Payment, Invoice)
                .outerjoin(Invoice, Invoice.id == Payment.invoice_id)
                .where(Payment.tenant_id == tenant_id, Payment.id == matched_id)
            )
        ).first()
        if not row:
            return None, None, None, None
        payment, invoice = row
        party = payment.vendor or (invoice.vendor if invoice else None)
        invoice_no = invoice.invoice_no if invoice else None
        return party, invoice_no, payment.amount, payment.currency

    if matched_type == BankMatchEntityType.COLLECTION.value:
        row = (
            await session.execute(
                select(Collection, Invoice)
                .outerjoin(Invoice, Invoice.id == Collection.invoice_id)
                .where(Collection.tenant_id == tenant_id, Collection.id == matched_id)
            )
        ).first()
        if not row:
            return None, None, None, None
        collection, invoice = row
        party = collection.customer or (invoice.vendor if invoice else None)
        invoice_no = invoice.invoice_no if invoice else None
        return party, invoice_no, collection.amount, collection.currency

    return None, None, None, None


async def match_to_response(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    match: BankTransactionMatch,
) -> BankTransactionMatchResponse:
    party, invoice_no, amount, currency = await _party_invoice_for_match(
        session,
        tenant_id=tenant_id,
        matched_type=match.matched_type,
        matched_id=match.matched_id,
    )
    label = None
    if party or invoice_no or amount is not None:
        label = format_match_target_label(
            party_name=party,
            invoice_no=invoice_no,
            amount=amount if amount is not None else match.allocated_amount,
            currency=currency,
        )
    base = BankTransactionMatchResponse.model_validate(match)
    return base.model_copy(
        update={
            "party_name": party,
            "invoice_no": invoice_no,
            "display_label": label,
        }
    )


async def matches_to_responses(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    matches: list[BankTransactionMatch],
) -> list[BankTransactionMatchResponse]:
    return [
        await match_to_response(session, tenant_id=tenant_id, match=m) for m in matches
    ]
