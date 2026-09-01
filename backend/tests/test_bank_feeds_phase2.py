"""Bank feeds Phase 2 — CSV import + API tests."""

from __future__ import annotations

from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog
from app.models.bank_feed import BankTransaction
from app.models.tenant_module import TenantModule
from app.services.bank_feeds.csv_parser import parse_canonical_bank_csv
from app.services.bank_feeds.parse_common import parse_statement_text_block
from app.services.bank_feeds.fingerprint import compute_fingerprint, normalize_description
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


CANONICAL_CSV = b"""Date,Description,Amount,Direction,Balance,Reference
2026-05-01,AWS Invoice INV-100,110.00,out,5000.00,REF-1
2026-05-02,Customer payment ACME,250.50,in,5250.50,REF-2
"""


@pytest.mark.asyncio
async def test_parse_canonical_csv_ok() -> None:
    result = parse_canonical_bank_csv(CANONICAL_CSV)
    assert result.errors == []
    assert len(result.rows) == 2
    assert result.rows[0].direction == "debit"
    assert result.rows[1].direction == "credit"
    assert result.rows[0].amount == Decimal("110.00")


@pytest.mark.asyncio
async def test_fingerprint_stable_on_normalized_description() -> None:
    from datetime import date

    a = normalize_description("AWS  Invoice  INV-100")
    b = normalize_description("aws invoice inv-100")
    assert a == b
    assert a == "aws invoice inv100"
    fp = compute_fingerprint(
        txn_date=date(2026, 5, 1),
        amount=Decimal("110.00"),
        direction="debit",
        description_normalized=a,
    )
    assert len(fp) == 64


@pytest.mark.asyncio
async def test_normalize_strips_punctuation_for_invoice_refs() -> None:
    """Bank narrations usually drop separators; invoice refs often keep them."""
    assert normalize_description("INV-1042") == "inv1042"
    assert normalize_description("INV1042") == "inv1042"
    assert normalize_description("INV_1042") == "inv1042"
    assert normalize_description("INV.1042") == "inv1042"
    assert normalize_description("INV/1042") == "inv1042"
    hay = normalize_description("NEFT DR TO SHARMA ENTERPRISES INV1042")
    assert normalize_description("INV-1042") in hay


@pytest.mark.asyncio
async def test_fingerprint_distinct_for_payment_rail_prefix_only() -> None:
    """Same date/amount/direction but different rail prefix must not collide."""
    from datetime import date

    txn_date = date(2026, 5, 1)
    amount = Decimal("500.00")
    direction = "debit"
    pairs = [
        ("UPI TO ACME SUPPLIES INV100", "NEFT TO ACME SUPPLIES INV100"),
        ("UPI PAYMENT 5000", "NEFT PAYMENT 5000"),
        ("IMPS REF 12345 VENDOR A", "NEFT REF 12345 VENDOR A"),
    ]
    for desc_a, desc_b in pairs:
        norm_a = normalize_description(desc_a)
        norm_b = normalize_description(desc_b)
        assert norm_a != norm_b, (desc_a, desc_b, norm_a, norm_b)
        fp_a = compute_fingerprint(
            txn_date=txn_date,
            amount=amount,
            direction=direction,
            description_normalized=norm_a,
        )
        fp_b = compute_fingerprint(
            txn_date=txn_date,
            amount=amount,
            direction=direction,
            description_normalized=norm_b,
        )
        assert fp_a != fp_b, (desc_a, desc_b)


