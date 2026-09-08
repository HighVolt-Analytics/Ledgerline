"""Pending bank account enqueue, promote, and account-number auto-match."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.bank_feed import BankTransaction, PendingBankAccount
from app.models.tenant_module import TenantModule
from app.services.bank_feeds.pending_account_service import (
    account_numbers_match,
    extract_account_numbers_from_text,
    normalize_account_number_digits,
)
from app.tenant_ids import TESTING_TENANT_UUID

CANONICAL_CSV = b"""Date,Description,Amount,Direction,Balance,Reference
2026-05-01,AWS Invoice INV-100,110.00,out,5000.00,REF-1
2026-05-02,Customer payment ACME,250.50,in,5250.50,REF-2
"""

STATEMENT_WITH_ACCOUNT = b"""Account Name: Business Operating
Account Number: 123456789
Currency: AUD
Date,Description,Amount,Direction,Balance,Reference
2026-06-01,Supplier payment,75.00,out,4000.00,JUN-1
2026-06-02,Customer deposit,300.00,in,4300.00,JUN-2
"""

NEXT_MONTH_SAME_ACCOUNT = b"""Account No. 123-456-789
Currency: AUD
Date,Description,Amount,Direction,Balance,Reference
2026-07-01,Payroll,1200.00,out,3100.00,JUL-1
2026-07-02,Refund,50.00,in,3150.00,JUL-2
"""


async def _enable_bank_feeds(db_session: AsyncSession) -> None:
    db_session.add(
        TenantModule(
            tenant_id=TESTING_TENANT_UUID,
            module_key="bank_feeds",
            is_active=True,
        )
    )
    await db_session.commit()


def test_normalize_and_match_account_numbers() -> None:
    assert normalize_account_number_digits("123-456-789") == "123456789"
    assert account_numbers_match("123 456 789", "123456789")
    assert not account_numbers_match("1234", "1234")  # too short
    assert not account_numbers_match("111111111", "222222222")


def test_extract_account_number_from_statement_text() -> None:
    text = STATEMENT_WITH_ACCOUNT.decode("utf-8")
    found = extract_account_numbers_from_text(text)
    assert "123456789" in found
    found2 = extract_account_numbers_from_text(NEXT_MONTH_SAME_ACCOUNT.decode("utf-8"))
    assert "123456789" in found2


def test_extract_hints_prefills_verify_fields() -> None:
    from app.models.bank_feed import BankFeedSource
    from app.services.bank_feeds.pending_account_service import _extract_hints

    hints = _extract_hints(
        STATEMENT_WITH_ACCOUNT,
        source=BankFeedSource.CSV,
        filename="mystery_bank.pdf",
    )
    assert hints["detected_account_number"] == "123456789"
    assert hints["detected_currency"] == "AUD"
    assert hints["detected_name"] == "Business Operating"
    assert hints["name_from_document"] is True


@pytest.mark.asyncio
async def test_pending_import_promote_imports_transactions(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _enable_bank_feeds(db_session)

    queued = await client.post(
        "/api/bank-feeds/pending-imports",
        files={"file": ("stmt.csv", CANONICAL_CSV, "text/csv")},
    )
    assert queued.status_code == 201, queued.text
    data = queued.json()["data"]
    assert data["disposition"] == "pending"
    pending = data["pending"]
    assert pending["status"] == "pending"
    assert pending["extracted_count"] == 2
    pending_id = pending["id"]

    listed = await client.get("/api/bank-feeds/pending-accounts")
    assert listed.status_code == 200
    assert any(row["id"] == pending_id for row in listed.json()["data"])

    # Dedupe same file
    again = await client.post(
        "/api/bank-feeds/pending-imports",
        files={"file": ("stmt.csv", CANONICAL_CSV, "text/csv")},
    )
    assert again.status_code == 201
    assert again.json()["data"]["disposition"] == "pending"
    assert again.json()["data"]["pending"]["id"] == pending_id

    promoted = await client.post(
        f"/api/bank-feeds/pending-accounts/{pending_id}/promote",
        json={
            "name": "Ops Pending",
            "account_number": "99887766",
            "currency": "AUD",
            "coa_account_name": "Bank Account",
        },
    )
    assert promoted.status_code == 200, promoted.text
    body = promoted.json()["data"]
    account = body["account"]
    assert account["name"] == "Ops Pending"
    assert account["account_number"] == "99887766"
    assert account["account_mask"] == "****7766"
    assert body["import_result"]["accepted_count"] == 2

    empty = await client.get("/api/bank-feeds/pending-accounts")
    assert empty.json()["data"] == []

    txns = await client.get(f"/api/bank-feeds/accounts/{account['id']}/transactions")
    assert txns.status_code == 200
    assert len(txns.json()["data"]["items"]) == 2

    row = (
        await db_session.execute(
            select(PendingBankAccount).where(PendingBankAccount.id == pending_id)
        )
    ).scalar_one()
    assert row.status == "promoted"
    assert row.promoted_bank_account_id == account["id"]


@pytest.mark.asyncio
async def test_auto_import_when_account_number_matches_registered_bank(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _enable_bank_feeds(db_session)

    create = await client.post(
        "/api/bank-feeds/accounts",
        json={
            "name": "Meine Account",
            "currency": "AUD",
            "account_number": "123456789",
            "coa_account_name": "Bank Account",
        },
    )
    assert create.status_code == 201, create.text
    account_id = create.json()["data"]["id"]

    # First month — with account number in file, no account selected → auto-import
    first = await client.post(
        "/api/bank-feeds/pending-imports",
        files={"file": ("may.csv", STATEMENT_WITH_ACCOUNT, "text/csv")},
    )
    assert first.status_code == 201, first.text
    body = first.json()["data"]
    assert body["disposition"] == "auto_imported"
    assert body["account"]["id"] == account_id
    assert body["import_result"]["accepted_count"] == 2
    assert body["pending"] is None

    pending_list = await client.get("/api/bank-feeds/pending-accounts")
    assert pending_list.json()["data"] == []

    # Next month — same account number (with dashes) → auto-import again
    second = await client.post(
        "/api/bank-feeds/pending-imports",
        files={"file": ("june.csv", NEXT_MONTH_SAME_ACCOUNT, "text/csv")},
    )
    assert second.status_code == 201, second.text
    body2 = second.json()["data"]
    assert body2["disposition"] == "auto_imported"
    assert body2["account"]["id"] == account_id
    assert body2["import_result"]["accepted_count"] == 2

    txns = await client.get(f"/api/bank-feeds/accounts/{account_id}/transactions")
    assert len(txns.json()["data"]["items"]) == 4


@pytest.mark.asyncio
async def test_currency_mismatch_does_not_auto_import(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _enable_bank_feeds(db_session)
    create = await client.post(
        "/api/bank-feeds/accounts",
        json={
            "name": "USD Ops",
            "currency": "USD",
            "account_number": "123456789",
            "coa_account_name": "Bank Account",
        },
    )
    assert create.status_code == 201, create.text

    queued = await client.post(
        "/api/bank-feeds/pending-imports",
        files={"file": ("aud.csv", STATEMENT_WITH_ACCOUNT, "text/csv")},
    )
    assert queued.status_code == 201, queued.text
    data = queued.json()["data"]
    assert data["disposition"] == "pending"
    assert data["pending"] is not None


@pytest.mark.asyncio
async def test_pending_dismiss(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _enable_bank_feeds(db_session)
    queued = await client.post(
        "/api/bank-feeds/pending-imports",
        files={"file": ("stmt2.csv", CANONICAL_CSV, "text/csv")},
    )
    pending_id = queued.json()["data"]["pending"]["id"]
    dismiss = await client.post(f"/api/bank-feeds/pending-accounts/{pending_id}/dismiss")
    assert dismiss.status_code == 204
    listed = await client.get("/api/bank-feeds/pending-accounts")
    assert listed.json()["data"] == []
    txn_count = (await db_session.execute(select(BankTransaction))).scalars().all()
    assert txn_count == []


@pytest.mark.asyncio
async def test_create_account_requires_number_and_ledger(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _enable_bank_feeds(db_session)
    res = await client.post(
        "/api/bank-feeds/accounts",
        json={"name": "No Number", "currency": "AUD"},
    )
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_pending_import_returns_extracted_verify_fields(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _enable_bank_feeds(db_session)
    queued = await client.post(
        "/api/bank-feeds/pending-imports",
        files={"file": ("ops.csv", STATEMENT_WITH_ACCOUNT, "text/csv")},
    )
    assert queued.status_code == 201, queued.text
    pending = queued.json()["data"]["pending"]
    assert pending["detected_name"] == "Business Operating"
    assert pending["detected_account_number"] == "123456789"
    assert pending["detected_currency"] == "AUD"
    assert pending["extracted_count"] == 2


@pytest.mark.asyncio
async def test_update_and_archive_bank_account(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _enable_bank_feeds(db_session)
    created = await client.post(
        "/api/bank-feeds/accounts",
        json={
            "name": "Ops",
            "currency": "AUD",
            "account_number": "99887766",
            "coa_account_name": "Bank Account",
        },
    )
    assert created.status_code == 201, created.text
    account_id = created.json()["data"]["id"]

    updated = await client.patch(
        f"/api/bank-feeds/accounts/{account_id}",
        json={
            "name": "Ops renamed",
            "currency": "AUD",
            "account_number": "1122334455",
            "coa_account_name": "Bank Account",
        },
    )
    assert updated.status_code == 200, updated.text
    body = updated.json()["data"]
    assert body["name"] == "Ops renamed"
    assert body["account_number"] == "1122334455"
    assert body["account_mask"] == "****4455"

    archived = await client.delete(f"/api/bank-feeds/accounts/{account_id}")
    assert archived.status_code == 200, archived.text
    assert archived.json()["data"]["status"] == "archived"

    active = await client.get("/api/bank-feeds/accounts")
    assert active.status_code == 200
    assert all(row["id"] != account_id for row in active.json()["data"])

    with_archived = await client.get("/api/bank-feeds/accounts?include_archived=true")
    assert with_archived.status_code == 200
    assert any(row["id"] == account_id for row in with_archived.json()["data"])
