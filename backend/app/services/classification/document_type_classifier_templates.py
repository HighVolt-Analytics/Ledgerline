"""Load shipped document-type classifier templates from JSON (config data, not code)."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.config import get_settings


def _templates_path() -> Path:
    return Path(get_settings().document_type_classifiers_path)


@lru_cache
def load_classifier_templates() -> dict[str, dict[str, Any]]:
    path = _templates_path()
    if not path.is_file():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("document type classifiers file must be a JSON object")
    return {str(code).strip().upper(): value for code, value in raw.items()}


def classifier_template_for_code(code: str) -> dict[str, Any] | None:
    template = load_classifier_templates().get(code.strip().upper())
    if not isinstance(template, dict):
        return None
    return dict(template)


def clear_classifier_templates_cache() -> None:
    load_classifier_templates.cache_clear()
