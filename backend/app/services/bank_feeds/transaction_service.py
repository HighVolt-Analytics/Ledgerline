"""Read helpers for bank transactions and imports."""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.bank_feed import (
    BankFeedImport,
    BankTransaction,
    BankTransactionMatch,
    BankTransactionNote,
    BankTxnMatchStatus,
)


async def get_import(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    import_id: int,
) -> BankFeedImport | None:
    stmt = select(BankFeedImport).where(
        BankFeedImport.tenant_id == tenant_id,
        BankFeedImport.id == import_id,
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def list_imports(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    bank_account_id: int,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[BankFeedImport], int]:
    filters = [
        BankFeedImport.tenant_id == tenant_id,
        BankFeedImport.bank_account_id == bank_account_id,
    ]
    count_stmt = select(func.count()).select_from(BankFeedImport).where(*filters)
    total = int((await session.execute(count_stmt)).scalar() or 0)

    page = max(1, page)
    page_size = min(max(1, page_size), 100)
    stmt = (
        select(BankFeedImport)
        .where(*filters)
        .order_by(BankFeedImport.imported_at.desc(), BankFeedImport.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    rows = list((await session.execute(stmt)).scalars().all())
    return rows, total


async def list_transactions(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    bank_account_id: int,
    match_status: str | None = None,
    reconcile: bool = False,
    date_from: date | None = None,
    date_to: date | None = None,
    page: int = 1,
    page_size: int = 50,
) -> tuple[list[BankTransaction], int]:
    filters = [
        BankTransaction.tenant_id == tenant_id,
        BankTransaction.bank_account_id == bank_account_id,
    ]
    if reconcile:
        filters.append(
            BankTransaction.match_status.in_(
                [
                    BankTxnMatchStatus.UNMATCHED.value,
                    BankTxnMatchStatus.SUGGESTED.value,
                ]
            )
        )
    elif match_status:
        filters.append(BankTransaction.match_status == match_status)
    if date_from:
        filters.append(BankTransaction.txn_date >= date_from)
    if date_to:
        filters.append(BankTransaction.txn_date <= date_to)

    count_stmt = select(func.count()).select_from(BankTransaction).where(*filters)
    total = int((await session.execute(count_stmt)).scalar() or 0)

    page = max(1, page)
    page_size = min(max(1, page_size), 200)
    stmt = (
        select(BankTransaction)
        .where(*filters)
        .order_by(BankTransaction.txn_date.desc(), BankTransaction.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    rows = list((await session.execute(stmt)).scalars().all())
    return rows, total


async def get_transaction(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    transaction_id: int,
) -> BankTransaction | None:
    stmt = select(BankTransaction).where(
        BankTransaction.tenant_id == tenant_id,
        BankTransaction.id == transaction_id,
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def list_matches_for_transaction(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    bank_transaction_id: int,
    active_only: bool = False,
) -> list[BankTransactionMatch]:
    filters = [
        BankTransactionMatch.tenant_id == tenant_id,
        BankTransactionMatch.bank_transaction_id == bank_transaction_id,
    ]
    if active_only:
        filters.append(BankTransactionMatch.unmatched_at.is_(None))
    stmt = (
        select(BankTransactionMatch)
        .where(*filters)
        .order_by(BankTransactionMatch.matched_at.desc(), BankTransactionMatch.id.desc())
    )
    return list((await session.execute(stmt)).scalars().all())


async def list_notes(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    bank_transaction_id: int,
) -> list[BankTransactionNote]:
    stmt = (
        select(BankTransactionNote)
        .where(
            BankTransactionNote.tenant_id == tenant_id,
            BankTransactionNote.bank_transaction_id == bank_transaction_id,
        )
        .order_by(BankTransactionNote.created_at.asc(), BankTransactionNote.id.asc())
    )
    return list((await session.execute(stmt)).scalars().all())


async def create_note(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    bank_transaction_id: int,
    body: str,
    author_user_id: int | None,
) -> BankTransactionNote:
    text = body.strip()
    if not text:
        raise ValueError("Note body is required")
    row = BankTransactionNote(
        tenant_id=tenant_id,
        bank_transaction_id=bank_transaction_id,
        body=text,
        author_user_id=author_user_id,
    )
    session.add(row)
    await session.flush()
    return row


async def list_notes(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    bank_transaction_id: int,
) -> list[BankTransactionNote]:
    stmt = (
        select(BankTransactionNote)
        .where(
            BankTransactionNote.tenant_id == tenant_id,
            BankTransactionNote.bank_transaction_id == bank_transaction_id,
        )
        .order_by(BankTransactionNote.created_at.asc(), BankTransactionNote.id.asc())
    )
    return list((await session.execute(stmt)).scalars().all())


async def create_note(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    bank_transaction_id: int,
    body: str,
    author_user_id: int | None,
) -> BankTransactionNote:
    text = body.strip()
    if not text:
        raise ValueError("Note body is required")
    row = BankTransactionNote(
        tenant_id=tenant_id,
        bank_transaction_id=bank_transaction_id,
        body=text,
        author_user_id=author_user_id,
    )
    session.add(row)
    await session.flush()
    return row
