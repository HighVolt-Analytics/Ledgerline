"""Merge disagreement telemetry tests."""

from __future__ import annotations

from decimal import Decimal

from app.services.extraction.merge_disagreement_telemetry import collect_scalar_disagreements
from app.services.invoice.invoice_data import InvoiceData


def test_collect_scalar_disagreements_detects_mismatch() -> None:
    llm = InvoiceData(vendor="ACME", total=Decimal("100"))
    di = InvoiceData(vendor="ACME", total=Decimal("200"))
    rows = collect_scalar_disagreements(
        field_keys=["vendor", "total"],
        llm_parsed=llm,
        di_parsed=di,
        regex_parsed=None,
        merged=llm,
    )
    total_row = next(row for row in rows if row.field_key == "total")
    assert not total_row.agreed
