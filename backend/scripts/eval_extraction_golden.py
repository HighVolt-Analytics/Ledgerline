#!/usr/bin/env python3
"""Golden-set extraction evaluator — field-level scoring per DT."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from app.services.extraction.extraction_orchestrator import merge_extraction_sources
from app.services.extraction.line_items_parser import (
    document_has_product_table,
    document_has_qty_only_table,
    parse_qty_only_line_items_from_text,
)
from app.services.extraction.pdf_parser import parse_local_text
from app.schemas.ocr_artifact import OcrArtifact

_GOLDEN_ROOT = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "golden"


def _load_manifest(root: Path) -> list[dict]:
    manifest_path = root / "manifest.json"
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    return list(data.get("fixtures") or [])


def _evaluate_fixture(fixture_id: str, root: Path) -> dict:
    fixture_dir = root / fixture_id
    expected = json.loads((fixture_dir / "expected.json").read_text(encoding="utf-8"))
    text = (fixture_dir / "input.txt").read_text(encoding="utf-8")
    parsed = parse_local_text(text)
    ocr = OcrArtifact(text=text, sparse=len(text.strip()) < 80, text_length=len(text))
    merged = merge_extraction_sources(parsed, ocr, dt_definition=None)
    qty_rows = parse_qty_only_line_items_from_text(text) if document_has_qty_only_table(text, {}) else []
    line_count = len(merged.line_items or qty_rows or [])
    li_expect = expected.get("line_items") or {}
    min_count = int(li_expect.get("min_count", 0))
    max_count = li_expect.get("max_count")
    passed = line_count >= min_count
    if max_count is not None:
        passed = passed and line_count <= int(max_count)
    fields = expected.get("fields") or {}
    field_results: dict[str, bool] = {}
    for key, want in fields.items():
        got = getattr(merged, key, None) or (merged.extracted_fields or {}).get(key)
        field_results[key] = str(got or "").strip() == str(want).strip()
        passed = passed and field_results[key]
    return {
        "fixture_id": fixture_id,
        "dt_code": expected.get("dt_code"),
        "passed": passed,
        "line_items_count": line_count,
        "field_results": field_results,
        "qty_only_table": document_has_qty_only_table(text, {}),
        "product_table": document_has_product_table(text, {}),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate golden extraction fixtures")
    parser.add_argument("--root", type=Path, default=_GOLDEN_ROOT)
    parser.add_argument("--fixture", action="append", dest="fixtures")
    args = parser.parse_args(argv)
    manifest = _load_manifest(args.root)
    selected = {row["id"] for row in manifest}
    if args.fixtures:
        selected = {token.strip() for token in args.fixtures if token.strip()}
    results = [_evaluate_fixture(fixture_id, args.root) for fixture_id in sorted(selected)]
    passed = sum(1 for row in results if row["passed"])
    print(json.dumps({"passed": passed, "total": len(results), "results": results}, indent=2))
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
