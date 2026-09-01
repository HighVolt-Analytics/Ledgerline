"""Bank statement PDF / shared parse_common tests."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import fitz
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tenant_module import TenantModule
from app.services.bank_feeds.parse_common import (
    BALANCE_CONTINUITY_MSG,
    DIRECTION_UNCERTAIN_IMPORT_MSG,
    DIRECTION_UNCERTAIN_IMPORT_MSG,
    DIRECTION_UNCERTAIN_ROW_MSG,
    ParsedBankCsvRow,
    finalize_parsed_rows,
    parse_money_token,
    parse_statement_text_block,
    parse_statement_text_line,
    refine_row_directions,
    validate_balance_continuity,
)
from app.services.bank_feeds.pdf_parser import parse_bank_statement_pdf, _parse_table_rows
from app.tenant_ids import TESTING_TENANT_UUID

SAMPLE_LINES = """
01 Aug 2026 Fuel Station REF2R6080100 25.04 4,224.96
02 Aug 2026 Refund - Online Retailer REF26080201 601.90 4,826.86
03 Aug 2026 Pharmacy REF26080302 566.09 4,260.77
04 Aug 2026 Streaming Service Subscription REF26080403 456.21 3,804.56
05 Aug 2026 Streaming Service Subscription REF26080504 146.23 3,658.33
08 Aug 2026 Electric Utility Payment REF26080805 67.54 3,590.79
09 Aug 2026 Interest Payment REF26080906 1,387.64 4,978.43
14 Aug 2026 Rent Payment REF26081407 302.95 4,675.48
19 Aug 2026 Fuel Station REF26081910 225.00 4,450.48
21 Aug 2026 Transfer In - J. Rivera REF26082111 1,734.79 6,185.27
22 Aug 2026 Transfer Out - Savings Sweep REF26082212 157.45 6,027.82
23 Aug 2026 Interest Payment REF26082313 1,079.49 7,107.31
24 Aug 2026 Streaming Service Subscription REF26082414 245.66 6,861.65
26 Aug 2026 Interest Payment REF26082615 1,588.73 8,450.38
29 Aug 2026 Electric Utility Payment REF26082916 399.06 8,051.32
30 Aug 2026 Transfer In - J. Rivera REF26083017 484.98 8,536.30
"""


def _make_pdf(lines: list[str], *, pages: int | None = None) -> bytes:
    doc = fitz.open()
    if pages and pages > 1:
        per_page = max(1, len(lines) // pages)
        chunks = [lines[i : i + per_page] for i in range(0, len(lines), per_page)]
    else:
        chunks = [lines]
    for page_lines in chunks:
        page = doc.new_page()
        y = 72
        for line in page_lines:
            page.insert_text((72, y), line, fontsize=11)
            y += 16
    return doc.tobytes()


async def _enable_bank_feeds(db_session: AsyncSession) -> None:
    db_session.add(
        TenantModule(
            tenant_id=TESTING_TENANT_UUID,
            module_key="bank_feeds",
            is_active=True,
        )
    )
    await db_session.commit()


def test_parse_sample_statement_all_rows() -> None:
    result = parse_statement_text_block(SAMPLE_LINES)
    assert result.extracted_count == 16
    assert len(result.rows) == 16
    assert all(err.message != DIRECTION_UNCERTAIN_ROW_MSG for err in result.errors)
    assert str(result.rows[0].txn_date) == "2026-08-01"
    assert result.rows[9].direction == "credit"


def test_unrecognized_debit_credit_headers_fail_safely(monkeypatch: pytest.MonkeyPatch) -> None:
    table = [
        ["Date", "Details", "Outflow", "Inflow", "Balance"],
        ["01 Aug 2026", "Fuel", "25.04", "", "4,224.96"],
    ]
    from app.services.bank_feeds.pdf_parser import (
        _table_has_unrecognized_flow_headers,
    )

    assert _table_has_unrecognized_flow_headers(table)

    def _fake_extract(_path):
        return [table], ""

    monkeypatch.setattr(
        "app.services.bank_feeds.pdf_parser._extract_pdf_tables_and_text",
        _fake_extract,
    )
    monkeypatch.setattr(
        "app.services.bank_feeds.pdf_parser._extract_text_with_ocr_fallback",
        lambda _path, text: (text, "pdfplumber"),
    )
    result = parse_bank_statement_pdf(b"%PDF-1.4 test")
    assert result.rows == []
    assert result.errors
    assert DIRECTION_UNCERTAIN_IMPORT_MSG in result.errors[0].message


def test_recognized_withdrawal_deposit_headers_succeed() -> None:
    table = [
        ["Date", "Narration", "Withdrawals", "Deposits", "Balance"],
        ["01 Aug 2026", "Fuel", "25.04", "", "4,224.96"],
        ["02 Aug 2026", "Refund", "", "601.90", "4,826.86"],
    ]
    parsed = _parse_table_rows(table)
    assert len(parsed.rows) == 2
    assert parsed.rows[0].direction == "debit"
    assert parsed.rows[1].direction == "credit"


def test_balance_continuity_flags_misparsed_row() -> None:
    rows = [
        ParsedBankCsvRow(1, date(2026, 8, 1), "A", Decimal("10"), "debit", Decimal("90"), None),
        ParsedBankCsvRow(2, date(2026, 8, 2), "B", Decimal("5"), "debit", Decimal("95"), None),
    ]
    errors = validate_balance_continuity(rows)
    assert len(errors) == 1
    assert BALANCE_CONTINUITY_MSG in errors[0].message


def test_finalize_rejects_balance_continuity_failures() -> None:
    rows = [
        ParsedBankCsvRow(1, date(2026, 8, 1), "A", Decimal("10"), "debit", Decimal("100"), None),
        ParsedBankCsvRow(2, date(2026, 8, 2), "B", Decimal("5"), "debit", Decimal("90"), None),
    ]
    accepted, errors = finalize_parsed_rows(rows)
    assert len(accepted) == 1
    assert any(BALANCE_CONTINUITY_MSG in err.message for err in errors)


def test_skipped_date_like_line_surfaces_error() -> None:
    result = parse_statement_text_block(
        "01 Aug 2026 Fuel Station 25.04 4,224.96\n"
        "02 Aug 2026\n"
        "03 Aug 2026 Pharmacy 566.09 4,260.77\n"
    )
    assert result.skipped_line_count >= 1
    assert any("Could not parse transaction line" in err.message for err in result.errors)


def test_numeric_formats_currency_comma_parentheses() -> None:
    amount, direction = parse_money_token("($1,234.56)")
    assert amount == Decimal("1234.56")
    assert direction == "debit"
    row = parse_statement_text_line(
        "01 Aug 2026 AUD Supplier ($1,234.56) 500.00", row_number=1
    )
    assert row is not None
    assert row.amount == Decimal("1234.56")
    assert row.balance == Decimal("500.00")
    assert row.direction == "debit"


def test_multi_page_pdf_import() -> None:
    lines = [line.strip() for line in SAMPLE_LINES.strip().splitlines()]
    pdf_bytes = _make_pdf(lines, pages=2)
    result = parse_bank_statement_pdf(pdf_bytes)
    assert result.extracted_count == 16
    assert len(result.rows) == 16


def test_unparseable_pdf_fails_clearly_not_partial() -> None:
    pdf_bytes = _make_pdf(["This is not a bank statement", "No dates or amounts here"])
    result = parse_bank_statement_pdf(pdf_bytes)
    assert result.rows == []
    assert result.extracted_count == 0
    assert result.errors
    assert result.errors[0].row_number == 0


def test_text_line_without_direction_or_balance_fails_row() -> None:
    row = parse_statement_text_line("01 Aug 2026 Fuel only 25.04", row_number=1)
    assert row is not None
    accepted, errors = finalize_parsed_rows([row])
    assert accepted == []
    assert any(DIRECTION_UNCERTAIN_ROW_MSG in err.message for err in errors)


@pytest.mark.asyncio
async def test_pdf_then_csv_dedupes_same_transaction(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _enable_bank_feeds(db_session)
    create = await client.post(
        "/api/bank-feeds/accounts",
        json={"name": "Dedup PDF CSV", "currency": "AUD"},
    )
    account_id = create.json()["data"]["id"]

    line = "2026-05-01 AWS Invoice INV-100 110.00 out 5,000.00 REF-1"
    pdf_bytes = _make_pdf([line])
    pdf_upload = await client.post(
        f"/api/bank-feeds/accounts/{account_id}/imports",
        files={"file": ("stmt.pdf", pdf_bytes, "application/pdf")},
    )
    assert pdf_upload.status_code == 200, pdf_upload.text
    assert pdf_upload.json()["data"]["accepted_count"] == 1
    assert pdf_upload.json()["data"]["extracted_count"] == 1

    csv_body = (
        "Date,Description,Amount,Direction,Balance,Reference\n"
        "2026-05-01,AWS Invoice INV-100,110.00,out,5000.00,REF-1\n"
    ).encode()
    csv_upload = await client.post(
        f"/api/bank-feeds/accounts/{account_id}/imports",
        files={"file": ("stmt.csv", csv_body, "text/csv")},
    )
    assert csv_upload.status_code == 200
    body = csv_upload.json()["data"]
    assert body["accepted_count"] == 0
    assert body["duplicate_count"] == 1

    listed = await client.get(f"/api/bank-feeds/accounts/{account_id}/transactions")
    assert len(listed.json()["data"]["items"]) == 1


REALISTIC_NARRATION_LINES = """
2026-09-02 Salary Credit NEFT Orion Systems 1,92,000.00 in 5,92,000.00
2026-09-04 UPI Tasty Bites Cafe 640.00 out 5,91,360.00
2026-09-06 NEFT DR Anand Traders INV771 (9,800.00) 5,81,560.00
2026-09-09 NEFT CR Continental Freight INV3009 22,000.00 in 6,03,560.00
2026-09-11 Bank Charges SMS Alert 150.00 out 6,03,410.00
2026-09-13 POS Spencers Retail Hyd 2,140.00 out 6,01,270.00
2026-09-16 NEFT DR Priya Textiles INV455 6,300.00 out 5,92,000.00
2026-09-19 Interest Paid Sep26 410.00 in 5,95,380.00
2026-09-21 NEFT CR Continental Freight INV3010 18,500.00 in 6,13,880.00
2026-09-23 Google Workspace IN 4,200.00 out 6,09,680.00
"""

REALISTIC_NARRATION_EXPECTED = [
    ("credit", Decimal("192000.00"), Decimal("592000.00"), "Salary Credit NEFT Orion Systems"),
    ("debit", Decimal("640.00"), Decimal("591360.00"), "UPI Tasty Bites Cafe"),
    ("debit", Decimal("9800.00"), Decimal("581560.00"), "NEFT DR Anand Traders INV771"),
    ("credit", Decimal("22000.00"), Decimal("603560.00"), "NEFT CR Continental Freight INV3009"),
    ("debit", Decimal("150.00"), Decimal("603410.00"), "Bank Charges SMS Alert"),
    ("debit", Decimal("2140.00"), Decimal("601270.00"), "POS Spencers Retail Hyd"),
    ("debit", Decimal("6300.00"), Decimal("592000.00"), "NEFT DR Priya Textiles INV455"),
    ("credit", Decimal("410.00"), Decimal("595380.00"), "Interest Paid Sep26"),
    ("credit", Decimal("18500.00"), Decimal("613880.00"), "NEFT CR Continental Freight INV3010"),
    ("debit", Decimal("4200.00"), Decimal("609680.00"), "Google Workspace IN"),
]


def test_text_fallback_realistic_multiword_narration() -> None:
    """Regression: Indian-format amounts + multi-word UPI/NEFT narration + in/out tokens."""
    lines = [line.strip() for line in REALISTIC_NARRATION_LINES.strip().splitlines()]
    assert len(lines) == 10

    for index, (line, (direction, amount, balance, description)) in enumerate(
        zip(lines, REALISTIC_NARRATION_EXPECTED), start=1
    ):
        row = parse_statement_text_line(line, row_number=index)
        assert row is not None, line
        assert row.direction == direction, line
        assert row.amount == amount, line
        assert row.balance == balance, line
        assert row.description == description, line

    result = parse_statement_text_block(REALISTIC_NARRATION_LINES)
    assert result.candidate_line_count == 10
    assert not any(
        err.message == DIRECTION_UNCERTAIN_ROW_MSG for err in result.errors
    ), [err.message for err in result.errors if err.message == DIRECTION_UNCERTAIN_ROW_MSG]
    # Rows 7–8 balances don't chain in this fixture; direction must still parse for all 10.
    assert result.extracted_count == 8
    assert sum(BALANCE_CONTINUITY_MSG in err.message for err in result.errors) == 2


def test_balance_continuity_uses_immediate_prior_row_after_rejections() -> None:
    """One bad balance row must not cause later valid rows to compare against a distant prior."""
    rows = [
        ParsedBankCsvRow(6, date(2026, 9, 12), "POS", Decimal("2140"), "debit", Decimal("551270"), None),
        ParsedBankCsvRow(7, date(2026, 9, 15), "NEFT DR", Decimal("6300"), "debit", Decimal("542000"), None),
        ParsedBankCsvRow(8, date(2026, 9, 18), "INTT", Decimal("410"), "credit", Decimal("545380"), None),
        ParsedBankCsvRow(9, date(2026, 9, 20), "NEFT CR", Decimal("18500"), "credit", Decimal("563880"), None),
    ]
    errors = validate_balance_continuity(rows)
    flagged = {err.row_number for err in errors}
    assert flagged == {7, 8}


def test_balance_continuity_rejected_rows_do_not_skip_chain_in_finalize() -> None:
    """finalize must run continuity once on the full row list (table-format rows 7-9 shape)."""
    rows = [
        ParsedBankCsvRow(6, date(2026, 9, 12), "POS", Decimal("2140"), "debit", Decimal("551270"), None),
        ParsedBankCsvRow(7, date(2026, 9, 15), "NEFT DR", Decimal("6300"), "debit", Decimal("542000"), None),
        ParsedBankCsvRow(8, date(2026, 9, 18), "INTT", Decimal("410"), "credit", Decimal("545380"), None),
        ParsedBankCsvRow(9, date(2026, 9, 20), "NEFT CR", Decimal("18500"), "credit", Decimal("563880"), None),
    ]
    accepted, errors = finalize_parsed_rows(rows)
    assert [row.row_number for row in accepted] == [6, 9]
    flagged = {err.row_number for err in errors if BALANCE_CONTINUITY_MSG in err.message}
    assert flagged == {7, 8}


def test_table_format_pdf_with_rs_prefix_amounts() -> None:
    """Real table PDF: Withdrawals/Deposits columns with Rs. prefixed amounts."""
    from pathlib import Path

    fixture = (
        Path(__file__).resolve().parents[2]
        / "test-assets"
        / "bank_statement_pdf_table_format.pdf"
    )
    assert fixture.is_file(), f"missing fixture: {fixture}"
    result = parse_bank_statement_pdf(fixture.read_bytes())
    assert result.parse_meta.get("extraction_method") == "pdfplumber"
    assert not any(
        err.message == DIRECTION_UNCERTAIN_ROW_MSG for err in result.errors
    ), [e.message for e in result.errors]
    assert not any(
        err.message == DIRECTION_UNCERTAIN_IMPORT_MSG for err in result.errors
    )
    assert result.extracted_count == 8
    assert not any(err.row_number == 9 for err in result.errors)
    continuity_rows = {
        err.row_number
        for err in result.errors
        if BALANCE_CONTINUITY_MSG in err.message
    }
    assert continuity_rows == {7, 8}
    assert result.rows[0].direction == "credit"
    assert result.rows[0].amount == Decimal("192000.00")
    assert result.rows[1].direction == "debit"
    assert result.rows[1].amount == Decimal("640.00")


def test_parse_money_token_rs_prefix() -> None:
    amount, direction = parse_money_token("Rs. 1,92,000.00")
    assert amount == Decimal("192000.00")
    assert direction is None


def test_refine_row_directions_uses_running_balance() -> None:
    rows = [
        ParsedBankCsvRow(1, date(2026, 8, 1), "Payment", Decimal("10"), "", Decimal("90"), None),
        ParsedBankCsvRow(2, date(2026, 8, 2), "Payment", Decimal("5"), "", Decimal("95"), None),
    ]
    refined = refine_row_directions(rows)
    assert refined[1].direction == "credit"
