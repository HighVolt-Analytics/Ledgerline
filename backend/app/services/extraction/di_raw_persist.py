"""Config-driven persistence of raw Azure DI analyze results."""

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any, Literal

from app.config import get_settings
from app.services.invoice.invoice_data import InvoiceData
from app.utils.logger import get_logger

logger = get_logger(__name__)

DiOutcome = Literal["success", "failure", "review"]


def serialize_di_analyze_result(result: Any) -> dict[str, Any] | None:
    """Best-effort serialize Azure DI AnalyzeResult to a JSON-safe dict."""
    if result is None:
        return None
    as_dict = getattr(result, "as_dict", None)
    if callable(as_dict):
        try:
            data = as_dict()
            if isinstance(data, dict):
                return data
        except Exception as exc:
            logger.warning("di_raw_as_dict_failed", error=str(exc))
    # Fallback: shallow snapshot
    snapshot: dict[str, Any] = {}
    content = getattr(result, "content", None)
    if content is not None:
        snapshot["content"] = str(content)[:50_000]
    pages = getattr(result, "pages", None)
    if pages is not None:
        snapshot["page_count"] = len(pages)
    documents = getattr(result, "documents", None)
    if documents is not None:
        snapshot["document_count"] = len(documents)
        if documents:
            fields = getattr(documents[0], "fields", None) or {}
            snapshot["field_names"] = sorted(str(k) for k in fields.keys())
    tables = getattr(result, "tables", None)
    if tables is not None:
        snapshot["table_count"] = len(tables)
    api_version = getattr(result, "api_version", None)
    if api_version:
        snapshot["apiVersion"] = str(api_version)
    model_id = getattr(result, "model_id", None)
    if model_id:
        snapshot["modelId"] = str(model_id)
    return snapshot or None


def should_persist_raw_di(outcome: DiOutcome) -> bool:
    settings = get_settings()
    mode = (settings.di_raw_persist_mode or "failures").strip().lower()
    if mode in {"off", "never", "none"}:
        return False
    if mode == "always":
        return True
    if mode == "failures":
        return outcome in {"failure", "review"}
    if mode == "sample":
        if outcome in {"failure", "review"}:
            return True
        return random.random() < float(settings.di_raw_persist_sample_rate)
    return outcome in {"failure", "review"}


def maybe_attach_raw_di(
    raw_snapshot: dict[str, Any] | None,
    *,
    model_id: str,
    outcome: DiOutcome,
) -> dict[str, object] | None:
    if raw_snapshot is None or not should_persist_raw_di(outcome):
        return None
    settings = get_settings()
    max_chars = int(settings.di_raw_max_chars)
    try:
        body_str = json.dumps(raw_snapshot, default=str)
    except (TypeError, ValueError):
        body_str = str(raw_snapshot)
    truncated = len(body_str) > max_chars
    if truncated:
        body_str = body_str[:max_chars]
        try:
            body: object = json.loads(body_str)
        except json.JSONDecodeError:
            body = body_str
    else:
        body = raw_snapshot
    return {
        "model_id": model_id,
        "api_version_hint": "2024-11-30",
        "truncated": truncated,
        "outcome": outcome,
        "body": body,
    }


def parse_invoice_with_raw(
    file_path: str | Path,
    *,
    content_type: str = "application/pdf",
    model_id_override: str | None = None,
) -> tuple[InvoiceData | None, dict[str, Any] | None, DiOutcome]:
    """
    Run prebuilt-invoice (or override model) and return (data, raw_snapshot, outcome).

    Does not apply persist policy — callers use maybe_attach_raw_di.
    """
    from app.services.extraction.document_intelligence import (
        is_di_enabled,
        parse_with_document_intelligence_ex,
    )

    if not is_di_enabled():
        return None, None, "failure"

    data, raw = parse_with_document_intelligence_ex(
        file_path,
        content_type=content_type,
        model_id_override=model_id_override,
    )
    if data is None:
        return None, raw, "failure"
    return data, raw, "success"
