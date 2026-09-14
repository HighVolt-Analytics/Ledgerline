"""Record dictionary adoption lineage when org document types are first saved."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document_type_adoption_lineage import DocumentTypeAdoptionLineage


def _document_type_rows(raw: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(raw, dict):
        return []
    rows = raw.get("document_types") or raw.get("documentTypes") or []
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


def _org_code(row: dict[str, Any]) -> str:
    return str(row.get("code") or row.get("dt_code") or "").strip().upper()


def _source_dictionary_code(row: dict[str, Any]) -> str:
    return str(row.get("source_dictionary_code") or row.get("sourceDictionaryCode") or "").strip().upper()


def _created_from_dictionary_version(row: dict[str, Any]) -> int | None:
    raw = row.get("created_from_dictionary_version", row.get("createdFromDictionaryVersion"))
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def detect_new_dictionary_adoptions(
    before_raw: dict[str, Any] | None,
    after_raw: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    before_codes = {_org_code(row) for row in _document_type_rows(before_raw) if _org_code(row)}
    out: list[dict[str, Any]] = []
    for row in _document_type_rows(after_raw):
        org_code = _org_code(row)
        source_code = _source_dictionary_code(row)
        version = _created_from_dictionary_version(row)
        if not org_code or not source_code or version is None:
            continue
        if org_code in before_codes:
            continue
        out.append(
            {
                "org_doc_type_code": org_code,
                "source_dictionary_code": source_code,
                "source_dictionary_version": version,
            }
        )
    return out


async def record_document_type_adoptions(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    before_raw: dict[str, Any] | None,
    after_raw: dict[str, Any] | None,
) -> int:
    adoptions = detect_new_dictionary_adoptions(before_raw, after_raw)
    if not adoptions:
        return 0
    now = datetime.now(timezone.utc)
    for row in adoptions:
        session.add(
            DocumentTypeAdoptionLineage(
                tenant_id=tenant_id,
                org_doc_type_code=row["org_doc_type_code"],
                source_dictionary_code=row["source_dictionary_code"],
                source_dictionary_version=row["source_dictionary_version"],
                adopted_at=now,
            )
        )
    return len(adoptions)
