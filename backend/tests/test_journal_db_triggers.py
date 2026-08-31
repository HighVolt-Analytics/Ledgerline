"""Postgres-only: DB balance constraint + immutability triggers (migration 099/100)."""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings


def _pg_url() -> str:
    get_settings.cache_clear()
    url = get_settings().database_url
    if "postgresql" not in url or "127.0.0.1" not in url and "localhost" not in url:
        pytest.skip("local PostgreSQL DATABASE_URL required (refuse remote)")
    return url


@pytest.fixture
async def pg_session():
    url = _pg_url()
    engine = create_async_engine(url, echo=False)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
        await session.rollback()
    await engine.dispose()


async def _seed(session: AsyncSession) -> tuple[str, int]:
    tid = str(uuid4())
    await session.execute(
        text(
            """
            INSERT INTO tenants (id, name, slug, currency)
            VALUES (CAST(:tid AS uuid), 'Trigger Tenant', :slug, 'AUD')
            """
        ),
        {"tid": tid, "slug": f"trig-{tid[:8]}"},
    )
    await session.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tid},
    )
    invoice_id = (
        await session.execute(
            text(
                """
                INSERT INTO invoices (tenant_id, status, currency, file_hash)
                VALUES (CAST(:tid AS uuid), 'processed', 'AUD', :fh)
                RETURNING id
                """
            ),
            {"tid": tid, "fh": f"trig-{uuid4().hex[:20]}"},
        )
    ).scalar_one()
    await session.flush()
    return tid, int(invoice_id)


@pytest.mark.asyncio
async def test_unbalanced_batch_rejected_on_commit(pg_session: AsyncSession) -> None:
    tid, invoice_id = await _seed(pg_session)
    batch_id = (
        await pg_session.execute(
            text(
                """
                INSERT INTO journal_batches (tenant_id, invoice_id, entry_kind, status)
                VALUES (CAST(:tid AS uuid), :inv, 'invoice_accrual', 'posted')
                RETURNING id
                """
            ),
            {"tid": tid, "inv": invoice_id},
        )
    ).scalar_one()
    await pg_session.execute(
        text(
            """
            INSERT INTO journal_entries
              (batch_id, tenant_id, invoice_id, date, account_code, account_name,
               debit, credit, entry_type, entry_kind)
            VALUES
              (:b, CAST(:tid AS uuid), :inv, CURRENT_DATE, '6100', 'Expense',
               100, 0, 'debit', 'invoice_accrual')
            """
        ),
        {"b": batch_id, "tid": tid, "inv": invoice_id},
    )
    with pytest.raises((IntegrityError, DBAPIError)) as exc:
        await pg_session.commit()
    msg = str(exc.value).lower()
    assert "do not equal" in msg or "23514" in msg
    await pg_session.rollback()


@pytest.mark.asyncio
async def test_journal_entry_update_and_delete_blocked(pg_session: AsyncSession) -> None:
    tid, invoice_id = await _seed(pg_session)
    batch_id = (
        await pg_session.execute(
            text(
                """
                INSERT INTO journal_batches (tenant_id, invoice_id, entry_kind, status)
                VALUES (CAST(:tid AS uuid), :inv, 'invoice_accrual', 'posted')
                RETURNING id
                """
            ),
            {"tid": tid, "inv": invoice_id},
        )
    ).scalar_one()
    await pg_session.execute(
        text(
            """
            INSERT INTO journal_entries
              (batch_id, tenant_id, invoice_id, date, account_code, account_name,
               debit, credit, entry_type, entry_kind)
            VALUES
              (:b, CAST(:tid AS uuid), :inv, CURRENT_DATE, '6100', 'Expense',
               50, 0, 'debit', 'invoice_accrual'),
              (:b, CAST(:tid AS uuid), :inv, CURRENT_DATE, '2000', 'AP',
               0, 50, 'credit', 'invoice_accrual')
            """
        ),
        {"b": batch_id, "tid": tid, "inv": invoice_id},
    )
    await pg_session.commit()

    await pg_session.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tid},
    )
    entry_id = (
        await pg_session.execute(
            text("SELECT id FROM journal_entries WHERE batch_id = :b LIMIT 1"),
            {"b": batch_id},
        )
    ).scalar_one()

    with pytest.raises((IntegrityError, DBAPIError)) as upd:
        await pg_session.execute(
            text("UPDATE journal_entries SET debit = 99 WHERE id = :id"),
            {"id": entry_id},
        )
        await pg_session.commit()
    assert "append-only" in str(upd.value).lower() or "23001" in str(upd.value)
    await pg_session.rollback()

    await pg_session.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tid},
    )
    with pytest.raises((IntegrityError, DBAPIError)) as dele:
        await pg_session.execute(
            text("DELETE FROM journal_entries WHERE id = :id"),
            {"id": entry_id},
        )
        await pg_session.commit()
    assert "append-only" in str(dele.value).lower() or "23001" in str(dele.value)
    await pg_session.rollback()
