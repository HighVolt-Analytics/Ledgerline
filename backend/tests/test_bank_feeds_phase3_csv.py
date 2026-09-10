"""Phase 3 — CSV header alias fallback + encoding sniff."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.services.bank_feeds.csv_parser import parse_canonical_bank_csv
from app.services.bank_feeds.statement_parse_profile import GENERIC_V1


BANK_SHAPED_CSV = """\
Transaction Date,Narrative,Debit Amount,Credit Amount,Running Balance,Cheque No
01 Aug 2026,Fuel Station,25.04,,1000.00,CHQ-1
02 Aug 2026,Salary Credit,,500.00,1500.00,
03 Aug 2026,Pharmacy,10.50,,1489.50,CHQ-2
"""


def test_alias_headers_import_via_generic_csv_aliases() -> None:
    """Real-shaped bank CSV (non-canonical headers) imports via generic_v1 aliases."""
    result = parse_canonical_bank_csv(BANK_SHAPED_CSV.encode("utf-8"), profile=GENERIC_V1)
    assert result.errors == [], [e.message for e in result.errors]
    assert len(result.rows) == 3
    assert result.parse_meta.get("csv_column_strategy") == "aliases"
    assert result.rows[0].txn_date == date(2026, 8, 1)
    assert result.rows[0].direction == "debit"
    assert result.rows[0].amount == Decimal("25.04")
    assert result.rows[0].description == "Fuel Station"
    assert result.rows[1].direction == "credit"
    assert result.rows[1].amount == Decimal("500.00")
    assert result.rows[0].reference == "CHQ-1"


def test_cp1252_encoding_sniff_succeeds() -> None:
    """cp1252 CSV that is not valid UTF-8 still decodes via encoding_fallbacks."""
    # 0xA3 is £ in cp1252; not valid as a UTF-8 continuation alone in this sequence.
    line = "Date,Description,Amount,Direction,Balance,Reference\r\n"
    line += "2026-05-01,Caf\xe9 payment,10.00,out,100.00,REF-1\r\n"
    raw = line.encode("latin-1")  # same bytes as cp1252 for these chars
    # Ensure raw is not valid UTF-8 (Café with 0xE9 alone).
    with pytest.raises(UnicodeDecodeError):
        raw.decode("utf-8")

    result = parse_canonical_bank_csv(raw, profile=GENERIC_V1)
    assert result.errors == [], [e.message for e in result.errors]
    assert len(result.rows) == 1
    assert result.parse_meta.get("csv_encoding") == "cp1252"
    assert "é" in result.rows[0].description or "Caf" in result.rows[0].description
    assert result.rows[0].amount == Decimal("10.00")
    assert result.rows[0].direction == "debit"


def test_missing_required_field_after_aliases_fails_loudly() -> None:
    """Even with aliases, a CSV lacking amount/flow columns must hard-fail clearly."""
    body = (
        "Transaction Date,Narrative,Memo Only\n"
        "01 Aug 2026,Fuel Station,no amounts here\n"
    ).encode("utf-8")
    result = parse_canonical_bank_csv(body, profile=GENERIC_V1)
    assert result.rows == []
    assert result.errors
    msg = result.errors[0].message.lower()
    assert "missing required fields after alias resolution" in msg
    assert "amount" in msg or "debit" in msg or "credit" in msg
    assert "found headers" in msg
    assert "narrative" in msg or "transaction date" in msg


def test_canonical_csv_regression_identical() -> None:
    """Exact canonical template path unchanged (strategy=canonical)."""
    canonical = (
        b"Date,Description,Amount,Direction,Balance,Reference\n"
        b"2026-05-01,AWS Invoice INV-100,110.00,out,5000.00,REF-1\n"
        b"2026-05-02,Customer payment ACME,250.50,in,5250.50,REF-2\n"
    )
    result = parse_canonical_bank_csv(canonical)
    assert result.errors == []
    assert len(result.rows) == 2
    assert result.parse_meta.get("csv_column_strategy") == "canonical"
    assert result.rows[0].direction == "debit"
    assert result.rows[1].direction == "credit"
    assert result.rows[0].amount == Decimal("110.00")
    assert result.rows[0].txn_date == date(2026, 5, 1)
