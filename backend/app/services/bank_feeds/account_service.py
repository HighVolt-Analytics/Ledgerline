"""Bank account CRUD helpers."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.bank_feed import BankAccount, BankAccountStatus, BankConnectionType
from app.services.rule_book.rule_book_mapper import (
    get_bank_account_mapping,
    load_classification_config,
)


async def list_bank_accounts(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    include_archived: bool = False,
) -> list[BankAccount]:
    stmt = select(BankAccount).where(BankAccount.tenant_id == tenant_id)
    if not include_archived:
        stmt = stmt.where(BankAccount.status == BankAccountStatus.ACTIVE.value)
    stmt = stmt.order_by(BankAccount.name.asc(), BankAccount.id.asc())
    return list((await session.execute(stmt)).scalars().all())


async def get_bank_account(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    account_id: int,
) -> BankAccount | None:
    stmt = select(BankAccount).where(
        BankAccount.tenant_id == tenant_id,
        BankAccount.id == account_id,
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def create_bank_account(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    name: str,
    currency: str,
    account_mask: str | None = None,
    coa_account_name: str | None = None,
) -> BankAccount:
    config = await load_classification_config(session, tenant_id)
    if coa_account_name and coa_account_name.strip():
        from app.services.rule_book.account_mapper import resolve_category_for_config

        mapping = resolve_category_for_config(coa_account_name.strip(), config)
    else:
        mapping = get_bank_account_mapping(config)

    row = BankAccount(
        tenant_id=tenant_id,
        name=name.strip(),
        currency=(currency or "").strip().upper()[:3],
        account_mask=(account_mask or "").strip() or None,
        coa_account_code=mapping.account_code,
        coa_account_name=mapping.account_name,
        connection_type=BankConnectionType.MANUAL.value,
        status=BankAccountStatus.ACTIVE.value,
    )
    session.add(row)
    await session.flush()
    return row
