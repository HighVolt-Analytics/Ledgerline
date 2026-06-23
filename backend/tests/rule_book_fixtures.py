"""Shared rule book fixtures for tests (org-defined document type catalogue)."""

from __future__ import annotations

import json
from pathlib import Path

from app.schemas.rule_book_config import RuleBookConfigPayload, validate_rule_book_config_payload

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def load_capture_config() -> RuleBookConfigPayload:
    """Demo rule book + optional test document type cards."""
    data = json.loads((_FIXTURES / "rule_book_demo.json").read_text(encoding="utf-8"))
    catalog_path = _FIXTURES / "document_types_test_catalog.json"
    if catalog_path.is_file():
        data["document_types"] = json.loads(catalog_path.read_text(encoding="utf-8"))
    return validate_rule_book_config_payload(data)
