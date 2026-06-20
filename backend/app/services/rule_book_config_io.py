"""Org-scoped classification rule book storage."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from app.config import get_settings
from app.schemas.rule_book_config import RuleBookConfigPayload, validate_rule_book_config_payload


def global_rule_book_config_path() -> Path:
    return Path(get_settings().rule_book_config_path)


def org_rule_book_config_path(org_id: int) -> Path:
    base = Path(get_settings().upload_dir) / "rule_books"
    return base / f"{org_id}_config.json"


def _seed_org_rule_book_config(org_id: int) -> Path:
    """Create org rule book from template once; never overwrite saved org config."""
    path = org_rule_book_config_path(org_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file():
        return path

    template = global_rule_book_config_path()
    if template.is_file():
        shutil.copy2(template, path)
    else:
        payload = RuleBookConfigPayload()
        path.write_text(
            json.dumps(payload.model_dump(), indent=2) + "\n",
            encoding="utf-8",
        )
    return path


def load_rule_book_config_dict(org_id: int) -> dict[str, Any]:
    path = _seed_org_rule_book_config(org_id)
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def save_rule_book_config(payload: RuleBookConfigPayload, org_id: int) -> Path:
    from app.services.document_type_catalog import clear_document_type_catalog_cache
    from app.services.rule_book_mapper import clear_classification_config_cache

    path = org_rule_book_config_path(org_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = payload.model_dump()
    with path.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
        fh.write("\n")
    clear_classification_config_cache()
    clear_document_type_catalog_cache()
    return path
