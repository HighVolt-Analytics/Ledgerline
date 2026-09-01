"""Postgres-only: parallel create/reverse on one bank line (real row-level contention)."""

from __future__ import annotations

import asyncio
import uuid
from collections import Counter
from decimal import Decimal

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import get_settings
from app.database import get_db, get_preauth_db
from app.models.bank_feed import BankTransaction
from app.models.journal import JournalEntryKind
from app.models.journal_batch import JournalBatch
from app.models.tenant import Tenant
from app.models.tenant_module import TenantModule
from app.tenant_ids import TESTING_TENANT_UUID
from tests.auth_test_helpers import seed_admin_user, tenant_auth_headers


def _pg_url() -> str:
    get_settings.cache_clear()
    url = get_settings().database_url
    if "postgresql" not in url or "sqlite" in url:
        pytest.skip("PostgreSQL DATABASE_URL required for concurrent claim tests")
    return url


@pytest_asyncio.fixture
async def pg_client():
    url = _pg_url()
    engine = create_async_engine(url, echo=False, poolclass=NullPool)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def override_get_db():
        async with factory() as session:
            yield session
            await session.commit()

    async def override_get_preauth_db():
        async with factory() as session:
            yield session
            await session.commit()

    from app.main import app

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_preauth_db] = override_get_preauth_db

    async with factory() as session:
        tenant = await session.get(Tenant, TESTING_TENANT_UUID)
        if tenant is None:
            pytest.skip("TESTING_TENANT_UUID not present in local PostgreSQL")

        existing = (
            await session.execute(
                select(TenantModule).where(
                    TenantModule.tenant_id == TESTING_TENANT_UUID,
                    TenantModule.module_key == "bank_feeds",
                )
            )
        ).scalar_one_or_none()
        if existing is None:
            session.add(
                TenantModule(
                    tenant_id=TESTING_TENANT_UUID,
                    module_key="bank_feeds",
                    is_active=True,
                )
            )
        else:
            existing.is_active = True

        suffix = uuid.uuid4().hex[:8]
        _, token = await seed_admin_user(
            session,
            email=f"bf-concur-{suffix}@test.example.com",
            tenant_id=TESTING_TENANT_UUID,
            tenant_slug=tenant.slug,
        )
        await session.commit()

    headers = tenant_auth_headers(token, TESTING_TENANT_UUID)
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers=headers,
    ) as client:
        yield client, factory

    app.dependency_overrides.clear()
    await engine.dispose()


async def _import_unmatched_out(
    client: AsyncClient,
    *,
    amount: str = "77.00",
) -> tuple[int, int]:
    acc = await client.post(
        "/api/bank-feeds/accounts",
        json={"name": f"Concur {uuid.uuid4().hex[:6]}", "currency": "AUD"},
    )
    assert acc.status_code == 201, acc.text
    account_id = acc.json()["data"]["id"]
    csv = (
        "Date,Description,Amount,Direction,Balance,Reference\n"
        f"2026-05-01,Parallel race line,{amount},out,1000.00,RACE\n"
    ).encode()
    uploaded = await client.post(
        f"/api/bank-feeds/accounts/{account_id}/imports",
        files={"file": ("race.csv", csv, "text/csv")},
    )
    assert uploaded.status_code == 200, uploaded.text
    listed = await client.get(f"/api/bank-feeds/accounts/{account_id}/transactions")
    assert listed.status_code == 200, listed.text
    txn_id = listed.json()["data"]["items"][0]["id"]
    return account_id, txn_id


_CREATE_PAYLOAD = {
    "party_type": "vendor",
    "create_party": {"name": "Parallel Vendor"},
    "ledger": "Operating Expenses",
    "description": "Parallel create race",
    "tax_rate_percent": 0,
}


@pytest.mark.asyncio
async def test_parallel_create_exactly_one_wins(pg_client) -> None:
    client, factory = pg_client
    _account_id, txn_id = await _import_unmatched_out(client)

    async def post_create():
        return await client.post(
            f"/api/bank-feeds/transactions/{txn_id}/create",
            json=_CREATE_PAYLOAD,
        )

    first, second = await asyncio.gather(post_create(), post_create())
    statuses = sorted([first.status_code, second.status_code])
    assert statuses == [200, 409], (first.status_code, first.text, second.status_code, second.text)

    winner = first if first.status_code == 200 else second
    loser = second if first.status_code == 200 else first
    assert winner.json()["data"]["match_status"] == "posted"
    assert loser.status_code == 409
    assert "already has a journal" in loser.json()["detail"].lower()

    async with factory() as session:
        txn = await session.get(BankTransaction, txn_id)
        assert txn is not None
        assert txn.match_status == "posted"
        assert txn.posted_journal_batch_id is not None

        batch_count = (
            await session.execute(
                select(func.count()).select_from(JournalBatch).where(
                    JournalBatch.tenant_id == TESTING_TENANT_UUID,
                    JournalBatch.entry_kind == JournalEntryKind.BANK_CREATE,
                    JournalBatch.reversal_reason.is_(None),
                    JournalBatch.id == txn.posted_journal_batch_id,
                )
            )
        ).scalar_one()
        assert batch_count == 1


@pytest.mark.asyncio
async def test_parallel_reverse_exactly_one_wins(pg_client) -> None:
    client, factory = pg_client
    _account_id, txn_id = await _import_unmatched_out(client, amount="44.00")

    created = await client.post(
        f"/api/bank-feeds/transactions/{txn_id}/create",
        json=_CREATE_PAYLOAD,
    )
    assert created.status_code == 200, created.text
    original_batch_id = created.json()["data"]["posted_journal_batch_id"]
    assert original_batch_id is not None

    async def post_reverse():
        return await client.post(
            f"/api/bank-feeds/transactions/{txn_id}/reverse-create",
        )

    first, second = await asyncio.gather(post_reverse(), post_reverse())
    statuses = Counter([first.status_code, second.status_code])
    assert statuses[200] == 1
    assert statuses[409] == 1

    async with factory() as session:
        txn = await session.get(BankTransaction, txn_id)
        assert txn is not None
        assert txn.match_status == "unmatched"
        assert txn.posted_journal_batch_id is None

        reversal_count = (
            await session.execute(
                select(func.count()).select_from(JournalBatch).where(
                    JournalBatch.tenant_id == TESTING_TENANT_UUID,
                    JournalBatch.reversal_reason.is_not(None),
                )
            )
        ).scalar_one()
        assert reversal_count >= 1

        original = await session.get(JournalBatch, original_batch_id)
        assert original is not None
        assert original.reversed_by_batch_id is not None
