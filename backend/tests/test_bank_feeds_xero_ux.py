"""Bank feeds Xero UX — imports list, reconcile filter, transfer, notes."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.bank_feed import BankTransactionNote
from app.models.journal import JournalEntry, JournalEntryKind
from app.models.tenant_module import TenantModule
from app.services.bank_feeds.create_service import claim_bank_create_slot
from app.services.bank_feeds.transfer_service import transfer_between_accounts
from app.tenant_ids import TESTING_TENANT_UUID


async def _enable_bank_feeds(db_session: AsyncSession) -> None:
    db_session.add(
        TenantModule(
            tenant_id=TESTING_TENANT_UUID,
            module_key="bank_feeds",
            is_active=True,
        )
    )
    await db_session.commit()


async def _two_accounts_and_out_txn(client: AsyncClient) -> tuple[int, int, int]:
    acc_a = await client.post(
        "/api/bank-feeds/accounts",
        json={"name": "Ops AUD", "currency": "AUD"},
    )
    acc_b = await client.post(
        "/api/bank-feeds/accounts",
        json={"name": "Savings AUD", "currency": "AUD"},
    )
    assert acc_a.status_code == 201, acc_a.text
    assert acc_b.status_code == 201, acc_b.text
    account_a = acc_a.json()["data"]["id"]
    account_b = acc_b.json()["data"]["id"]
    csv = (
        "Date,Description,Amount,Direction,Balance,Reference\n"
        "2026-05-01,Transfer out test,250.00,out,1000.00,T1\n"
    ).encode()
    uploaded = await client.post(
        f"/api/bank-feeds/accounts/{account_a}/imports",
        files={"file": ("t.csv", csv, "text/csv")},
    )
    assert uploaded.status_code == 200, uploaded.text
    listed = await client.get(f"/api/bank-feeds/accounts/{account_a}/transactions")
    txn_id = listed.json()["data"]["items"][0]["id"]
    return account_a, account_b, txn_id


@pytest.mark.asyncio
async def test_list_imports_for_account(client: AsyncClient, db_session: AsyncSession) -> None:
    await _enable_bank_feeds(db_session)
    account_a, _, _ = await _two_accounts_and_out_txn(client)
    resp = await client.get(f"/api/bank-feeds/accounts/{account_a}/imports")
    assert resp.status_code == 200, resp.text
    items = resp.json()["data"]["items"]
    assert len(items) >= 1
    assert items[0]["accepted_count"] == 1


@pytest.mark.asyncio
async def test_reconcile_filter_merges_unmatched_and_suggested(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _enable_bank_feeds(db_session)
    account_a, _, _ = await _two_accounts_and_out_txn(client)
    resp = await client.get(
        f"/api/bank-feeds/accounts/{account_a}/transactions?reconcile=true"
    )
    assert resp.status_code == 200, resp.text
    items = resp.json()["data"]["items"]
    assert len(items) == 1
    assert items[0]["match_status"] == "unmatched"


@pytest.mark.asyncio
async def test_transfer_posts_bank_transfer_journal(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _enable_bank_feeds(db_session)
    account_a, account_b, txn_id = await _two_accounts_and_out_txn(client)
    resp = await client.post(
        f"/api/bank-feeds/transactions/{txn_id}/transfer",
        json={
            "to_bank_account_id": account_b,
            "description": "Move to savings",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()["data"]
    assert body["match_status"] == "posted"
    batch_id = body["posted_journal_batch_id"]
    assert batch_id is not None

    entries = list(
        (
            await db_session.execute(
                select(JournalEntry).where(JournalEntry.batch_id == batch_id)
            )
        ).scalars().all()
    )
    assert len(entries) == 2
    assert all(e.entry_kind == JournalEntryKind.BANK_TRANSFER for e in entries)


@pytest.mark.asyncio
async def test_transfer_atomic_claim(client: AsyncClient, db_session: AsyncSession) -> None:
    await _enable_bank_feeds(db_session)
    from app.models.bank_feed import BankAccount, BankTransaction
    from app.services.bank_feeds.account_service import get_bank_account

    account_a, account_b, txn_id = await _two_accounts_and_out_txn(client)
    txn = (
        await db_session.execute(
            select(BankTransaction).where(BankTransaction.id == txn_id)
        )
    ).scalar_one()
    source = await get_bank_account(
        db_session, tenant_id=TESTING_TENANT_UUID, account_id=account_a
    )
    dest = await get_bank_account(
        db_session, tenant_id=TESTING_TENANT_UUID, account_id=account_b
    )
    assert source and dest

    await transfer_between_accounts(
        db_session,
        tenant_id=TESTING_TENANT_UUID,
        txn=txn,
        source_account=source,
        destination_account=dest,
        description="First transfer",
        actor_name="test",
        actor_email=None,
    )
    await db_session.commit()

    txn2 = (
        await db_session.execute(
            select(BankTransaction).where(BankTransaction.id == txn_id)
        )
    ).scalar_one()
    won = await claim_bank_create_slot(
        db_session, tenant_id=TESTING_TENANT_UUID, transaction_id=txn_id
    )
    assert won is False
    assert txn2.match_status == "posted"


@pytest.mark.asyncio
async def test_notes_scoped_to_tenant(client: AsyncClient, db_session: AsyncSession) -> None:
    await _enable_bank_feeds(db_session)
    _, _, txn_id = await _two_accounts_and_out_txn(client)
    created = await client.post(
        f"/api/bank-feeds/transactions/{txn_id}/notes",
        json={"body": "Check with finance"},
    )
    assert created.status_code == 201, created.text
    listed = await client.get(f"/api/bank-feeds/transactions/{txn_id}/notes")
    assert listed.status_code == 200, listed.text
    notes = listed.json()["data"]
    assert len(notes) == 1
    assert notes[0]["body"] == "Check with finance"

    rows = list(
        (
            await db_session.execute(select(BankTransactionNote))
        ).scalars().all()
    )
    assert all(r.tenant_id == TESTING_TENANT_UUID for r in rows)
