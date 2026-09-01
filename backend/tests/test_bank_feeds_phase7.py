"""Bank feeds Phase 7 — unsettled cash settlements."""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.bank_feed import (
    BankMatchEntityType,
    BankMatchMethod,
    BankTransactionMatch,
    BankTxnMatchStatus,
)
from app.models.collection import Collection, CollectionStatus
from app.models.invoice import Invoice, InvoiceStatus
from app.models.payment import Payment, PaymentStatus
from app.models.tenant import Tenant
from app.models.tenant_module import TenantModule
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


@pytest.fixture
def fixed_today(monkeypatch: pytest.MonkeyPatch) -> date:
    anchor = date(2026, 8, 31)

    async def _today(db, tenant_id):  # noqa: ANN001
        return anchor

    monkeypatch.setattr(
        "app.services.bank_feeds.unsettled_service._institution_today",
        _today,
    )
    return anchor


async def _paid_payment(
    db_session: AsyncSession,
    *,
    suffix: str,
    paid_date: datetime | None,
    amount: Decimal = Decimal("100.00"),
) -> Payment:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor=f"Vendor {suffix}",
        invoice_no=f"INV-{suffix}",
        status=InvoiceStatus.PROCESSED,
        currency="AUD",
        total=amount,
        file_hash=f"bf7-{suffix}",
    )
    db_session.add(inv)
    await db_session.flush()
    payment = Payment(
        tenant_id=TESTING_TENANT_UUID,
        invoice_id=inv.id,
        vendor=inv.vendor,
        amount=amount,
        currency="AUD",
        status=PaymentStatus.PAID,
        paid_date=paid_date,
    )
    db_session.add(payment)
    await db_session.flush()
    return payment


async def _received_collection(
    db_session: AsyncSession,
    *,
    suffix: str,
    received_date: datetime | None,
    amount: Decimal = Decimal("250.00"),
) -> Collection:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor=f"Customer {suffix}",
        invoice_no=f"SINV-{suffix}",
        status=InvoiceStatus.PROCESSED,
        currency="AUD",
        total=amount,
        file_hash=f"bf7c-{suffix}",
    )
    db_session.add(inv)
    await db_session.flush()
    collection = Collection(
        tenant_id=TESTING_TENANT_UUID,
        invoice_id=inv.id,
        customer=f"Customer {suffix}",
        amount=amount,
        currency="AUD",
        status=CollectionStatus.RECEIVED,
        received_date=received_date,
    )
    db_session.add(collection)
    await db_session.flush()
    return collection


async def _bank_account_and_txn(client: AsyncClient) -> tuple[int, int]:
    acc = await client.post(
        "/api/bank-feeds/accounts",
        json={"name": "Ops AUD", "currency": "AUD"},
    )
    assert acc.status_code == 201, acc.text
    account_id = acc.json()["data"]["id"]
    csv = (
        b"Date,Description,Amount,Direction,Balance,Reference\n"
        b"2026-08-20,Bank line,100.00,out,1000.00,REF7\n"
    )
    uploaded = await client.post(
        f"/api/bank-feeds/accounts/{account_id}/imports",
        files={"file": ("s.csv", csv, "text/csv")},
    )
    assert uploaded.status_code == 200, uploaded.text
    listed = await client.get(f"/api/bank-feeds/accounts/{account_id}/transactions")
    txn_id = listed.json()["data"]["items"][0]["id"]
    return account_id, txn_id


async def _post_bank_create(client: AsyncClient, txn_id: int) -> None:
    created = await client.post(
        f"/api/bank-feeds/transactions/{txn_id}/create",
        json={
            "party_type": "vendor",
            "create_party": {"name": "Unrelated Vendor"},
            "ledger": "Operating Expenses",
            "description": "Unrelated bank create",
            "tax_rate_percent": 0,
        },
    )
    assert created.status_code == 200, created.text
    body = created.json()["data"]
    assert body["match_status"] == "posted"
    assert body["posted_journal_batch_id"] is not None


