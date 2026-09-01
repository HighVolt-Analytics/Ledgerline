"""Phase 3 close-out: privilege gating, manual match, unmatch-rematch remaining."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog
from app.models.invoice import Invoice, InvoiceStatus
from app.models.payment import Payment, PaymentStatus
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


@pytest.mark.asyncio
async def test_mutate_requires_post_privilege(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _enable_bank_feeds(db_session)

    from app.services.auth import privilege_service

    monkeypatch.setattr(
        privilege_service,
        "user_has_privilege",
        lambda ctx, action: False if action == "Post" else True,
    )

    listed = await client.get("/api/bank-feeds/accounts")
    assert listed.status_code == 200

    create = await client.post(
        "/api/bank-feeds/accounts",
        json={"name": "No Post", "currency": "AUD"},
    )
    assert create.status_code == 403
    assert "Post" in create.json()["detail"]

    # Confirm path also gated (404 vs 403 — privilege checked before lookup)
    confirm = await client.post("/api/bank-feeds/matches/1/confirm")
    assert confirm.status_code == 403
    unmatch = await client.post("/api/bank-feeds/matches/1/unmatch")
    assert unmatch.status_code == 403
    exclude = await client.post("/api/bank-feeds/transactions/1/exclude")
    assert exclude.status_code == 403


@pytest.mark.asyncio
async def test_manual_match_audit_and_unmatch_rematch_remaining(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _enable_bank_feeds(db_session)

    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Manual Co",
        invoice_no="INV-MANUAL",
        status=InvoiceStatus.PROCESSED,
        currency="AUD",
        total=Decimal("100.00"),
        file_hash="bf-manual-1",
    )
    db_session.add(inv)
    await db_session.flush()
    payment = Payment(
        tenant_id=TESTING_TENANT_UUID,
        invoice_id=inv.id,
        vendor="Manual Co",
        amount=Decimal("100.00"),
        currency="AUD",
        status=PaymentStatus.PAID,
        paid_date=datetime(2026, 10, 1, tzinfo=timezone.utc),
    )
    db_session.add(payment)
    await db_session.commit()

    acc = await client.post(
        "/api/bank-feeds/accounts",
        json={"name": "Ops", "currency": "AUD"},
    )
    account_id = acc.json()["data"]["id"]

    # Import only FEE1 first — date/ref far from payment so match-run writes nothing.
    csv1 = (
        b"Date,Description,Amount,Direction,Balance,Reference\n"
        b"2026-01-15,Unrelated bank fee xyz,100.00,out,500.00,FEE1\n"
    )
    await client.post(
        f"/api/bank-feeds/accounts/{account_id}/imports",
        files={"file": ("m1.csv", csv1, "text/csv")},
    )
    listed = await client.get(
        f"/api/bank-feeds/accounts/{account_id}/transactions"
    )
    fee1 = listed.json()["data"]["items"][0]

    run = await client.post(f"/api/bank-feeds/accounts/{account_id}/match-run")
    assert run.status_code == 200
    by_txn = {r["transaction_id"]: r for r in run.json()["data"]["items"]}
    assert by_txn[fee1["id"]]["matches_written"] == 0

    # Manual match on a non-suggested candidate
    man = await client.post(
        f"/api/bank-feeds/transactions/{fee1['id']}/matches",
        json={
            "matched_type": "payment",
            "matched_id": payment.id,
            "allocated_amount": 100.0,
        },
    )
    assert man.status_code == 201, man.text
    assert man.json()["data"]["match_method"] == "manual"
    match_id = man.json()["data"]["id"]

    await db_session.commit()
    audits = (
        await db_session.execute(
            select(AuditLog).where(
                AuditLog.tenant_id == TESTING_TENANT_UUID,
                AuditLog.event == "bank_txn_matched",
            )
        )
    ).scalars().all()
    manual_audits = [
        a
        for a in audits
        if (a.detail or {}).get("match_method") == "manual"
        and (a.detail or {}).get("bank_transaction_id") == fee1["id"]
    ]
    assert manual_audits, "expected audit with match_method=manual"

    un = await client.post(
        f"/api/bank-feeds/matches/{match_id}/unmatch",
        json={"reason": "wrong line"},
    )
    assert un.status_code == 200

    # Second bank line — rematch should see full remaining after unmatch
    csv2 = (
        b"Date,Description,Amount,Direction,Balance,Reference\n"
        b"2026-10-02,Second line for rematch,100.00,out,400.00,FEE2\n"
    )
    await client.post(
        f"/api/bank-feeds/accounts/{account_id}/imports",
        files={"file": ("m2.csv", csv2, "text/csv")},
    )
    listed2 = await client.get(
        f"/api/bank-feeds/accounts/{account_id}/transactions"
    )
    fee2 = next(
        i for i in listed2.json()["data"]["items"] if i["reference"] == "FEE2"
    )

    man2 = await client.post(
        f"/api/bank-feeds/transactions/{fee2['id']}/matches",
        json={
            "matched_type": "payment",
            "matched_id": payment.id,
            "allocated_amount": 100.0,
        },
    )
    assert man2.status_code == 201, man2.text
    assert man2.json()["data"]["allocated_amount"] == 100.0

    # Remaining consumed again — second allocation must fail
    man3 = await client.post(
        f"/api/bank-feeds/transactions/{fee1['id']}/matches",
        json={
            "matched_type": "payment",
            "matched_id": payment.id,
            "allocated_amount": 1.0,
        },
    )
    assert man3.status_code == 400
    assert "remaining" in man3.json()["detail"].lower()


@pytest.mark.asyncio
async def test_match_targets_filtered_by_bank_account_currency(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _enable_bank_feeds(db_session)

    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="FX Vendor",
        invoice_no="INV-FX",
        status=InvoiceStatus.PROCESSED,
        currency="USD",
        total=Decimal("100.00"),
        file_hash="bf-fx-1",
    )
    db_session.add(inv)
    await db_session.flush()
    payment = Payment(
        tenant_id=TESTING_TENANT_UUID,
        invoice_id=inv.id,
        vendor="FX Vendor",
        amount=Decimal("100.00"),
        currency="USD",
        status=PaymentStatus.PAID,
        paid_date=datetime(2026, 10, 1, tzinfo=timezone.utc),
    )
    db_session.add(payment)
    await db_session.commit()

    acc = await client.post(
        "/api/bank-feeds/accounts",
        json={"name": "AUD Ops", "currency": "AUD"},
    )
    assert acc.status_code == 201, acc.text
    account_id = acc.json()["data"]["id"]

    unscoped = await client.get("/api/bank-feeds/match-targets?matched_type=payment")
    assert unscoped.status_code == 200
    assert any(row["id"] == payment.id for row in unscoped.json()["data"])

    scoped = await client.get(
        f"/api/bank-feeds/match-targets?matched_type=payment&bank_account_id={account_id}"
    )
    assert scoped.status_code == 200
    assert not any(row["id"] == payment.id for row in scoped.json()["data"])
