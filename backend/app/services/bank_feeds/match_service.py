"""Bank transaction ↔ payment/collection match engine (Phase 3).

No GL / settlement journal posting from matches — link only.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Literal

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.bank_feed import (
    BankAccount,
    BankMatchEntityType,
    BankMatchMethod,
    BankTransaction,
    BankTransactionMatch,
    BankTxnDirection,
    BankTxnMatchStatus,
)
from app.models.collection import Collection, CollectionStatus
from app.models.invoice import Invoice
from app.models.payment import Payment, PaymentStatus
from app.services.audit.audit_service import log_event
from app.services.bank_feeds.fingerprint import normalize_description, normalize_party_name
from app.services.bank_feeds.categorize_service import clear_category_on_match
from app.services.bank_feeds.match_constants import (
    AUTO_MATCH_CONFIDENCE_THRESHOLD,
    MATCH_DATE_WINDOW_DAYS,
    SUGGESTED_MATCH_CONFIDENCE_THRESHOLD,
)
from app.services.bank_feeds.reference import resolve_txn_reference

_ZERO = Decimal("0.00")
_CENT = Decimal("0.01")


def _q(value: Decimal | float | int | str) -> Decimal:
    return Decimal(str(value)).quantize(_CENT)


def _clip(value: float) -> float:
    return max(0.0, min(1.0, value))


def score_amount(bank_amount: Decimal, compare_amount: Decimal) -> float:
    delta = abs(_q(bank_amount) - _q(compare_amount))
    if delta == _ZERO:
        return 1.0
    if delta <= _CENT:
        return 0.95
    return 0.0


def score_date(days: int) -> float:
    if days == 0:
        return 1.0
    if days == 1:
        return 0.85
    if days == 2:
        return 0.70
    if days in {3, 4, 5}:
        return 0.55
    if days in {6, 7}:
        return 0.40
    return 0.0


def score_reference(
    *,
    haystack_raw: str,
    invoice_no: str | None,
    payment_intent: str | None,
    entity_token: str,
    party_name: str | None,
) -> tuple[float, str | None]:
    """Return (S_ref, hit label). Party names <3 chars after normalize → no party hit."""
    haystack = normalize_description(haystack_raw)
    if not haystack:
        return 0.0, None

    inv_norm = normalize_description(invoice_no or "")
    if inv_norm and inv_norm in haystack:
        return 1.0, invoice_no

    intent_norm = normalize_description(payment_intent or "")
    if intent_norm and intent_norm in haystack:
        return 1.0, payment_intent

    token_norm = normalize_description(entity_token)
    if token_norm and token_norm in haystack:
        return 0.9, entity_token

    party = normalize_party_name(party_name or "")
    if len(party) >= 3 and party in haystack:
        return 0.6, party_name
    # Party names under 3 chars after normalize: S_ref stays 0 for this tier
    # (amount + date only); not special-cased further.
    return 0.0, None


def combine_confidence(s_amount: float, s_date: float, s_ref: float) -> Decimal:
    raw = 0.50 * s_amount + 0.30 * s_date + 0.20 * s_ref
    return Decimal(str(round(_clip(raw), 4)))


@dataclass(frozen=True)
class ScoredCandidate:
    matched_type: str
    matched_id: int
    invoice_id: int | None
    remaining: Decimal
    confidence: Decimal
    s_amount: float
    s_date: float
    s_ref: float
    date_days: int
    reference_hit: str | None
    amount_path: str
    compare_amount: Decimal
    auto_eligible: bool


def _anchor_date_payment(payment: Payment) -> date | None:
    if payment.paid_date is not None:
        return payment.paid_date.date() if hasattr(payment.paid_date, "date") else payment.paid_date
    if payment.scheduled_date is not None:
        return payment.scheduled_date
    return payment.due_date


def _anchor_date_collection(collection: Collection) -> date | None:
    if collection.received_date is not None:
        return (
            collection.received_date.date()
            if hasattr(collection.received_date, "date")
            else collection.received_date
        )
    return collection.due_date


async def _allocated_sum(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    matched_type: str,
    matched_id: int,
    exclude_match_id: int | None = None,
) -> Decimal:
    stmt = select(func.coalesce(func.sum(BankTransactionMatch.allocated_amount), 0)).where(
        BankTransactionMatch.tenant_id == tenant_id,
        BankTransactionMatch.matched_type == matched_type,
        BankTransactionMatch.matched_id == matched_id,
        BankTransactionMatch.unmatched_at.is_(None),
    )
    if exclude_match_id is not None:
        stmt = stmt.where(BankTransactionMatch.id != exclude_match_id)
    value = (await session.execute(stmt)).scalar()
    return _q(value or 0)


async def _payment_gross_compare(
    payment: Payment,
    *,
    bank_currency: str,
) -> tuple[Decimal, str] | None:
    """Return (gross_compare_amount, amount_path) or None if FX path unavailable."""
    pay_ccy = (payment.currency or "").strip().upper()
    bank_ccy = (bank_currency or "").strip().upper()
    if pay_ccy and bank_ccy and pay_ccy == bank_ccy:
        return _q(payment.amount), "payment.amount"
    if payment.bank_payment_amount is not None and bank_ccy:
        return _q(payment.bank_payment_amount), "payment.bank_payment_amount"
    return None


async def _collection_gross_compare(
    collection: Collection,
    *,
    bank_currency: str,
) -> tuple[Decimal, str] | None:
    """Collections: same-currency only — hard-exclude FX mismatches."""
    col_ccy = (collection.currency or "").strip().upper()
    bank_ccy = (bank_currency or "").strip().upper()
    if not col_ccy or not bank_ccy or col_ccy != bank_ccy:
        return None
    return _q(collection.amount), "collection.amount"


async def _score_payment(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    txn: BankTransaction,
    bank_currency: str,
    payment: Payment,
    invoice_no: str | None,
) -> ScoredCandidate | None:
    anchor = _anchor_date_payment(payment)
    if anchor is None:
        return None
    days = abs((txn.txn_date - anchor).days)
    if days > MATCH_DATE_WINDOW_DAYS:
        return None

    gross = await _payment_gross_compare(payment, bank_currency=bank_currency)
    if gross is None:
        return None
    gross_amount, amount_path = gross
    allocated = await _allocated_sum(
        session,
        tenant_id=tenant_id,
        matched_type=BankMatchEntityType.PAYMENT.value,
        matched_id=payment.id,
    )
    remaining = _q(gross_amount - allocated)
    if remaining <= _ZERO:
        return None

    s_amount = score_amount(txn.amount, remaining)
    s_date = score_date(days)
    s_ref, hit = score_reference(
        haystack_raw=f"{txn.description} {resolve_txn_reference(txn) or ''}",
        invoice_no=invoice_no,
        payment_intent=payment.payment_intent,
        entity_token=f"payment-{payment.id}",
        party_name=payment.vendor,
    )
    confidence = combine_confidence(s_amount, s_date, s_ref)
    auto_eligible = (
        confidence >= Decimal(str(AUTO_MATCH_CONFIDENCE_THRESHOLD)) and s_amount == 1.0
    )
    return ScoredCandidate(
        matched_type=BankMatchEntityType.PAYMENT.value,
        matched_id=payment.id,
        invoice_id=payment.invoice_id,
        remaining=remaining,
        confidence=confidence,
        s_amount=s_amount,
        s_date=s_date,
        s_ref=s_ref,
        date_days=days,
        reference_hit=hit,
        amount_path=amount_path,
        compare_amount=remaining,
        auto_eligible=auto_eligible,
    )


async def _score_collection(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    txn: BankTransaction,
    bank_currency: str,
    collection: Collection,
    invoice_no: str | None,
) -> ScoredCandidate | None:
    # Hard gate: collection currency must equal bank account currency.
    if await _collection_gross_compare(collection, bank_currency=bank_currency) is None:
        return None

    anchor = _anchor_date_collection(collection)
    if anchor is None:
        return None
    days = abs((txn.txn_date - anchor).days)
    if days > MATCH_DATE_WINDOW_DAYS:
        return None

    gross = await _collection_gross_compare(collection, bank_currency=bank_currency)
    assert gross is not None
    gross_amount, amount_path = gross
    allocated = await _allocated_sum(
        session,
        tenant_id=tenant_id,
        matched_type=BankMatchEntityType.COLLECTION.value,
        matched_id=collection.id,
    )
    remaining = _q(gross_amount - allocated)
    if remaining <= _ZERO:
        return None

    s_amount = score_amount(txn.amount, remaining)
    s_date = score_date(days)
    s_ref, hit = score_reference(
        haystack_raw=f"{txn.description} {resolve_txn_reference(txn) or ''}",
        invoice_no=invoice_no,
        payment_intent=None,
        entity_token=f"collection-{collection.id}",
        party_name=collection.customer,
    )
    confidence = combine_confidence(s_amount, s_date, s_ref)
    auto_eligible = (
        confidence >= Decimal(str(AUTO_MATCH_CONFIDENCE_THRESHOLD)) and s_amount == 1.0
    )
    return ScoredCandidate(
        matched_type=BankMatchEntityType.COLLECTION.value,
        matched_id=collection.id,
        invoice_id=collection.invoice_id,
        remaining=remaining,
        confidence=confidence,
        s_amount=s_amount,
        s_date=s_date,
        s_ref=s_ref,
        date_days=days,
        reference_hit=hit,
        amount_path=amount_path,
        compare_amount=remaining,
        auto_eligible=auto_eligible,
    )


def _reasons(c: ScoredCandidate) -> dict[str, Any]:
    return {
        "amount_score": c.s_amount,
        "date_score": c.s_date,
        "reference_score": c.s_ref,
        "date_days": c.date_days,
        "reference_hit": c.reference_hit,
        "compare_amount": f"{c.compare_amount:.2f}",
        "amount_path": c.amount_path,
        "remaining": f"{c.remaining:.2f}",
    }


async def _refresh_txn_match_status(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    txn: BankTransaction,
) -> None:
    if txn.match_status in (
        BankTxnMatchStatus.EXCLUDED.value,
        BankTxnMatchStatus.POSTED.value,
    ):
        return
    active = await session.execute(
        select(BankTransactionMatch).where(
            BankTransactionMatch.tenant_id == tenant_id,
            BankTransactionMatch.bank_transaction_id == txn.id,
            BankTransactionMatch.unmatched_at.is_(None),
        )
    )
    rows = list(active.scalars().all())
    if not rows:
        txn.match_status = BankTxnMatchStatus.UNMATCHED.value
        return
    if any(r.match_method == BankMatchMethod.AUTO.value for r in rows) or any(
        r.match_method == BankMatchMethod.MANUAL.value for r in rows
    ):
        # Confirmed suggested counts as matched when txn was set matched on confirm
        pass
    if txn.match_status == BankTxnMatchStatus.MATCHED.value:
        return
    if any(r.match_method == BankMatchMethod.SUGGESTED.value for r in rows) and all(
        r.match_method == BankMatchMethod.SUGGESTED.value for r in rows
    ):
        txn.match_status = BankTxnMatchStatus.SUGGESTED.value
    else:
        txn.match_status = BankTxnMatchStatus.MATCHED.value


async def _void_open_suggestions(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    txn: BankTransaction,
    actor_name: str | None,
    actor_email: str | None,
    client_ip: str | None,
) -> None:
    """Expire prior suggested rows before a new match-run on this txn."""
    stmt = select(BankTransactionMatch).where(
        BankTransactionMatch.tenant_id == tenant_id,
        BankTransactionMatch.bank_transaction_id == txn.id,
        BankTransactionMatch.unmatched_at.is_(None),
        BankTransactionMatch.match_method == BankMatchMethod.SUGGESTED.value,
    )
    rows = list((await session.execute(stmt)).scalars().all())
    now = datetime.now(timezone.utc)
    for row in rows:
        before = {
            "match_id": row.id,
            "matched_type": row.matched_type,
            "matched_id": row.matched_id,
            "match_status": txn.match_status,
        }
        row.unmatched_at = now
        row.unmatch_reason = "superseded_by_match_run"
        await log_event(
            session,
            "bank_txn_unmatched",
            tenant_id=tenant_id,
            invoice_id=None,
            detail={
                "bank_transaction_id": txn.id,
                "match_id": row.id,
                "reason": "superseded_by_match_run",
                "before": before,
                "after": {"unmatched_at": now.isoformat()},
            },
            actor_name=actor_name,
            actor_email=actor_email,
            client_ip=client_ip,
        )


async def score_candidates_for_txn(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    account: BankAccount,
    txn: BankTransaction,
) -> list[ScoredCandidate]:
    scored: list[ScoredCandidate] = []
    bank_ccy = account.currency

    if txn.direction == BankTxnDirection.DEBIT.value:
        pay_stmt: Select[tuple[Payment]] = select(Payment).where(
            Payment.tenant_id == tenant_id,
            Payment.status.in_([PaymentStatus.PAID, PaymentStatus.SCHEDULED]),
        )
        payments = list((await session.execute(pay_stmt)).scalars().all())
        inv_ids = {p.invoice_id for p in payments}
        invoices = {}
        if inv_ids:
            inv_rows = (
                await session.execute(select(Invoice).where(Invoice.id.in_(inv_ids)))
            ).scalars().all()
            invoices = {i.id: i for i in inv_rows}
        for payment in payments:
            inv = invoices.get(payment.invoice_id)
            candidate = await _score_payment(
                session,
                tenant_id=tenant_id,
                txn=txn,
                bank_currency=bank_ccy,
                payment=payment,
                invoice_no=inv.invoice_no if inv else None,
            )
            if candidate is not None and candidate.confidence >= Decimal(
                str(SUGGESTED_MATCH_CONFIDENCE_THRESHOLD)
            ):
                scored.append(candidate)

    elif txn.direction == BankTxnDirection.CREDIT.value:
        col_stmt = select(Collection).where(
            Collection.tenant_id == tenant_id,
            Collection.status.in_(
                [CollectionStatus.RECEIVED, CollectionStatus.AWAITING]
            ),
        )
        collections = list((await session.execute(col_stmt)).scalars().all())
        inv_ids = {c.invoice_id for c in collections}
        invoices = {}
        if inv_ids:
            inv_rows = (
                await session.execute(select(Invoice).where(Invoice.id.in_(inv_ids)))
            ).scalars().all()
            invoices = {i.id: i for i in inv_rows}
        for collection in collections:
            inv = invoices.get(collection.invoice_id)
            candidate = await _score_collection(
                session,
                tenant_id=tenant_id,
                txn=txn,
                bank_currency=bank_ccy,
                collection=collection,
                invoice_no=inv.invoice_no if inv else None,
            )
            if candidate is not None and candidate.confidence >= Decimal(
                str(SUGGESTED_MATCH_CONFIDENCE_THRESHOLD)
            ):
                scored.append(candidate)

    scored.sort(key=lambda c: (-float(c.confidence), c.matched_type, c.matched_id))
    return scored


@dataclass
class MatchRunResult:
    transaction_id: int
    status: str
    matches_written: int
    auto_matched: bool
    tie_demoted: bool


async def run_match_for_transaction(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    account: BankAccount,
    txn: BankTransaction,
    actor_name: str | None,
    actor_email: str | None,
    client_ip: str | None = None,
) -> MatchRunResult:
    if txn.match_status in (
        BankTxnMatchStatus.EXCLUDED.value,
        BankTxnMatchStatus.POSTED.value,
        BankTxnMatchStatus.MATCHED.value,
    ):
        return MatchRunResult(txn.id, txn.match_status, 0, False, False)

    await _void_open_suggestions(
        session,
        tenant_id=tenant_id,
        txn=txn,
        actor_name=actor_name,
        actor_email=actor_email,
        client_ip=client_ip,
    )

    candidates = await score_candidates_for_txn(
        session, tenant_id=tenant_id, account=account, txn=txn
    )
    if not candidates:
        txn.match_status = BankTxnMatchStatus.UNMATCHED.value
        await session.flush()
        return MatchRunResult(txn.id, txn.match_status, 0, False, False)

    auto_pool = [c for c in candidates if c.auto_eligible]
    tie_demoted = len(auto_pool) >= 2
    use_auto = len(auto_pool) == 1

    written = 0
    if use_auto:
        c = auto_pool[0]
        allocated = min(_q(txn.amount), c.remaining)
        row = BankTransactionMatch(
            tenant_id=tenant_id,
            bank_transaction_id=txn.id,
            matched_type=c.matched_type,
            matched_id=c.matched_id,
            allocated_amount=allocated,
            match_confidence=c.confidence,
            match_method=BankMatchMethod.AUTO.value,
            match_reasons=_reasons(c),
            matched_by=actor_name or "system",
        )
        session.add(row)
        await session.flush()
        clear_category_on_match(txn)
        txn.match_status = BankTxnMatchStatus.MATCHED.value
        written = 1
        await log_event(
            session,
            "bank_txn_matched",
            tenant_id=tenant_id,
            invoice_id=c.invoice_id,
            detail={
                "bank_transaction_id": txn.id,
                "match_id": row.id,
                "matched_type": c.matched_type,
                "matched_id": c.matched_id,
                "match_method": BankMatchMethod.AUTO.value,
                "match_confidence": float(c.confidence),
                "allocated_amount": f"{allocated:.2f}",
                "match_reasons": _reasons(c),
            },
            actor_name=actor_name,
            actor_email=actor_email,
            client_ip=client_ip,
        )
    else:
        # Suggested: all candidates at/above suggest threshold (including demoted autos)
        to_write = candidates if tie_demoted else [
            c
            for c in candidates
            if c.confidence >= Decimal(str(SUGGESTED_MATCH_CONFIDENCE_THRESHOLD))
        ]
        for c in to_write:
            allocated = min(_q(txn.amount), c.remaining)
            row = BankTransactionMatch(
                tenant_id=tenant_id,
                bank_transaction_id=txn.id,
                matched_type=c.matched_type,
                matched_id=c.matched_id,
                allocated_amount=allocated,
                match_confidence=c.confidence,
                match_method=BankMatchMethod.SUGGESTED.value,
                match_reasons={
                    **_reasons(c),
                    "tie_demoted_from_auto": tie_demoted and c.auto_eligible,
                },
                matched_by=actor_name or "system",
            )
            session.add(row)
            await session.flush()
            written += 1
            await log_event(
                session,
                "bank_txn_match_suggested",
                tenant_id=tenant_id,
                invoice_id=c.invoice_id,
                detail={
                    "bank_transaction_id": txn.id,
                    "match_id": row.id,
                    "matched_type": c.matched_type,
                    "matched_id": c.matched_id,
                    "match_method": BankMatchMethod.SUGGESTED.value,
                    "match_confidence": float(c.confidence),
                    "allocated_amount": f"{allocated:.2f}",
                    "match_reasons": row.match_reasons,
                    "tie_demoted": tie_demoted,
                },
                actor_name=actor_name,
                actor_email=actor_email,
                client_ip=client_ip,
            )
        txn.match_status = (
            BankTxnMatchStatus.SUGGESTED.value
            if written
            else BankTxnMatchStatus.UNMATCHED.value
        )

    await session.flush()
    return MatchRunResult(
        transaction_id=txn.id,
        status=txn.match_status,
        matches_written=written,
        auto_matched=use_auto,
        tie_demoted=tie_demoted,
    )


async def run_match_for_account(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    account: BankAccount,
    actor_name: str | None,
    actor_email: str | None,
    client_ip: str | None = None,
) -> list[MatchRunResult]:
    stmt = select(BankTransaction).where(
        BankTransaction.tenant_id == tenant_id,
        BankTransaction.bank_account_id == account.id,
        BankTransaction.match_status.in_(
            [
                BankTxnMatchStatus.UNMATCHED.value,
                BankTxnMatchStatus.SUGGESTED.value,
            ]
        ),
    ).order_by(BankTransaction.txn_date.asc(), BankTransaction.id.asc())
    txns = list((await session.execute(stmt)).scalars().all())
    results: list[MatchRunResult] = []
    for txn in txns:
        results.append(
            await run_match_for_transaction(
                session,
                tenant_id=tenant_id,
                account=account,
                txn=txn,
                actor_name=actor_name,
                actor_email=actor_email,
                client_ip=client_ip,
            )
        )
    return results


async def create_manual_match(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    account: BankAccount,
    txn: BankTransaction,
    matched_type: Literal["payment", "collection"],
    matched_id: int,
    allocated_amount: Decimal | None,
    actor_name: str | None,
    actor_email: str | None,
    client_ip: str | None = None,
) -> BankTransactionMatch:
    if txn.match_status == BankTxnMatchStatus.EXCLUDED.value:
        raise ValueError("Cannot match an excluded transaction — reopen exclude first")
    if txn.match_status == BankTxnMatchStatus.POSTED.value:
        raise ValueError("Cannot match a posted bank line — reverse the journal first")

    invoice_id: int | None = None
    remaining: Decimal

    if matched_type == BankMatchEntityType.PAYMENT.value:
        if txn.direction != BankTxnDirection.DEBIT.value:
            raise ValueError("Money-out lines can only match payments")
        payment = await session.get(Payment, matched_id)
        if payment is None or payment.tenant_id != tenant_id:
            raise LookupError("Payment not found")
        gross = await _payment_gross_compare(payment, bank_currency=account.currency)
        if gross is None:
            raise ValueError("Payment currency cannot be compared to this bank account")
        allocated_sum = await _allocated_sum(
            session,
            tenant_id=tenant_id,
            matched_type=matched_type,
            matched_id=matched_id,
        )
        remaining = _q(gross[0] - allocated_sum)
        invoice_id = payment.invoice_id
    else:
        if txn.direction != BankTxnDirection.CREDIT.value:
            raise ValueError("Money-in lines can only match collections")
        collection = await session.get(Collection, matched_id)
        if collection is None or collection.tenant_id != tenant_id:
            raise LookupError("Collection not found")
        gross = await _collection_gross_compare(
            collection, bank_currency=account.currency
        )
        if gross is None:
            raise ValueError(
                "Collection currency differs from bank account currency — not eligible"
            )
        allocated_sum = await _allocated_sum(
            session,
            tenant_id=tenant_id,
            matched_type=matched_type,
            matched_id=matched_id,
        )
        remaining = _q(gross[0] - allocated_sum)
        invoice_id = collection.invoice_id

    if remaining <= _ZERO:
        raise ValueError("Nothing remaining to allocate on this payment/collection")

    alloc = _q(allocated_amount) if allocated_amount is not None else min(_q(txn.amount), remaining)
    if alloc <= _ZERO:
        raise ValueError("allocated_amount must be positive")
    if alloc > remaining:
        raise ValueError("allocated_amount exceeds remaining unallocated amount")
    if alloc > _q(txn.amount):
        raise ValueError("allocated_amount exceeds bank line amount")

    # Expire open suggestions on this txn
    await _void_open_suggestions(
        session,
        tenant_id=tenant_id,
        txn=txn,
        actor_name=actor_name,
        actor_email=actor_email,
        client_ip=client_ip,
    )

    row = BankTransactionMatch(
        tenant_id=tenant_id,
        bank_transaction_id=txn.id,
        matched_type=matched_type,
        matched_id=matched_id,
        allocated_amount=alloc,
        match_confidence=Decimal("1.0000"),
        match_method=BankMatchMethod.MANUAL.value,
        match_reasons={"manual": True, "remaining_before": f"{remaining:.2f}"},
        matched_by=actor_name or "user",
    )
    session.add(row)
    clear_category_on_match(txn)
    txn.match_status = BankTxnMatchStatus.MATCHED.value
    await session.flush()
    await log_event(
        session,
        "bank_txn_matched",
        tenant_id=tenant_id,
        invoice_id=invoice_id,
        detail={
            "bank_transaction_id": txn.id,
            "match_id": row.id,
            "matched_type": matched_type,
            "matched_id": matched_id,
            "match_method": BankMatchMethod.MANUAL.value,
            "match_confidence": 1.0,
            "allocated_amount": f"{alloc:.2f}",
        },
        actor_name=actor_name,
        actor_email=actor_email,
        client_ip=client_ip,
    )
    return row


async def confirm_suggested_match(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    match: BankTransactionMatch,
    txn: BankTransaction,
    actor_name: str | None,
    actor_email: str | None,
    client_ip: str | None = None,
) -> BankTransactionMatch:
    if match.unmatched_at is not None:
        raise ValueError("Match is no longer active")
    if match.match_method != BankMatchMethod.SUGGESTED.value:
        raise ValueError("Only suggested matches can be confirmed")

    # Void sibling suggestions on same txn
    siblings = list(
        (
            await session.execute(
                select(BankTransactionMatch).where(
                    BankTransactionMatch.tenant_id == tenant_id,
                    BankTransactionMatch.bank_transaction_id == txn.id,
                    BankTransactionMatch.unmatched_at.is_(None),
                    BankTransactionMatch.id != match.id,
                    BankTransactionMatch.match_method == BankMatchMethod.SUGGESTED.value,
                )
            )
        ).scalars().all()
    )
    now = datetime.now(timezone.utc)
    for sib in siblings:
        sib.unmatched_at = now
        sib.unmatch_reason = "rejected_on_confirm_other"
        await log_event(
            session,
            "bank_txn_unmatched",
            tenant_id=tenant_id,
            detail={
                "bank_transaction_id": txn.id,
                "match_id": sib.id,
                "reason": "rejected_on_confirm_other",
                "confirmed_match_id": match.id,
            },
            actor_name=actor_name,
            actor_email=actor_email,
            client_ip=client_ip,
        )

    before = {"match_status": txn.match_status, "match_method": match.match_method}
    clear_category_on_match(txn)
    txn.match_status = BankTxnMatchStatus.MATCHED.value
    await session.flush()
    await log_event(
        session,
        "bank_txn_match_confirmed",
        tenant_id=tenant_id,
        detail={
            "bank_transaction_id": txn.id,
            "match_id": match.id,
            "matched_type": match.matched_type,
            "matched_id": match.matched_id,
            "before": before,
            "after": {"match_status": txn.match_status},
        },
        actor_name=actor_name,
        actor_email=actor_email,
        client_ip=client_ip,
    )
    return match


async def unmatch(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    match: BankTransactionMatch,
    txn: BankTransaction,
    reason: str | None,
    actor_name: str | None,
    actor_email: str | None,
    client_ip: str | None = None,
) -> BankTransactionMatch:
    if match.unmatched_at is not None:
        raise ValueError("Match is already inactive")
    before = {
        "match_status": txn.match_status,
        "matched_type": match.matched_type,
        "matched_id": match.matched_id,
        "allocated_amount": f"{match.allocated_amount:.2f}",
    }
    match.unmatched_at = datetime.now(timezone.utc)
    match.unmatch_reason = (reason or "").strip() or "user_unmatch"
    await _refresh_txn_match_status(session, tenant_id=tenant_id, txn=txn)
    # After unmatch, if only suggestions remain, status suggested; if none, unmatched
    active = list(
        (
            await session.execute(
                select(BankTransactionMatch).where(
                    BankTransactionMatch.tenant_id == tenant_id,
                    BankTransactionMatch.bank_transaction_id == txn.id,
                    BankTransactionMatch.unmatched_at.is_(None),
                )
            )
        ).scalars().all()
    )
    if not active:
        txn.match_status = BankTxnMatchStatus.UNMATCHED.value
    elif all(a.match_method == BankMatchMethod.SUGGESTED.value for a in active):
        txn.match_status = BankTxnMatchStatus.SUGGESTED.value
    else:
        txn.match_status = BankTxnMatchStatus.MATCHED.value
    await session.flush()
    await log_event(
        session,
        "bank_txn_unmatched",
        tenant_id=tenant_id,
        detail={
            "bank_transaction_id": txn.id,
            "match_id": match.id,
            "reason": match.unmatch_reason,
            "before": before,
            "after": {
                "match_status": txn.match_status,
                "unmatched_at": match.unmatched_at.isoformat(),
            },
        },
        actor_name=actor_name,
        actor_email=actor_email,
        client_ip=client_ip,
    )
    return match


async def exclude_transaction(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    txn: BankTransaction,
    reason: str | None,
    actor_name: str | None,
    actor_email: str | None,
    client_ip: str | None = None,
) -> BankTransaction:
    if txn.match_status == BankTxnMatchStatus.POSTED.value:
        raise ValueError("Cannot exclude a posted bank line — reverse the journal first")
    before = {"match_status": txn.match_status}
    # Void active matches
    active = list(
        (
            await session.execute(
                select(BankTransactionMatch).where(
                    BankTransactionMatch.tenant_id == tenant_id,
                    BankTransactionMatch.bank_transaction_id == txn.id,
                    BankTransactionMatch.unmatched_at.is_(None),
                )
            )
        ).scalars().all()
    )
    now = datetime.now(timezone.utc)
    for row in active:
        row.unmatched_at = now
        row.unmatch_reason = "excluded"
    txn.match_status = BankTxnMatchStatus.EXCLUDED.value
    await session.flush()
    await log_event(
        session,
        "bank_txn_excluded",
        tenant_id=tenant_id,
        detail={
            "bank_transaction_id": txn.id,
            "reason": (reason or "").strip() or None,
            "before": before,
            "after": {"match_status": txn.match_status},
            "voided_match_ids": [r.id for r in active],
        },
        actor_name=actor_name,
        actor_email=actor_email,
        client_ip=client_ip,
    )
    return txn


async def get_match(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    match_id: int,
) -> BankTransactionMatch | None:
    stmt = select(BankTransactionMatch).where(
        BankTransactionMatch.tenant_id == tenant_id,
        BankTransactionMatch.id == match_id,
    )
    return (await session.execute(stmt)).scalar_one_or_none()
