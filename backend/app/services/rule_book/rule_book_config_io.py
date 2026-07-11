"""Org-scoped classification rule book storage (DB source of truth)."""

from __future__ import annotations

import json
import time
import uuid
from copy import deepcopy
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.schemas.rule_book_config import RuleBookConfigPayload, validate_rule_book_config_payload
from app.services.rule_book.rule_book_config_repository import (
    ensure_default_config,
    fetch_config_dict,
    upsert_config,
)
from app.services.rule_book.rule_book_ingest_stats import strip_email_capture_volatile_stats
from app.tenant_ids import PLATFORM_TENANT_UUID, TESTING_TENANT_UUID, parse_tenant_id

_LEGACY_FILE_TENANT_MAP: dict[str, uuid.UUID] = {
    "1": TESTING_TENANT_UUID,
    "2": PLATFORM_TENANT_UUID,
}

_POSTING_CONFIG_CACHE_TTL_SEC = 30.0
_posting_config_cache: dict[uuid.UUID, tuple[float, RuleBookConfigPayload]] = {}


def clear_posting_config_cache() -> None:
    _posting_config_cache.clear()


def global_rule_book_config_path() -> Path:
    return Path(get_settings().rule_book_config_path)


def tenant_rule_book_config_path(tenant_id: uuid.UUID | int | str) -> Path:
    """Legacy filesystem path (fallback import only)."""
    base = Path(get_settings().upload_dir) / "rule_books"
    return base / f"{tenant_id}_config.json"


def _legacy_file_paths_for_tenant(tenant_id: uuid.UUID) -> list[Path]:
    paths = [tenant_rule_book_config_path(tenant_id)]
    for legacy_key, mapped in _LEGACY_FILE_TENANT_MAP.items():
        if mapped == tenant_id:
            paths.append(tenant_rule_book_config_path(legacy_key))
    extra = Path("./data/uploads/rule_books") / f"{tenant_id}_config.json"
    if extra not in paths:
        paths.append(extra)
    for legacy_key, mapped in _LEGACY_FILE_TENANT_MAP.items():
        if mapped == tenant_id:
            legacy_extra = Path("./data/uploads/rule_books") / f"{legacy_key}_config.json"
            if legacy_extra not in paths:
                paths.append(legacy_extra)
    return paths


def _load_legacy_file_dict(tenant_id: uuid.UUID) -> dict[str, Any] | None:
    legacy = load_legacy_file_dict_with_masters(tenant_id)
    if legacy is None:
        return None
    data = deepcopy(legacy)
    data.pop("vendor_masters", None)
    data.pop("employee_masters", None)
    return data


def load_legacy_file_dict_with_masters(tenant_id: uuid.UUID) -> dict[str, Any] | None:
    for path in _legacy_file_paths_for_tenant(tenant_id):
        if not path.is_file():
            continue
        with path.open(encoding="utf-8") as fh:
            raw = json.load(fh)
        if isinstance(raw, dict):
            return deepcopy(raw)
    return None


async def load_rule_book_config_dict(
    session: AsyncSession,
    tenant_id: uuid.UUID,
) -> dict[str, Any]:
    """Load config from DB; fall back to legacy file and upsert into DB."""
    tid = parse_tenant_id(tenant_id)
    if tid is None:
        raise ValueError("Invalid tenant_id")

    stored = await fetch_config_dict(session, tid)
    if stored is not None:
        fixed = validate_rule_book_config_payload(stored).model_dump()
        if fixed.get("document_types") != stored.get("document_types"):
            await upsert_config(session, tid, fixed)
        return fixed

    legacy = _load_legacy_file_dict(tid)
    if legacy is not None:
        await upsert_config(session, tid, legacy)
        return legacy

    return await ensure_default_config(session, tid)


async def merge_persisted_rule_book_slices(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    incoming: dict[str, Any],
) -> dict[str, Any]:
    """Preserve config slices not included in RuleBookRulesPayload PUT bodies."""
    stored = await load_rule_book_config_dict(session, tenant_id)
    merged = dict(incoming)
    if not merged.get("chart_of_accounts"):
        merged["chart_of_accounts"] = stored.get("chart_of_accounts") or []
    return merged


async def save_rule_book_config(
    session: AsyncSession,
    payload: RuleBookConfigPayload,
    tenant_id: uuid.UUID,
    *,
    updated_by_user_id: int | None = None,
) -> None:
    from app.services.classification.document_type_catalog import clear_document_type_catalog_cache
    from app.services.rule_book.rule_book_mapper import clear_classification_config_cache

    tid = parse_tenant_id(tenant_id)
    if tid is None:
        raise ValueError("Invalid tenant_id")

    data = payload.model_dump()
    data.pop("vendor_masters", None)
    data.pop("employee_masters", None)
    strip_email_capture_volatile_stats(data)
    from app.services.classification.document_type_lifecycle import scrub_document_type_references

    scrubbed = scrub_document_type_references(validate_rule_book_config_payload(data))
    data = scrubbed.model_dump()
    await upsert_config(
        session,
        tid,
        data,
        updated_by_user_id=updated_by_user_id,
    )
    clear_classification_config_cache()
    clear_document_type_catalog_cache()
    clear_posting_config_cache()


async def load_rule_book_config_with_masters(
    session: AsyncSession,
    tenant_id: uuid.UUID,
) -> dict[str, Any]:
    from app.services.master_data.master_data_service import attach_masters_to_config_dict

    raw = await load_rule_book_config_dict(session, tenant_id)
    return await attach_masters_to_config_dict(session, tenant_id, raw)


async def load_posting_config_payload(
    session: AsyncSession,
    tenant_id: uuid.UUID,
) -> RuleBookConfigPayload:
    """Cached rule book without master tables — safe for dossier/matrix read paths."""
    tid = parse_tenant_id(tenant_id)
    if tid is None:
        raise ValueError("Invalid tenant_id")

    now = time.monotonic()
    cached = _posting_config_cache.get(tid)
    if cached is not None and now - cached[0] < _POSTING_CONFIG_CACHE_TTL_SEC:
        return cached[1]

    raw = await load_rule_book_config_dict(session, tid)
    payload = validate_rule_book_config_payload(raw)
    _posting_config_cache[tid] = (now, payload)
    return payload
