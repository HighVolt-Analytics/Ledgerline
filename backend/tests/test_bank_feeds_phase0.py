"""Phase 0 bank-statement parse fixes: direction overwrite, confidence, date order."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.services.bank_feeds.parse_common import (
    BALANCE_CONTINUITY_MSG,
    DIRECTION_CONFIDENCE_HIGH,
    DIRECTION_CONFIDENCE_LOW,
    DIRECTION_CONFIDENCE_MEDIUM,
    ParsedBankCsvRow,
    finalize_parsed_rows,
    infer_document_date_order,
    parse_statement_date,
    parse_statement_text_block,
    refine_row_directions,
)


def test_refine_does_not_overwrite_explicit_debit_with_balance_delta() -> None:
    """0.1: explicit debit must not flip to credit when balance delta suggests credit."""
    rows = [
        ParsedBankCsvRow(
            1,
            date(2026, 8, 1),
            "Opening gap",
            Decimal("10.00"),
            "debit",
            Decimal("100.00"),
            None,
            direction_confidence=DIRECTION_CONFIDENCE_HIGH,
        ),
        # Balance rose (+5) which would imply credit — but column said debit.
        ParsedBankCsvRow(
            2,
            date(2026, 8, 2),
            "Explicit debit",
            Decimal("5.00"),
            "debit",
            Decimal("105.00"),
            None,
            direction_confidence=DIRECTION_CONFIDENCE_HIGH,
        ),
    ]
    refined = refine_row_directions(rows)
    assert refined[1].direction == "debit"
    assert refined[1].direction_confidence == DIRECTION_CONFIDENCE_HIGH


def test_refine_still_fills_empty_direction_from_balance() -> None:
    rows = [
        ParsedBankCsvRow(1, date(2026, 8, 1), "A", Decimal("10"), "", Decimal("90"), None),
        ParsedBankCsvRow(2, date(2026, 8, 2), "B", Decimal("5"), "", Decimal("95"), None),
    ]
    refined = refine_row_directions(rows)
    assert refined[1].direction == "credit"
    assert refined[1].direction_confidence == DIRECTION_CONFIDENCE_MEDIUM


def test_balance_inferred_continuity_mismatch_kept_as_low_confidence() -> None:
    """0.2: medium + continuity failure → low confidence, row kept (not dropped)."""
    rows = [
        ParsedBankCsvRow(
            1,
            date(2026, 8, 1),
            "A",
            Decimal("10"),
            "debit",
            Decimal("100"),
            None,
            direction_confidence=DIRECTION_CONFIDENCE_HIGH,
        ),
        # Empty direction; balance delta implies credit (+5) but amount is 10 → mismatch.
        ParsedBankCsvRow(2, date(2026, 8, 2), "B", Decimal("10"), "", Decimal("105"), None),
    ]
    accepted, errors = finalize_parsed_rows(rows, reject_on_balance_continuity=True)
    assert len(accepted) == 2
    assert accepted[1].direction == "credit"
    assert accepted[1].direction_confidence == DIRECTION_CONFIDENCE_LOW
    assert any(BALANCE_CONTINUITY_MSG in err.message for err in errors)


def test_high_confidence_continuity_mismatch_still_rejected_when_hard() -> None:
    """Legacy hard path: explicit high-confidence rows still drop on continuity."""
    rows = [
        ParsedBankCsvRow(
            1,
            date(2026, 8, 1),
            "A",
            Decimal("10"),
            "debit",
            Decimal("100"),
            None,
            direction_confidence=DIRECTION_CONFIDENCE_HIGH,
        ),
        ParsedBankCsvRow(
            2,
            date(2026, 8, 2),
            "B",
            Decimal("5"),
            "debit",
            Decimal("90"),
            None,
            direction_confidence=DIRECTION_CONFIDENCE_HIGH,
        ),
    ]
    accepted, errors = finalize_parsed_rows(rows, reject_on_balance_continuity=True)
    assert [r.row_number for r in accepted] == [1]
    assert any(BALANCE_CONTINUITY_MSG in err.message for err in errors)


def test_document_with_day_gt_12_forces_dmy_for_all_rows() -> None:
    """0.3: presence of 13/01/2024 anywhere forces DMY for the whole document."""
    text = (
        "13/01/2024 Salary 100.00 in 1,100.00\n"
        "01/02/2024 Coffee 10.00 out 1,090.00\n"
    )
    result = parse_statement_text_block(text)
    assert result.parse_meta.get("date_order") == "dmy"
    assert result.parse_meta.get("date_order_assumed") == "false"
    assert len(result.rows) == 2
    assert result.rows[0].txn_date == date(2024, 1, 13)
    # Under DMY, 01/02/2024 is 1 February — not 2 January (MDY).
    assert result.rows[1].txn_date == date(2024, 2, 1)


def test_document_with_month_slot_day_gt_12_forces_mdy() -> None:
    inferred = infer_document_date_order(["01/13/2024", "02/01/2024"])
    assert inferred.order == "mdy"
    assert inferred.assumed is False
    assert parse_statement_date("02/01/2024", date_order="mdy") == date(2024, 2, 1)


def test_ambiguous_dates_assume_dmy_and_flag() -> None:
    inferred = infer_document_date_order(["01/02/2024", "03/04/2024"])
    assert inferred.order == "dmy"
    assert inferred.assumed is True


def test_ambiguous_dates_prefer_usd_currency_hint() -> None:
    inferred = infer_document_date_order(
        ["01/02/2024", "03/04/2024"],
        preferred_order="mdy",
    )
    assert inferred.order == "mdy"
    assert inferred.assumed is True
