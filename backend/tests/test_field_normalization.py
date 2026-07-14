"""Layer 2 — field normalization coverage for invoice#, vendor, amount, date."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.services.dossier.document_duplicate_service import normalize_invoice_number
from app.services.extraction.document_identity_service import (
    dates_within_tolerance,
    normalize_identity_value,
)
from app.services.extraction.invoice_no_sanitizer import invoice_no_dup_tokens_from_values
from app.services.master_data.vendor_name_utils import normalize_vendor_name


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("INV-001245", "inv1245"),
        ("INV-1245", "inv1245"),
        ("INV/2345", "inv2345"),
        ("INV_2345", "inv2345"),
        ("INV.2345", "inv2345"),
        ("inv 2345", "inv2345"),
    ],
)
def test_normalize_invoice_number_table(raw: str, expected: str) -> None:
    assert normalize_invoice_number(raw) == expected


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("INV2345", "2345"),
        ("INV2345A", "INV2345"),
        ("INV2345A", "2345"),
        ("INV-001245", "INV-1245"),
    ],
)
def test_invoice_no_dup_tokens_overlap(a: str, b: str) -> None:
    # Shared core digits when vendor matches (VR02); trailing letter / prefix noise.
    left = invoice_no_dup_tokens_from_values(a)
    right = invoice_no_dup_tokens_from_values(b)
    assert left & right


@pytest.mark.parametrize(
    ("raw", "expected_core"),
    [
        ("3B Semiconductors Pvt. Ltd.", "3B Semiconductors"),
        ("3B SEMICONDUCTORS PRIVATE LIMITED", "3B SEMICONDUCTORS"),
        ("3b semiconductors pvt ltd", "3b semiconductors"),
        ("Acme Inc.", "Acme"),
        ("Widgets LLC", "Widgets"),
    ],
)
def test_normalize_vendor_strips_legal_suffixes(raw: str, expected_core: str) -> None:
    got = normalize_vendor_name(raw)
    assert got is not None
    assert got.lower() == expected_core.lower()


def test_vendor_variants_collapse_to_same_key() -> None:
    variants = [
        "3B Semiconductors Pvt. Ltd.",
        "3B SEMICONDUCTORS PRIVATE LIMITED",
        "3b semiconductors pvt ltd",
    ]
    keys = {normalize_vendor_name(v).lower() for v in variants if normalize_vendor_name(v)}
    assert len(keys) == 1
    assert keys == {"3b semiconductors"}


def test_amount_normalized_to_two_dp() -> None:
    assert normalize_identity_value("total", "1,234.5") == "1234.50"
    assert normalize_identity_value("total", "$99.00") == "99.00"


def test_dates_within_tolerance_calendar_days() -> None:
    a = date(2026, 7, 1)
    b = date(2026, 7, 8)
    c = date(2026, 7, 9)
    assert dates_within_tolerance(a, b, days=7) is True
    assert dates_within_tolerance(a, c, days=7) is False
    assert dates_within_tolerance(a, None, days=7) is True
    assert dates_within_tolerance(None, None, days=7) is True
