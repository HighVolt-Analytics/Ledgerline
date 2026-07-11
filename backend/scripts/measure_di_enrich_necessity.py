#!/usr/bin/env python3
"""Compare line-item extraction with and without prebuilt-invoice DI enrich."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path

from app.schemas.ocr_artifact import OcrArtifact
from app.services.extraction.extraction_orchestrator import merge_extraction_sources
from app.services.extraction.line_items_parser import resolve_usable_line_items_from_payload
from app.services.invoice.invoice_data import InvoiceData, ParsedLineItem
from decimal import Decimal


@dataclass
class FixtureResult:
    name: str
    layout_only_rows: int
    layout_plus_enrich_rows: int
    descriptions_match: bool


def _fixture_a() -> tuple[str, dict, InvoiceData]:
    text = (
        "DESCRIPTION QTY UNIT PRICE AMOUNT\n"
        "Widget A 2 10.00 20.00\n"
        "Widget B 1 5.00 5.00\n"
    )
    payload = {
        "table_line_items": [
            {"description": "Widget A", "qty": "2", "unit_price": "10", "amount": "20"},
            {"description": "Widget B", "qty": "1", "unit_price": "5", "amount": "5"},
        ]
    }
    parsed = InvoiceData(
        line_items=[
            ParsedLineItem(description="Widget A", qty=Decimal("2"), unit_price=Decimal("10"), amount=Decimal("20")),
        ]
    )
    return text, payload, parsed


def _fixture_b() -> tuple[str, dict, InvoiceData]:
    text = (Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "qty_only_table_ocr.txt").read_text(
        encoding="utf-8"
    )
    payload = {
        "table_line_items": [
            {"description": "CPU CHIPS 14 Gen I3 14100", "qty": "150"},
        ]
    }
    parsed = InvoiceData(
        line_items=[ParsedLineItem(description="CPU CHIPS 14 Gen I3 14100", qty=Decimal("150"))]
    )
    return text, payload, parsed


def _run_fixture(name: str, text: str, payload: dict, parsed: InvoiceData) -> FixtureResult:
    layout_payload = {key: value for key, value in payload.items() if key != "di_line_items"}
    enrich_payload = dict(payload)
    if "di_line_items" not in enrich_payload and layout_payload.get("table_line_items"):
        enrich_payload["di_line_items"] = layout_payload["table_line_items"]

    layout_rows = resolve_usable_line_items_from_payload(layout_payload)
    enrich_rows = resolve_usable_line_items_from_payload(enrich_payload)

    layout_merged = merge_extraction_sources(
        parsed,
        OcrArtifact(success=True, text=text, text_length=len(text), payload_json=layout_payload),
    )
    enrich_merged = merge_extraction_sources(
        parsed,
        OcrArtifact(success=True, text=text, text_length=len(text), payload_json=enrich_payload),
    )

    layout_desc = [(row.description or "").lower() for row in layout_merged.line_items]
    enrich_desc = [(row.description or "").lower() for row in enrich_merged.line_items]
    return FixtureResult(
        name=name,
        layout_only_rows=len(layout_rows),
        layout_plus_enrich_rows=len(enrich_rows),
        descriptions_match=layout_desc == enrich_desc,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Emit JSON report")
    args = parser.parse_args()

    fixtures = [
        ("fixture_a_product_table", *_fixture_a()),
        ("fixture_b_qty_only", *_fixture_b()),
    ]
    results = [_run_fixture(name, text, payload, parsed) for name, text, payload, parsed in fixtures]

    if args.json:
        print(json.dumps([asdict(row) for row in results], indent=2))
        return

    for row in results:
        print(
            f"{row.name}: layout_rows={row.layout_only_rows} "
            f"enrich_rows={row.layout_plus_enrich_rows} match={row.descriptions_match}"
        )


if __name__ == "__main__":
    main()
