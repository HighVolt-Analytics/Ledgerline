"""Bank feeds Phase 3 — match engine tests."""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.collection import Collection, CollectionStatus
from app.models.invoice import Invoice, InvoiceStatus
from app.models.payment import Payment, PaymentStatus
from app.models.tenant_module import TenantModule
from app.services.bank_feeds.fingerprint import normalize_party_name
from app.services.bank_feeds.match_service import (
    combine_confidence,
    score_amount,
    score_date,
    score_reference,
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


def test_normalize_party_name_strips_legal_suffixes() -> None:
    assert normalize_party_name("Acme Pty Ltd") == "acme"
    assert normalize_party_name("Foo Inc.") == "foo"
    # Under 3 chars after normalize → empty-ish short token
    assert len(normalize_party_name("AB Ltd")) < 3 or normalize_party_name("AB Ltd") == "ab"


def test_score_reference_short_party_name_stays_zero() -> None:
    s, hit = score_reference(
        haystack_raw="payment to xy for goods",
        invoice_no=None,
        payment_intent=None,
        entity_token="payment-1",
        party_name="Xy",  # 2 chars after normalize
    )
    assert s == 0.0
    assert hit is None


def test_combine_and_bands() -> None:
    assert score_amount(Decimal("10.00"), Decimal("10.00")) == 1.0
    assert score_date(0) == 1.0
    conf = combine_confidence(1.0, 1.0, 1.0)
    assert conf == Decimal("1.0000")
    # amount+date only (no ref): 0.50+0.30 = 0.80
    assert combine_confidence(1.0, 1.0, 0.0) == Decimal("0.8000")
    assert combine_confidence(1.0, 0.85, 1.0) >= Decimal("0.9500")


@pytest.mark.asyncio
async def test_auto_match_payment_exact(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _enable_bank_feeds(db_session)

    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Acme Pty Ltd",
        invoice_no="INV-900",
        status=InvoiceStatus.PROCESSED,
        currency="AUD",
        total=Decimal("110.00"),
        file_hash="bf-match-1",
    )
    db_session.add(inv)
    await db_session.flush()
    payment = Payment(
        tenant_id=TESTING_TENANT_UUID,
        invoice_id=inv.id,
        vendor="Acme Pty Ltd",
        amount=Decimal("110.00"),
        currency="AUD",
        status=PaymentStatus.PAID,
        paid_date=datetime(2026, 5, 1, tzinfo=timezone.utc),
    )
    db_session.add(payment)
    await db_session.commit()

    acc = await client.post(
        "/api/bank-feeds/accounts",
        json={"name": "Ops", "currency": "AUD"},
    )
    account_id = acc.json()["data"]["id"]
    csv = b"""Date,Description,Amount,Direction,Balance,Reference
2026-05-01,Payment INV-900 Acme,110.00,out,1000.00,X1
"""
    await client.post(
        f"/api/bank-feeds/accounts/{account_id}/imports",
        files={"file": ("a.csv", csv, "text/csv")},
    )
    run = await client.post(f"/api/bank-feeds/accounts/{account_id}/match-run")
    assert run.status_code == 200, run.text
    items = run.json()["data"]["items"]
    assert len(items) == 1
    assert items[0]["auto_matched"] is True
    assert items[0]["status"] == "matched"

    listed = await client.get(f"/api/bank-feeds/accounts/{account_id}/transactions")
    txn = listed.json()["data"]["items"][0]
    detail = await client.get(f"/api/bank-feeds/transactions/{txn['id']}")
    matches = detail.json()["data"]["matches"]
    assert len(matches) == 1
    assert matches[0]["match_method"] == "auto"
    assert matches[0]["matched_type"] == "payment"
    assert matches[0]["matched_id"] == payment.id


@pytest.mark.asyncio
async def test_tie_break_demotes_to_suggested(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _enable_bank_feeds(db_session)

    for i, no in enumerate(("INV-A", "INV-B"), start=1):
        inv = Invoice(
            tenant_id=TESTING_TENANT_UUID,
            vendor="Same Vendor Ltd",
            invoice_no=no,
            status=InvoiceStatus.PROCESSED,
            currency="AUD",
            total=Decimal("50.00"),
            file_hash=f"bf-tie-{i}",
        )
        db_session.add(inv)
        await db_session.flush()
        db_session.add(
            Payment(
                tenant_id=TESTING_TENANT_UUID,
                invoice_id=inv.id,
                vendor="Same Vendor Ltd",
                amount=Decimal("50.00"),
                currency="AUD",
                status=PaymentStatus.PAID,
                paid_date=datetime(2026, 6, 1, tzinfo=timezone.utc),
            )
        )
    await db_session.commit()

    acc = await client.post(
        "/api/bank-feeds/accounts",
        json={"name": "Ops", "currency": "AUD"},
    )
    account_id = acc.json()["data"]["id"]
    # Narration hits neither invoice uniquely; amount+date exact for both
    csv = b"""Date,Description,Amount,Direction,Balance,Reference
2026-06-01,INV-A INV-B Same Vendor payment,50.00,out,900.00,
"""
    await client.post(
        f"/api/bank-feeds/accounts/{account_id}/imports",
        files={"file": ("t.csv", csv, "text/csv")},
    )
    run = await client.post(f"/api/bank-feeds/accounts/{account_id}/match-run")
    item = run.json()["data"]["items"][0]
    assert item["auto_matched"] is False
    assert item["tie_demoted"] is True
    assert item["status"] == "suggested"
    assert item["matches_written"] == 2


@pytest.mark.asyncio
async def test_collection_fx_hard_gate(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _enable_bank_feeds(db_session)
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Customer USD",
        invoice_no="AR-1",
        status=InvoiceStatus.PROCESSED,
        currency="USD",
        total=Decimal("100.00"),
        file_hash="bf-col-fx",
    )
    db_session.add(inv)
    await db_session.flush()
    db_session.add(
        Collection(
            tenant_id=TESTING_TENANT_UUID,
            invoice_id=inv.id,
            customer="Customer USD",
            amount=Decimal("100.00"),
            currency="USD",
            status=CollectionStatus.RECEIVED,
            received_date=datetime(2026, 7, 1, tzinfo=timezone.utc),
        )
    )
    await db_session.commit()

    acc = await client.post(
        "/api/bank-feeds/accounts",
        json={"name": "AUD Bank", "currency": "AUD"},
    )
    account_id = acc.json()["data"]["id"]
    csv = b"""Date,Description,Amount,Direction,Balance,Reference
2026-07-01,AR-1 Customer USD,100.00,in,1100.00,
"""
    await client.post(
        f"/api/bank-feeds/accounts/{account_id}/imports",
        files={"file": ("c.csv", csv, "text/csv")},
    )
    run = await client.post(f"/api/bank-feeds/accounts/{account_id}/match-run")
    item = run.json()["data"]["items"][0]
    assert item["matches_written"] == 0
    assert item["status"] == "unmatched"


@pytest.mark.asyncio
async def test_remaining_amount_after_partial_manual(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _enable_bank_feeds(db_session)
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Split Co",
        invoice_no="INV-SPLIT",
        status=InvoiceStatus.PROCESSED,
        currency="AUD",
        total=Decimal("100.00"),
        file_hash="bf-split",
    )
    db_session.add(inv)
    await db_session.flush()
    payment = Payment(
        tenant_id=TESTING_TENANT_UUID,
        invoice_id=inv.id,
        vendor="Split Co",
        amount=Decimal("100.00"),
        currency="AUD",
        status=PaymentStatus.PAID,
        paid_date=datetime(2026, 8, 1, tzinfo=timezone.utc),
    )
    db_session.add(payment)
    await db_session.commit()

    acc = await client.post(
        "/api/bank-feeds/accounts",
        json={"name": "Ops", "currency": "AUD"},
    )
    account_id = acc.json()["data"]["id"]
    csv = b"""Date,Description,Amount,Direction,Balance,Reference
2026-08-01,INV-SPLIT part1,60.00,out,940.00,P1
2026-08-01,INV-SPLIT part2,40.00,out,900.00,P2
"""
    await client.post(
        f"/api/bank-feeds/accounts/{account_id}/imports",
        files={"file": ("s.csv", csv, "text/csv")},
    )
    listed = await client.get(f"/api/bank-feeds/accounts/{account_id}/transactions")
    items = listed.json()["data"]["items"]
    # Manual partial on first line
    first = next(i for i in items if i["amount"] == 60.0)
    man = await client.post(
        f"/api/bank-feeds/transactions/{first['id']}/matches",
        json={
            "matched_type": "payment",
            "matched_id": payment.id,
            "allocated_amount": 60.0,
        },
    )
    assert man.status_code == 201, man.text

    # Match-run should auto the 40 against remaining 40
    run = await client.post(f"/api/bank-feeds/accounts/{account_id}/match-run")
    assert run.status_code == 200
    by_id = {r["transaction_id"]: r for r in run.json()["data"]["items"]}
    second = next(i for i in items if i["amount"] == 40.0)
    assert by_id[second["id"]]["auto_matched"] is True


@pytest.mark.asyncio
async def test_confirm_unmatch_exclude(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _enable_bank_feeds(db_session)
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Solo Vendor",
        invoice_no="INV-SOLO",
        status=InvoiceStatus.PROCESSED,
        currency="AUD",
        total=Decimal("25.00"),
        file_hash="bf-confirm",
    )
    db_session.add(inv)
    await db_session.flush()
    payment = Payment(
        tenant_id=TESTING_TENANT_UUID,
        invoice_id=inv.id,
        vendor="Solo Vendor",
        amount=Decimal("25.00"),
        currency="AUD",
        status=PaymentStatus.SCHEDULED,
        scheduled_date=date(2026, 9, 1),
    )
    db_session.add(payment)
    await db_session.commit()

    acc = await client.post(
        "/api/bank-feeds/accounts",
        json={"name": "Ops", "currency": "AUD"},
    )
    account_id = acc.json()["data"]["id"]
    # Date off by 3 days → suggested band (not auto)
    csv = b"""Date,Description,Amount,Direction,Balance,Reference
2026-09-04,INV-SOLO Solo Vendor,25.00,out,100.00,
"""
    await client.post(
        f"/api/bank-feeds/accounts/{account_id}/imports",
        files={"file": ("u.csv", csv, "text/csv")},
    )
    run = await client.post(f"/api/bank-feeds/accounts/{account_id}/match-run")
    item = run.json()["data"]["items"][0]
    assert item["status"] == "suggested"
    listed = await client.get(f"/api/bank-feeds/accounts/{account_id}/transactions")
    txn_id = listed.json()["data"]["items"][0]["id"]
    detail = await client.get(f"/api/bank-feeds/transactions/{txn_id}")
    match_id = detail.json()["data"]["matches"][0]["id"]

    conf = await client.post(f"/api/bank-feeds/matches/{match_id}/confirm")
    assert conf.status_code == 200
    assert (
        await client.get(f"/api/bank-feeds/transactions/{txn_id}")
    ).json()["data"]["match_status"] == "matched"

    un = await client.post(
        f"/api/bank-feeds/matches/{match_id}/unmatch",
        json={"reason": "wrong payment"},
    )
    assert un.status_code == 200
    assert (
        await client.get(f"/api/bank-feeds/transactions/{txn_id}")
    ).json()["data"]["match_status"] == "unmatched"

    ex = await client.post(
        f"/api/bank-feeds/transactions/{txn_id}/exclude",
        json={"reason": "bank fee"},
    )
    assert ex.status_code == 200
    assert ex.json()["data"]["match_status"] == "excluded"
