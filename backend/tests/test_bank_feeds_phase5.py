"""Bank feeds Phase 5 — narration categorize after import + match precedence."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.bank_feed import BankTransaction
from app.models.invoice import Invoice, InvoiceStatus
from app.models.payment import Payment, PaymentStatus
from app.models.tenant_module import TenantModule
from app.services.rule_book.rule_book_config_io import (
    clear_posting_config_cache,
    load_rule_book_config_dict,
)
from app.services.rule_book.rule_book_config_repository import upsert_config
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


async def _put_atm_rule(db_session: AsyncSession) -> None:
    raw = await load_rule_book_config_dict(db_session, TESTING_TENANT_UUID)
    raw["bank_narration_rules"] = [
        {
            "id": "bnr-atm",
            "name": "ATM cash",
            "enabled": True,
            "priority": 10,
            "match_on": {"description_contains": "ATM"},
            "post_to": {"ledger": "Petty Cash", "sub_ledger": ""},
            "matched_count": 0,
        }
    ]
    await upsert_config(db_session, TESTING_TENANT_UUID, raw)
    await db_session.commit()
    clear_posting_config_cache()


CSV_TWO = b"""Date,Description,Amount,Direction,Balance,Reference
2026-05-01,ATM WITHDRAWAL #12,50.00,out,5000.00,R1
2026-05-02,Customer payment ACME,250.50,in,5250.50,R2
"""


@pytest.mark.asyncio
async def test_import_auto_categorizes_and_reports_count(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _enable_bank_feeds(db_session)
    await _put_atm_rule(db_session)

    create = await client.post(
        "/api/bank-feeds/accounts",
        json={"name": "Ops AUD", "currency": "AUD"},
    )
    assert create.status_code == 201, create.text
    account_id = create.json()["data"]["id"]

    upload = await client.post(
        f"/api/bank-feeds/accounts/{account_id}/imports",
        files={"file": ("stmt.csv", CSV_TWO, "text/csv")},
    )
    assert upload.status_code == 200, upload.text
    imp = upload.json()["data"]
    assert imp["accepted_count"] == 2
    assert imp["categorized_count"] == 1

    listed = await client.get(
        f"/api/bank-feeds/accounts/{account_id}/transactions?match_status=unmatched"
    )
    items = listed.json()["data"]["items"]
    by_desc = {row["description"]: row for row in items}
    atm = by_desc["ATM WITHDRAWAL #12"]
    other = by_desc["Customer payment ACME"]
    assert atm["category_coa"] == "Petty Cash"
    assert atm["category_source"] == "rule"
    assert atm["category_rule_name"] == "ATM cash"
    assert other["category_coa"] is None


@pytest.mark.asyncio
async def test_match_clears_category_manual_override_and_categorize_run(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _enable_bank_feeds(db_session)
    await _put_atm_rule(db_session)

    create = await client.post(
        "/api/bank-feeds/accounts",
        json={"name": "Ops AUD", "currency": "AUD"},
    )
    account_id = create.json()["data"]["id"]
    upload = await client.post(
        f"/api/bank-feeds/accounts/{account_id}/imports",
        files={"file": ("stmt.csv", CSV_TWO, "text/csv")},
    )
    assert upload.json()["data"]["categorized_count"] == 1

    items = (
        await client.get(
            f"/api/bank-feeds/accounts/{account_id}/transactions?match_status=unmatched"
        )
    ).json()["data"]["items"]
    atm = next(row for row in items if "ATM" in row["description"])
    other = next(row for row in items if "ACME" in row["description"])

    patched = await client.patch(
        f"/api/bank-feeds/transactions/{other['id']}/category",
        json={"category_coa": "Suspense Account"},
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["data"]["category_coa"] == "Suspense Account"
    assert patched.json()["data"]["category_source"] == "manual"

    rerun = await client.post(f"/api/bank-feeds/accounts/{account_id}/categorize-run")
    assert rerun.status_code == 200, rerun.text
    # Manual override must not be overwritten; ATM already categorized by rule.
    assert rerun.json()["data"]["categorized_count"] == 0
    still = (await client.get(f"/api/bank-feeds/transactions/{other['id']}")).json()["data"]
    assert still["category_coa"] == "Suspense Account"
    assert still["category_source"] == "manual"

    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Cash Vendor",
        invoice_no="ATM-1",
        status=InvoiceStatus.PROCESSED,
        currency="AUD",
        total=Decimal("50.00"),
        file_hash="bf-cat-match-1",
    )
    db_session.add(inv)
    await db_session.flush()
    pay = Payment(
        tenant_id=TESTING_TENANT_UUID,
        invoice_id=inv.id,
        vendor="Cash Vendor",
        amount=Decimal("50.00"),
        currency="AUD",
        status=PaymentStatus.PAID,
        paid_date=datetime(2026, 5, 1, tzinfo=timezone.utc),
    )
    db_session.add(pay)
    await db_session.commit()

    linked = await client.post(
        f"/api/bank-feeds/transactions/{atm['id']}/matches",
        json={"matched_type": "payment", "matched_id": pay.id},
    )
    assert linked.status_code == 201, linked.text
    after = (await client.get(f"/api/bank-feeds/transactions/{atm['id']}")).json()["data"]
    assert after["match_status"] == "matched"
    assert after["category_coa"] is None
    assert after["category_source"] is None

    db_session.expire_all()
    persisted = await db_session.get(BankTransaction, atm["id"])
    assert persisted is not None
    assert persisted.category_coa is None
    flags = persisted.review_flags if isinstance(persisted.review_flags, dict) else {}
    superseded = flags.get("superseded_categorization") or {}
    assert superseded.get("category_coa") == "Petty Cash"
    assert "categorization" not in flags