@pytest.mark.asyncio
async def test_create_account_rejects_unsupported_currency(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _enable_bank_feeds(db_session)
    res = await client.post(
        "/api/bank-feeds/accounts",
        json={"name": "Bad Currency", "currency": "IND"},
    )
    assert res.status_code == 422, res.text
    detail = res.json()["detail"]
    assert any("IND" in str(item.get("msg", "")) for item in detail)


@pytest.mark.asyncio
async def test_bank_feeds_module_disabled_returns_403(client: AsyncClient) -> None:
    res = await client.get("/api/bank-feeds/accounts")
    assert res.status_code == 403
    assert "bank_feeds" in res.json()["detail"]


@pytest.mark.asyncio
async def test_create_account_import_list_and_idempotent_reupload(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _enable_bank_feeds(db_session)

    create = await client.post(
        "/api/bank-feeds/accounts",
        json={"name": "Operating AUD", "currency": "aud", "account_mask": "****1234"},
    )
    assert create.status_code == 201, create.text
    account = create.json()["data"]
    assert account["currency"] == "AUD"
    assert account["coa_account_name"]
    account_id = account["id"]

    upload = await client.post(
        f"/api/bank-feeds/accounts/{account_id}/imports",
        files={"file": ("stmt.csv", CANONICAL_CSV, "text/csv")},
    )
    assert upload.status_code == 200, upload.text
    imp = upload.json()["data"]
    assert imp["accepted_count"] == 2
    assert imp["duplicate_count"] == 0
    assert imp["error_count"] == 0
    assert imp["reused_existing"] is False
    import_id = imp["id"]

    listed = await client.get(f"/api/bank-feeds/accounts/{account_id}/transactions")
    assert listed.status_code == 200
    items = listed.json()["data"]["items"]
    assert len(items) == 2
    assert {i["money_flow"] for i in items} == {"in", "out"}
    assert "fingerprint" not in items[0]
    assert "direction" not in items[0]

    detail = await client.get(f"/api/bank-feeds/transactions/{items[0]['id']}")
    assert detail.status_code == 200
    assert detail.json()["data"]["matches"] == []

    got_import = await client.get(f"/api/bank-feeds/imports/{import_id}")
    assert got_import.status_code == 200
    assert got_import.json()["data"]["accepted_count"] == 2

    reupload = await client.post(
        f"/api/bank-feeds/accounts/{account_id}/imports",
        files={"file": ("stmt.csv", CANONICAL_CSV, "text/csv")},
    )
    assert reupload.status_code == 200
    again = reupload.json()["data"]
    assert again["reused_existing"] is True
    assert again["id"] == import_id

    txns = (
        await db_session.execute(
            select(BankTransaction).where(BankTransaction.bank_account_id == account_id)
        )
    ).scalars().all()
    assert len(txns) == 2

    audits = (
        await db_session.execute(
            select(AuditLog).where(AuditLog.tenant_id == TESTING_TENANT_UUID)
        )
    ).scalars().all()
    events = {a.event for a in audits}
    assert "bank_account_created" in events
    assert "bank_feed_import_started" in events
    assert "bank_feed_import_completed" in events
    assert "bank_txn_accepted" in events
    assert "bank_feed_import_idempotent_reuse" in events


@pytest.mark.asyncio
async def test_import_rejects_duplicate_row_by_fingerprint(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _enable_bank_feeds(db_session)
    create = await client.post(
        "/api/bank-feeds/accounts",
        json={"name": "Ops", "currency": "AUD"},
    )
    account_id = create.json()["data"]["id"]

    first = b"""Date,Description,Amount,Direction,Balance,Reference
2026-06-01,Office rent,900.00,out,100.00,R1
"""
    second = b"""Date,Description,Amount,Direction,Balance,Reference
2026-06-01,Office rent,900.00,out,100.00,R2
2026-06-02,New fee,10.00,out,90.00,R3
"""
    await client.post(
        f"/api/bank-feeds/accounts/{account_id}/imports",
        files={"file": ("a.csv", first, "text/csv")},
    )
    res = await client.post(
        f"/api/bank-feeds/accounts/{account_id}/imports",
        files={"file": ("b.csv", second, "text/csv")},
    )
    data = res.json()["data"]
    assert data["accepted_count"] == 1
    assert data["duplicate_count"] == 1

    listed = await client.get(f"/api/bank-feeds/accounts/{account_id}/transactions")
    assert len(listed.json()["data"]["items"]) == 2


@pytest.mark.asyncio
async def test_import_allows_shared_reference_different_amount_date(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Split payments may share the same Reference (invoice no.) — not a unique txn id."""
    await _enable_bank_feeds(db_session)
    create = await client.post(
        "/api/bank-feeds/accounts",
        json={"name": "Ops Split", "currency": "AUD"},
    )
    account_id = create.json()["data"]["id"]

    csv = b"""Date,Description,Amount,Direction,Balance,Reference
2026-08-18,Payment to supplier ACME,15000.00,out,85000.00,INV-2003
2026-08-20,Payment to supplier ACME,10000.00,out,75000.00,INV-2003
"""
    res = await client.post(
        f"/api/bank-feeds/accounts/{account_id}/imports",
        files={"file": ("split.csv", csv, "text/csv")},
    )
    assert res.status_code == 200, res.text
    data = res.json()["data"]
    assert data["accepted_count"] == 2
    assert data["duplicate_count"] == 0

    listed = await client.get(f"/api/bank-feeds/accounts/{account_id}/transactions")
    items = listed.json()["data"]["items"]
    assert len(items) == 2
    assert {i["reference"] for i in items} == {"INV-2003"}
    assert {i["amount"] for i in items} == {15000.0, 10000.0}
    assert {i["txn_date"] for i in items} == {"2026-08-18", "2026-08-20"}

    txns = (
        await db_session.execute(
            select(BankTransaction).where(BankTransaction.bank_account_id == account_id)
        )
    ).scalars().all()
    assert all(t.external_id is None for t in txns)


def test_parse_pdf_text_lines_debit_credit() -> None:
    line_text = """
    2026-05-01 AWS Invoice INV-100 110.00 out 5000.00
    2026-05-02 Customer payment ACME 250.50 in 5250.50
    """
    result = parse_statement_text_block(line_text)
    assert result.errors == []
    assert len(result.rows) == 2
    assert result.rows[0].direction == "debit"
    assert result.rows[1].direction == "credit"
    assert result.rows[0].amount == Decimal("110.00")


def test_parse_pdf_text_lines_month_name_date_and_balance() -> None:
    """Matches sample_bank_statement.pdf layout (DD Mon YYYY + amount + balance)."""
    line_text = """
    19 Aug 2026 Fuel Station REF26081910 225.00 4,450.48
    21 Aug 2026 Transfer In - J. Rivera REF26082111 1,734.79 6,185.27
    22 Aug 2026 Transfer Out - Savings Sweep REF26082212 157.45 6,027.82
    23 Aug 2026 Interest Payment REF26082313 1,079.49 7,107.31
    """
    result = parse_statement_text_block(line_text)
    assert result.errors == []
    assert len(result.rows) == 4
    assert str(result.rows[0].txn_date) == "2026-08-19"
    assert result.rows[0].direction == "debit"
    assert result.rows[1].direction == "credit"
    assert result.rows[2].direction == "debit"
    assert result.rows[3].direction == "credit"
    assert result.rows[0].balance == Decimal("4450.48")


def _make_statement_pdf(lines: list[str]) -> bytes:
    import fitz

    doc = fitz.open()
    page = doc.new_page()
    y = 72
    for line in lines:
        page.insert_text((72, y), line, fontsize=11)
        y += 16
    return doc.tobytes()


@pytest.mark.asyncio
async def test_import_pdf_statement_via_api(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _enable_bank_feeds(db_session)
    create = await client.post(
        "/api/bank-feeds/accounts",
        json={"name": "PDF Ops", "currency": "AUD"},
    )
    account_id = create.json()["data"]["id"]

    pdf_bytes = _make_statement_pdf(
        [
            "Date Description Amount Direction Balance Reference",
            "2026-05-01 AWS Invoice INV-100 110.00 out 5000.00 REF-1",
            "2026-05-02 Customer payment ACME 250.50 in 5250.50 REF-2",
        ]
    )
    from app.services.bank_feeds.pdf_parser import parse_bank_statement_pdf

    parsed = parse_bank_statement_pdf(pdf_bytes)
    assert parsed.errors == [], parsed.errors
    assert len(parsed.rows) == 2

    upload = await client.post(
        f"/api/bank-feeds/accounts/{account_id}/imports",
        files={"file": ("stmt.pdf", pdf_bytes, "application/pdf")},
    )
    assert upload.status_code == 200, upload.text
    imp = upload.json()["data"]
    assert imp["accepted_count"] == 2
    assert imp["extracted_count"] == 2
    assert imp["source"] == "pdf"


@pytest.mark.asyncio
async def test_failed_pdf_import_can_be_retried_same_file(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Same file hash must re-parse after a failed import (not idempotent reuse)."""
    from app.services.bank_feeds import import_service

    await _enable_bank_feeds(db_session)
    create = await client.post(
        "/api/bank-feeds/accounts",
        json={"name": "Retry PDF", "currency": "AUD"},
    )
    account_id = create.json()["data"]["id"]
    pdf_bytes = _make_statement_pdf(
        [
            "01 Aug 2026 Fuel Station REF001 25.04 4,224.96",
            "02 Aug 2026 Refund REF002 601.90 4,826.86",
        ]
    )

    def _fail_parse(_content: bytes):
        from app.services.bank_feeds.parse_common import CsvParseError, CsvParseResult

        return CsvParseResult(
            rows=[],
            errors=[CsvParseError(0, "forced failure for retry test")],
        )

    monkeypatch.setattr(import_service, "parse_bank_statement_pdf", _fail_parse)
    first = await client.post(
        f"/api/bank-feeds/accounts/{account_id}/imports",
        files={"file": ("sample_bank_statement.pdf", pdf_bytes, "application/pdf")},
    )
    assert first.status_code == 200
    assert first.json()["data"]["status"] == "failed"

    monkeypatch.undo()
    second = await client.post(
        f"/api/bank-feeds/accounts/{account_id}/imports",
        files={"file": ("sample_bank_statement.pdf", pdf_bytes, "application/pdf")},
    )
    assert second.status_code == 200, second.text
    body = second.json()["data"]
    assert body["reused_existing"] is False
    assert body["accepted_count"] == 2
    assert body["extracted_count"] == 2
    assert body["status"] == "completed"

