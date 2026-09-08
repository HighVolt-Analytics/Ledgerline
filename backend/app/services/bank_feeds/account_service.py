"""Bank account CRUD helpers."""

from __future__ import annotations

import re
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.bank_feed import BankAccount, BankAccountStatus, BankConnectionType
from app.services.rule_book.rule_book_mapper import load_classification_config


def mask_account_number(account_number: str | None) -> str | None:
    digits = re.sub(r"\D", "", (account_number or "").strip())
    if not digits:
        raw = (account_number or "").strip()
        if not raw:
            return None
        return f"****{raw[-4:]}" if len(raw) >= 4 else raw
    if len(digits) <= 4:
        return digits
    return f"****{digits[-4:]}"


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
    account_number: str,
    coa_account_name: str,
    account_mask: str | None = None,
) -> BankAccount:
    from app.services.rule_book.account_mapper import resolve_category_for_config

    config = await load_classification_config(session, tenant_id)
    mapping = resolve_category_for_config(coa_account_name.strip(), config)
    number = (account_number or "").strip()
    mask = (account_mask or "").strip() or mask_account_number(number)

    row = BankAccount(
        tenant_id=tenant_id,
        name=name.strip(),
        currency=(currency or "").strip().upper()[:3],
        account_number=number or None,
        account_mask=mask,
        coa_account_code=mapping.account_code,
        coa_account_name=mapping.account_name,
        connection_type=BankConnectionType.MANUAL.value,
        status=BankAccountStatus.ACTIVE.value,
    )
    session.add(row)
    await session.flush()
    return row


async def update_bank_account(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    account_id: int,
    name: str,
    currency: str,
    account_number: str,
    coa_account_name: str,
    account_mask: str | None = None,
) -> BankAccount | None:
    from app.services.rule_book.account_mapper import resolve_category_for_config

    row = await get_bank_account(session, tenant_id=tenant_id, account_id=account_id)
    if row is None:
        return None
    config = await load_classification_config(session, tenant_id)
    mapping = resolve_category_for_config(coa_account_name.strip(), config)
    number = (account_number or "").strip()
    row.name = name.strip()
    row.currency = (currency or "").strip().upper()[:3]
    row.account_number = number or None
    row.account_mask = (account_mask or "").strip() or mask_account_number(number)
    row.coa_account_code = mapping.account_code
    row.coa_account_name = mapping.account_name
    await session.flush()
    return row


async def archive_bank_account(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    account_id: int,
) -> BankAccount | None:
    """Soft-delete: mark archived so it leaves active lists but history remains."""
    row = await get_bank_account(session, tenant_id=tenant_id, account_id=account_id)
    if row is None:
        return None
    row.status = BankAccountStatus.ARCHIVED.value
    await session.flush()
    return row
