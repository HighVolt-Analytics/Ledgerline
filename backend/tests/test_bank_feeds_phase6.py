"""Bank feeds Phase 6 — create/reverse journals from unmatched lines."""

from __future__ import annotations

from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.bank_feed import BankAccount, BankTransaction
from app.models.invoice import Invoice
from app.models.journal import JournalEntry, JournalEntryKind
from app.models.journal_batch import JournalBatch
from app.models.tenant_module import TenantModule
from app.services.bank_feeds.create_service import (
    BankCreateConflict,
    BankCreateError,
    claim_bank_create_slot,
    claim_bank_reverse_slot,
    create_bank_journal,
    reverse_bank_journal,
    inclusive_tax_split,
)
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


async def _import_one_out(client: AsyncClient, amount: str = "110.00") -> tuple[int, int]:
    acc = await client.post(
        "/api/bank-feeds/accounts",
        json={"name": "Ops AUD", "currency": "AUD"},
    )
    assert acc.status_code == 201, acc.text
    account_id = acc.json()["data"]["id"]
    csv = (
        "Date,Description,Amount,Direction,Balance,Reference\n"
        f"2026-05-01,Office supplies Acme,{amount},out,1000.00,X1\n"
    ).encode()
    uploaded = await client.post(
        f"/api/bank-feeds/accounts/{account_id}/imports",
        files={"file": ("a.csv", csv, "text/csv")},
    )
    assert uploaded.status_code == 200, uploaded.text
    listed = await client.get(f"/api/bank-feeds/accounts/{account_id}/transactions")
    txn = listed.json()["data"]["items"][0]
    return account_id, txn["id"]


def test_inclusive_tax_split_gst_inclusive() -> None:
    net, tax = inclusive_tax_split(Decimal("110.00"), Decimal("10"))
    assert net == Decimal("100.00")
    assert tax == Decimal("10.00")
    zero_net, zero_tax = inclusive_tax_split(Decimal("50.00"), Decimal("0"))
    assert zero_net == Decimal("50.00")
    assert zero_tax == Decimal("0.00")


