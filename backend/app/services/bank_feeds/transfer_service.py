"""Post (and reverse) a bank-to-bank transfer journal for an unmatched line."""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.bank_feed import (
    BankAccount,
    BankTransaction,
    BankTxnDirection,
    BankTxnMatchStatus,
)
from app.models.journal import EntryType, JournalEntryKind
from app.models.journal_batch import JournalBatch
from app.models.tenant import Tenant
from app.services.audit.audit_service import log_event
from app.services.bank_feeds.create_service import (
    BankCreateConflict,
    BankCreateError,
    claim_bank_create_slot,
    claim_bank_reverse_slot,
)
from app.services.payments.journal_fx import round_money
from app.services.payments.journal_generator import JournalLine
from app.services.payments.journal_persist_service import persist_journal_lines
from app.services.payments.journal_reversal_service import reverse_batch

_ZERO = Decimal("0.00")


async def transfer_between_accounts(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    txn: BankTransaction,
    source_account: BankAccount,
    destination_account: BankAccount,
    description: str,
    actor_name: str | None,
    actor_email: str | None,
    client_ip: str | None = None,
) -> BankTransaction:
    if source_account.id == destination_account.id:
        raise BankCreateError("Choose a different destination account")
    if destination_account.tenant_id != tenant_id:
        raise BankCreateError("Destination account not found")

    desc = description.strip()
    if not desc:
        raise BankCreateError("Description is required")

    tenant = await session.get(Tenant, tenant_id)
    if tenant is None:
        raise BankCreateError("Tenant not found")

    won = await claim_bank_create_slot(
        session, tenant_id=tenant_id, transaction_id=txn.id
    )
    if not won:
        raise BankCreateConflict("This bank line already has a journal")

    gross = round_money(Decimal(str(txn.amount)).copy_abs())
    on = txn.txn_date
    txn_currency = (txn.currency or "").strip().upper() or tenant.currency
    base_currency = (tenant.currency or "").strip().upper()

    source_line = JournalLine(
        date=on,
        account_code=source_account.coa_account_code[:20],
        account_name=source_account.coa_account_name[:255],
        debit=_ZERO,
        credit=_ZERO,
        entry_type=EntryType.CREDIT,
        txn_currency=txn_currency,
        base_currency=base_currency,
    )
    dest_line = JournalLine(
        date=on,
        account_code=destination_account.coa_account_code[:20],
        account_name=destination_account.coa_account_name[:255],
        debit=_ZERO,
        credit=_ZERO,
        entry_type=EntryType.DEBIT,
        txn_currency=txn_currency,
        base_currency=base_currency,
    )

    money_out = txn.direction == BankTxnDirection.DEBIT.value
    if money_out:
        dest_line.debit = gross
        dest_line.credit = _ZERO
        dest_line.entry_type = EntryType.DEBIT
        source_line.debit = _ZERO
        source_line.credit = gross
        source_line.entry_type = EntryType.CREDIT
    else:
        source_line.debit = gross
        source_line.credit = _ZERO
        source_line.entry_type = EntryType.DEBIT
        dest_line.debit = _ZERO
        dest_line.credit = gross
        dest_line.entry_type = EntryType.CREDIT

    batch = await persist_journal_lines(
        session,
        None,
        [dest_line, source_line],
        entry_kind=JournalEntryKind.BANK_TRANSFER,
        tenant_id=tenant_id,
        base_currency=base_currency,
    )
    await session.flush()

    attach = await session.execute(
        update(BankTransaction)
        .where(
            BankTransaction.id == txn.id,
            BankTransaction.tenant_id == tenant_id,
            BankTransaction.match_status == BankTxnMatchStatus.POSTED.value,
            BankTransaction.posted_journal_batch_id.is_(None),
        )
        .values(posted_journal_batch_id=batch.id)
        .execution_options(synchronize_session="fetch")
    )
    if attach.rowcount != 1:
        raise BankCreateConflict("This bank line already has a journal")

    flags = dict(txn.review_flags) if isinstance(txn.review_flags, dict) else {}
    flags["transfer_posting"] = {
        "description": desc,
        "from_account_id": source_account.id,
        "from_account_name": source_account.name,
        "to_account_id": destination_account.id,
        "to_account_name": destination_account.name,
        "journal_batch_id": batch.id,
    }
    txn.review_flags = flags
    await session.flush()

    await log_event(
        session,
        "bank_txn_transfer_posted",
        tenant_id=tenant_id,
        detail={
            "bank_transaction_id": txn.id,
            "journal_batch_id": batch.id,
            "from_account_id": source_account.id,
            "to_account_id": destination_account.id,
            "amount": str(gross),
            "description": desc,
            "actor_user": actor_name,
        },
        actor_name=actor_name,
        actor_email=actor_email,
        client_ip=client_ip,
    )
    await session.refresh(txn)
    return txn


async def reverse_bank_posting(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    txn: BankTransaction,
    actor_name: str | None,
    actor_email: str | None,
    client_ip: str | None = None,
) -> BankTransaction:
    """Reverse a posted create or transfer journal."""
    batch_id = txn.posted_journal_batch_id
    if txn.match_status != BankTxnMatchStatus.POSTED.value or batch_id is None:
        raise BankCreateError("This bank line is not posted")

    won = await claim_bank_reverse_slot(
        session,
        tenant_id=tenant_id,
        transaction_id=txn.id,
        posted_journal_batch_id=batch_id,
    )
    if not won:
        raise BankCreateConflict("This posting has already been reversed")

    batch = await session.get(JournalBatch, batch_id)
    if batch is None or batch.tenant_id != tenant_id:
        raise BankCreateError("Posted journal was not found")
    reversal = await reverse_batch(session, batch, reason="bank_posting_reverse")

    flags = dict(txn.review_flags) if isinstance(txn.review_flags, dict) else {}
    was_transfer = isinstance(flags.get("transfer_posting"), dict)
    reversal_id = reversal.id if reversal is not None else None
    for key in ("create_posting", "transfer_posting"):
        posting = flags.get(key)
        if isinstance(posting, dict):
            flags[key] = {**posting, "reversed_by_batch_id": reversal_id}
    txn.review_flags = flags
    await session.flush()

    event = "bank_txn_transfer_reversed" if was_transfer else "bank_txn_create_reversed"
    await log_event(
        session,
        event,
        tenant_id=tenant_id,
        detail={
            "bank_transaction_id": txn.id,
            "journal_batch_id": batch_id,
            "reversal_batch_id": reversal_id,
            "actor_user": actor_name,
        },
        actor_name=actor_name,
        actor_email=actor_email,
        client_ip=client_ip,
    )
    await session.refresh(txn)
    return txn