@pytest.mark.asyncio
async def test_unsettled_paid_payment_with_bank_create_posted_still_flagged(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """Bank Create posts a journal but writes no match row — payment stays unsettled."""
    await _enable_bank_feeds(db_session)
    payment = await _paid_payment(
        db_session,
        suffix="bank-create",
        paid_date=datetime(2026, 8, 1, tzinfo=timezone.utc),
    )
    await db_session.commit()

    _, txn_id = await _bank_account_and_txn(client)
    await _post_bank_create(client, txn_id)

    matches = (
        await db_session.execute(
            select(BankTransactionMatch).where(
                BankTransactionMatch.tenant_id == TESTING_TENANT_UUID,
                BankTransactionMatch.matched_type == BankMatchEntityType.PAYMENT.value,
                BankTransactionMatch.matched_id == payment.id,
                BankTransactionMatch.unmatched_at.is_(None),
            )
        )
    ).scalars().all()
    assert matches == []

    res = await client.get("/api/bank-feeds/unsettled-settlements")
    assert res.status_code == 200, res.text
    row = next(
        (i for i in res.json()["data"]["items"] if i["entity_id"] == payment.id),
        None,
    )
    assert row is not None, "paid payment must remain unsettled after unrelated Bank Create"
    assert row["entity_type"] == "payment"
    assert float(row["allocated_bank_amount"]) == 0.0


@pytest.mark.asyncio
async def test_unsettled_null_paid_date_is_immediate_anomaly(
    client: AsyncClient,
    db_session: AsyncSession,
    fixed_today: date,
) -> None:
    """status=paid with null paid_date is flagged immediately, not silently dropped."""
    await _enable_bank_feeds(db_session)
    payment = await _paid_payment(db_session, suffix="null-date", paid_date=None)
    await db_session.commit()

    res = await client.get("/api/bank-feeds/unsettled-settlements")
    assert res.status_code == 200, res.text
    row = next(
        (i for i in res.json()["data"]["items"] if i["entity_id"] == payment.id),
        None,
    )
    assert row is not None
    assert row["entity_type"] == "payment"
    assert row["days_since_settled"] == 0
    assert row["settled_date"] == fixed_today.isoformat()


@pytest.mark.asyncio
async def test_unsettled_null_received_date_is_immediate_anomaly(
    client: AsyncClient,
    db_session: AsyncSession,
    fixed_today: date,
) -> None:
    """status=received with null received_date is flagged immediately."""
    await _enable_bank_feeds(db_session)
    collection = await _received_collection(
        db_session, suffix="null-rcv", received_date=None
    )
    await db_session.commit()

    res = await client.get("/api/bank-feeds/unsettled-settlements")
    assert res.status_code == 200, res.text
    row = next(
        (i for i in res.json()["data"]["items"] if i["entity_id"] == collection.id),
        None,
    )
    assert row is not None
    assert row["entity_type"] == "collection"
    assert row["days_since_settled"] == 0
    assert row["settled_date"] == fixed_today.isoformat()


@pytest.mark.asyncio
async def test_unsettled_module_disabled_returns_403(client: AsyncClient) -> None:
    res = await client.get("/api/bank-feeds/unsettled-settlements")
    assert res.status_code == 403
    assert "bank_feeds" in res.json()["detail"]
    count = await client.get("/api/bank-feeds/unsettled-settlements/count")
    assert count.status_code == 403


@pytest.mark.asyncio
async def test_unsettled_requires_view_privilege(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _enable_bank_feeds(db_session)
    from app.services.auth import privilege_service

    monkeypatch.setattr(
        privilege_service,
        "user_has_privilege",
        lambda ctx, action: False if action == "View" else True,
    )
    res = await client.get("/api/bank-feeds/unsettled-settlements")
    assert res.status_code == 403
    assert "View" in res.json()["detail"]


@pytest.mark.asyncio
async def test_unsettled_flags_old_paid_payment_without_match(
    client: AsyncClient,
    db_session: AsyncSession,
    fixed_today: date,
) -> None:
    await _enable_bank_feeds(db_session)
    payment = await _paid_payment(
        db_session,
        suffix="old",
        paid_date=datetime(2026, 8, 10, tzinfo=timezone.utc),
    )
    await db_session.commit()

    res = await client.get("/api/bank-feeds/unsettled-settlements")
    assert res.status_code == 200, res.text
    items = res.json()["data"]["items"]
    assert any(i["entity_type"] == "payment" and i["entity_id"] == payment.id for i in items)
    row = next(i for i in items if i["entity_id"] == payment.id)
    assert row["days_since_settled"] == (fixed_today - date(2026, 8, 10)).days
    assert row["has_suggested_bank_match"] is False
    assert float(row["allocated_bank_amount"]) == 0.0


@pytest.mark.asyncio
async def test_unsettled_within_grace_not_listed(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    await _enable_bank_feeds(db_session)
    await _paid_payment(
        db_session,
        suffix="grace",
        paid_date=datetime(2026, 8, 28, tzinfo=timezone.utc),
    )
    await db_session.commit()

    res = await client.get("/api/bank-feeds/unsettled-settlements")
    assert res.status_code == 200
    assert not any(i["entity_type"] == "payment" for i in res.json()["data"]["items"])


@pytest.mark.asyncio
async def test_unsettled_excludes_fully_matched_payment(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    await _enable_bank_feeds(db_session)
    payment = await _paid_payment(
        db_session,
        suffix="matched",
        paid_date=datetime(2026, 8, 1, tzinfo=timezone.utc),
    )
    await db_session.commit()
    _, txn_id = await _bank_account_and_txn(client)
    man = await client.post(
        f"/api/bank-feeds/transactions/{txn_id}/matches",
        json={
            "matched_type": "payment",
            "matched_id": payment.id,
            "allocated_amount": 100.0,
        },
    )
    assert man.status_code == 201, man.text

    res = await client.get("/api/bank-feeds/unsettled-settlements")
    assert res.status_code == 200
    assert not any(i["entity_id"] == payment.id for i in res.json()["data"]["items"])


@pytest.mark.asyncio
async def test_unsettled_partial_allocation_stays_flagged(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    await _enable_bank_feeds(db_session)
    payment = await _paid_payment(
        db_session,
        suffix="partial",
        paid_date=datetime(2026, 8, 1, tzinfo=timezone.utc),
        amount=Decimal("100.00"),
    )
    await db_session.commit()
    _, txn_id = await _bank_account_and_txn(client)
    man = await client.post(
        f"/api/bank-feeds/transactions/{txn_id}/matches",
        json={
            "matched_type": "payment",
            "matched_id": payment.id,
            "allocated_amount": 40.0,
        },
    )
    assert man.status_code == 201, man.text

    res = await client.get("/api/bank-feeds/unsettled-settlements")
    assert res.status_code == 200
    row = next(i for i in res.json()["data"]["items"] if i["entity_id"] == payment.id)
    assert float(row["allocated_bank_amount"]) == 40.0
    assert float(row["gross_amount"]) == 100.0


@pytest.mark.asyncio
async def test_unsettled_suggested_only_still_flagged(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    await _enable_bank_feeds(db_session)
    payment = await _paid_payment(
        db_session,
        suffix="suggested",
        paid_date=datetime(2026, 8, 1, tzinfo=timezone.utc),
    )
    await db_session.commit()
    account_id, txn_id = await _bank_account_and_txn(client)
    run = await client.post(f"/api/bank-feeds/accounts/{account_id}/match-run")
    assert run.status_code == 200, run.text
    # Force a suggested row if match-run did not write one (date/ref mismatch).
    match = BankTransactionMatch(
        tenant_id=TESTING_TENANT_UUID,
        bank_transaction_id=txn_id,
        matched_type=BankMatchEntityType.PAYMENT.value,
        matched_id=payment.id,
        allocated_amount=Decimal("100.00"),
        match_confidence=Decimal("0.7500"),
        match_method=BankMatchMethod.SUGGESTED.value,
    )
    db_session.add(match)
    await db_session.commit()

    res = await client.get("/api/bank-feeds/unsettled-settlements")
    assert res.status_code == 200
    row = next(i for i in res.json()["data"]["items"] if i["entity_id"] == payment.id)
    assert row["has_suggested_bank_match"] is True
    assert float(row["allocated_bank_amount"]) == 0.0


@pytest.mark.asyncio
async def test_unsettled_confirmed_suggestion_not_flagged(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    await _enable_bank_feeds(db_session)
    payment = await _paid_payment(
        db_session,
        suffix="confirmed",
        paid_date=datetime(2026, 8, 1, tzinfo=timezone.utc),
    )
    await db_session.commit()
    _, txn_id = await _bank_account_and_txn(client)
    man = await client.post(
        f"/api/bank-feeds/transactions/{txn_id}/matches",
        json={
            "matched_type": "payment",
            "matched_id": payment.id,
            "allocated_amount": 100.0,
        },
    )
    assert man.status_code == 201, man.text
    match_id = man.json()["data"]["id"]
    # Downgrade to suggested + matched txn to simulate confirmed suggestion state.
    match = (
        await db_session.execute(
            select(BankTransactionMatch).where(BankTransactionMatch.id == match_id)
        )
    ).scalar_one()
    match.match_method = BankMatchMethod.SUGGESTED.value
    from app.models.bank_feed import BankTransaction

    txn = await db_session.get(BankTransaction, txn_id)
    assert txn is not None
    txn.match_status = BankTxnMatchStatus.MATCHED.value
    await db_session.commit()

    res = await client.get("/api/bank-feeds/unsettled-settlements")
    assert res.status_code == 200
    assert not any(i["entity_id"] == payment.id for i in res.json()["data"]["items"])


@pytest.mark.asyncio
async def test_unsettled_collection_received(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    await _enable_bank_feeds(db_session)
    collection = await _received_collection(
        db_session,
        suffix="col",
        received_date=datetime(2026, 8, 1, tzinfo=timezone.utc),
    )
    await db_session.commit()

    res = await client.get("/api/bank-feeds/unsettled-settlements")
    assert res.status_code == 200
    assert any(
        i["entity_type"] == "collection" and i["entity_id"] == collection.id
        for i in res.json()["data"]["items"]
    )


@pytest.mark.asyncio
async def test_unsettled_respects_tenant_grace_days_setting(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    await _enable_bank_feeds(db_session)
    tenant = await db_session.get(Tenant, TESTING_TENANT_UUID)
    assert tenant is not None
    tenant.settings_json = {
        **(tenant.settings_json or {}),
        "bank_cash_verification_grace_days": 3,
    }
    await _paid_payment(
        db_session,
        suffix="short-grace",
        paid_date=datetime(2026, 8, 25, tzinfo=timezone.utc),
    )
    await db_session.commit()

    res = await client.get("/api/bank-feeds/unsettled-settlements")
    assert res.status_code == 200
    assert res.json()["data"]["grace_days"] == 3
    assert any(i["entity_type"] == "payment" for i in res.json()["data"]["items"])


@pytest.mark.asyncio
async def test_unsettled_lookback_cap_excludes_old_settlements(
    client: AsyncClient,
    db_session: AsyncSession,
    fixed_today: date,
) -> None:
    await _enable_bank_feeds(db_session)
    old_date = fixed_today.replace(year=fixed_today.year - 1, month=1, day=15)
    await _paid_payment(
        db_session,
        suffix="ancient",
        paid_date=datetime(
            old_date.year, old_date.month, old_date.day, tzinfo=timezone.utc
        ),
    )
    await db_session.commit()

    res = await client.get("/api/bank-feeds/unsettled-settlements")
    assert res.status_code == 200
    assert res.json()["data"]["lookback_months"] == 12
    assert not any(i["party_name"] == "Vendor ancient" for i in res.json()["data"]["items"])


@pytest.mark.asyncio
async def test_unsettled_count_endpoint(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    await _enable_bank_feeds(db_session)
    await _paid_payment(
        db_session,
        suffix="count-a",
        paid_date=datetime(2026, 8, 1, tzinfo=timezone.utc),
    )
    await _paid_payment(
        db_session,
        suffix="count-b",
        paid_date=datetime(2026, 8, 2, tzinfo=timezone.utc),
    )
    await db_session.commit()

    res = await client.get("/api/bank-feeds/unsettled-settlements/count")
    assert res.status_code == 200
    assert res.json()["data"]["count"] >= 2