@pytest.mark.asyncio
async def test_create_posts_null_invoice_journal(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _enable_bank_feeds(db_session)
    _account_id, txn_id = await _import_one_out(client)

    created = await client.post(
        f"/api/bank-feeds/transactions/{txn_id}/create",
        json={
            "party_type": "vendor",
            "create_party": {"name": "Acme Supplies"},
            "ledger": "Operating Expenses",
            "description": "Office supplies",
            "tax_rate_percent": 10,
        },
    )
    assert created.status_code == 200, created.text
    body = created.json()["data"]
    assert body["match_status"] == "posted"
    assert body["posted_journal_batch_id"] is not None
    batch_id = body["posted_journal_batch_id"]

    entries = list(
        (
            await db_session.execute(
                select(JournalEntry).where(JournalEntry.batch_id == batch_id)
            )
        ).scalars().all()
    )
    assert entries
    assert all(e.invoice_id is None for e in entries)
    assert all(e.entry_kind == JournalEntryKind.BANK_CREATE for e in entries)
    debit = sum((e.debit for e in entries), Decimal("0"))
    credit = sum((e.credit for e in entries), Decimal("0"))
    assert debit == credit == Decimal("110.00")
    by_name = {e.account_name: e for e in entries}
    assert by_name["Operating Expenses"].debit == Decimal("100.00")
    assert by_name["GST Paid"].debit == Decimal("10.00")
    assert any(e.credit == Decimal("110.00") for e in entries)
    assert any(e.vendor_registry_id is not None for e in entries)

    joined_ids = list(
        (
            await db_session.execute(
                select(JournalEntry.id).join(
                    Invoice, Invoice.id == JournalEntry.invoice_id
                )
            )
        ).scalars().all()
    )
    bank_ids = {e.id for e in entries}
    assert bank_ids.isdisjoint(set(joined_ids))


@pytest.mark.asyncio
async def test_create_rejected_when_not_unmatched(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _enable_bank_feeds(db_session)
    _account_id, txn_id = await _import_one_out(client)
    payload = {
        "party_type": "vendor",
        "create_party": {"name": "Once Vendor"},
        "ledger": "Operating Expenses",
        "description": "Once",
        "tax_rate_percent": 0,
    }
    first = await client.post(f"/api/bank-feeds/transactions/{txn_id}/create", json=payload)
    assert first.status_code == 200, first.text
    second = await client.post(f"/api/bank-feeds/transactions/{txn_id}/create", json=payload)
    assert second.status_code == 409


@pytest.mark.asyncio
async def test_create_claim_rejects_second_session(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _enable_bank_feeds(db_session)
    account_id, txn_id = await _import_one_out(client, "80.00")

    vendor = await client.post(
        "/api/vendors",
        json={
            "vendor_slug": "race-vendor",
            "vendor_name": "Race Vendor",
            "sender_pattern": "bank:race-vendor",
            "approved": True,
        },
    )
    assert vendor.status_code == 201, vendor.text
    vendor_id = vendor.json()["data"]["id"]

    bind = db_session.bind
    assert bind is not None
    factory = async_sessionmaker(bind, class_=AsyncSession, expire_on_commit=False)

    async with factory() as session:
        txn = await session.get(BankTransaction, txn_id)
        account = await session.get(BankAccount, account_id)
        assert txn is not None and account is not None
        await create_bank_journal(
            session,
            tenant_id=TESTING_TENANT_UUID,
            txn=txn,
            account=account,
            party_type="vendor",
            party_id=vendor_id,
            create_party=None,
            ledger="Operating Expenses",
            description="Race create",
            tax_rate_percent=0,
            actor_name="test",
            actor_email=None,
        )
        await session.commit()

    async with factory() as session:
        txn = await session.get(BankTransaction, txn_id)
        account = await session.get(BankAccount, account_id)
        assert txn is not None and account is not None
        with pytest.raises(BankCreateConflict):
            await create_bank_journal(
                session,
                tenant_id=TESTING_TENANT_UUID,
                txn=txn,
                account=account,
                party_type="vendor",
                party_id=vendor_id,
                create_party=None,
                ledger="Operating Expenses",
                description="Race create",
                tax_rate_percent=0,
                actor_name="test",
                actor_email=None,
            )

    count = (
        await db_session.execute(
            select(func.count()).select_from(JournalBatch).where(
                JournalBatch.tenant_id == TESTING_TENANT_UUID,
                JournalBatch.entry_kind == JournalEntryKind.BANK_CREATE,
                JournalBatch.reversal_reason.is_(None),
            )
        )
    ).scalar_one()
    assert count == 1


@pytest.mark.asyncio
async def test_reverse_claim_rejects_second_session(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _enable_bank_feeds(db_session)
    _account_id, txn_id = await _import_one_out(client, "40.00")
    created = await client.post(
        f"/api/bank-feeds/transactions/{txn_id}/create",
        json={
            "party_type": "vendor",
            "create_party": {"name": "Reverse Vendor"},
            "ledger": "Operating Expenses",
            "description": "To reverse",
            "tax_rate_percent": 0,
        },
    )
    assert created.status_code == 200, created.text
    original_batch = created.json()["data"]["posted_journal_batch_id"]

    bind = db_session.bind
    assert bind is not None
    factory = async_sessionmaker(bind, class_=AsyncSession, expire_on_commit=False)

    async with factory() as session:
        txn = await session.get(BankTransaction, txn_id)
        assert txn is not None
        await reverse_bank_journal(
            session,
            tenant_id=TESTING_TENANT_UUID,
            txn=txn,
            actor_name="test",
            actor_email=None,
        )
        await session.commit()

    async with factory() as session:
        txn = await session.get(BankTransaction, txn_id)
        assert txn is not None
        with pytest.raises(BankCreateError, match="not posted"):
            await reverse_bank_journal(
                session,
                tenant_id=TESTING_TENANT_UUID,
                txn=txn,
                actor_name="test",
                actor_email=None,
            )

    db_session.expire_all()
    refreshed = await db_session.get(BankTransaction, txn_id)
    assert refreshed is not None
    assert refreshed.match_status == "unmatched"
    assert refreshed.posted_journal_batch_id is None

    reversal_count = (
        await db_session.execute(
            select(func.count()).select_from(JournalBatch).where(
                JournalBatch.tenant_id == TESTING_TENANT_UUID,
                JournalBatch.entry_kind == JournalEntryKind.BANK_CREATE,
                JournalBatch.reversal_reason.is_not(None),
            )
        )
    ).scalar_one()
    assert reversal_count == 1

    original = await db_session.get(JournalBatch, original_batch)
    assert original is not None
    assert original.reversed_by_batch_id is not None


@pytest.mark.asyncio
async def test_claim_slots_are_single_use(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _enable_bank_feeds(db_session)
    _account_id, txn_id = await _import_one_out(client, "25.00")
    txn = await db_session.get(BankTransaction, txn_id)
    assert txn is not None

    assert await claim_bank_create_slot(
        db_session, tenant_id=TESTING_TENANT_UUID, transaction_id=txn_id
    )
    assert not await claim_bank_create_slot(
        db_session, tenant_id=TESTING_TENANT_UUID, transaction_id=txn_id
    )
    await db_session.rollback()

    created = await client.post(
        f"/api/bank-feeds/transactions/{txn_id}/create",
        json={
            "party_type": "vendor",
            "create_party": {"name": "Claim Vendor"},
            "ledger": "Operating Expenses",
            "description": "Claim test",
            "tax_rate_percent": 0,
        },
    )
    assert created.status_code == 200, created.text
    batch_id = created.json()["data"]["posted_journal_batch_id"]
    assert batch_id is not None

    assert await claim_bank_reverse_slot(
        db_session,
        tenant_id=TESTING_TENANT_UUID,
        transaction_id=txn_id,
        posted_journal_batch_id=batch_id,
    )
    assert not await claim_bank_reverse_slot(
        db_session,
        tenant_id=TESTING_TENANT_UUID,
        transaction_id=txn_id,
        posted_journal_batch_id=batch_id,
    )
    await db_session.rollback()


@pytest.mark.asyncio
async def test_create_money_in_requires_customer(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _enable_bank_feeds(db_session)
    acc = await client.post(
        "/api/bank-feeds/accounts",
        json={"name": "Ops AUD", "currency": "AUD"},
    )
    account_id = acc.json()["data"]["id"]
    csv = b"""Date,Description,Amount,Direction,Balance,Reference
2026-05-01,Customer receipt,55.00,in,2000.00,IN1
"""
    await client.post(
        f"/api/bank-feeds/accounts/{account_id}/imports",
        files={"file": ("a.csv", csv, "text/csv")},
    )
    listed = await client.get(f"/api/bank-feeds/accounts/{account_id}/transactions")
    txn_id = listed.json()["data"]["items"][0]["id"]
    wrong = await client.post(
        f"/api/bank-feeds/transactions/{txn_id}/create",
        json={
            "party_type": "vendor",
            "create_party": {"name": "Wrong"},
            "ledger": "Operating Revenue",
            "description": "Receipt",
            "tax_rate_percent": 0,
        },
    )
    assert wrong.status_code == 400
    ok = await client.post(
        f"/api/bank-feeds/transactions/{txn_id}/create",
        json={
            "party_type": "customer",
            "create_party": {"name": "Retail Co"},
            "ledger": "Operating Revenue",
            "description": "Receipt",
            "tax_rate_percent": 10,
        },
    )
    assert ok.status_code == 200, ok.text
    batch_id = ok.json()["data"]["posted_journal_batch_id"]
    entries = list(
        (
            await db_session.execute(
                select(JournalEntry).where(JournalEntry.batch_id == batch_id)
            )
        ).scalars().all()
    )
    assert any(e.account_name == "GST Collected" and e.credit == Decimal("5.00") for e in entries)
    assert any(e.account_name == "Operating Revenue" and e.credit == Decimal("50.00") for e in entries)
    posted_tab = await client.get(
        f"/api/bank-feeds/accounts/{account_id}/transactions?match_status=posted"
    )
    assert posted_tab.status_code == 200
    assert len(posted_tab.json()["data"]["items"]) == 1
