"""Resolve LLM + policy classification detail from pipeline audit events."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog
from app.models.invoice import Invoice

_CLASSIFICATION_DETAIL_EVENTS = frozenset(
    {
        "document_classified",
        "classification_gate_passed",
        "classification_gate_failed",
        "llm_classified",
        "routing_review_required",
    }
)

_DETAIL_KEYS = (
    "llm_suggested_dt",
    "llm_confidence",
    "llm_reasoning",
    "policy_winner_dt",
    "policy_winner_confidence",
    "confirmed_dt",
    "confirmed_confidence",
    "document_type_code",
    "document_type_confidence",
    "compare_passed",
    "review_reasons",
    "document_ai_provider",
    "min_route_confidence",
)


def _as_dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _sort_key(row: AuditLog) -> tuple[datetime, int]:
    return (row.created_at or datetime.min, int(row.id or 0))


def merge_classification_audit_detail(
    *,
    invoice: Invoice,
    logs: list[AuditLog],
) -> dict[str, Any]:
    """Merge classification audit rows — newest pipeline run wins per field."""
    merged: dict[str, Any] = {}
    for row in sorted(logs, key=_sort_key, reverse=True):
        if row.event not in _CLASSIFICATION_DETAIL_EVENTS:
            continue
        detail = _as_dict(row.detail)
        if row.event == "routing_review_required":
            if str(detail.get("gate") or "").strip().lower() != "classification":
                continue
        for key in _DETAIL_KEYS:
            if key in merged:
                continue
            if key not in detail:
                continue
            value = detail[key]
            if value is None:
                continue
            if key == "review_reasons" and not value:
                continue
            merged[key] = value

    if "llm_suggested_dt" not in merged and invoice.llm_suggested_dt:
        merged["llm_suggested_dt"] = invoice.llm_suggested_dt
    if "llm_confidence" not in merged and invoice.llm_confidence is not None:
        merged["llm_confidence"] = invoice.llm_confidence
    if "document_type_code" not in merged and invoice.document_type_code:
        merged["document_type_code"] = invoice.document_type_code
    if "document_type_confidence" not in merged and invoice.document_type_confidence is not None:
        merged["document_type_confidence"] = invoice.document_type_confidence

    return merged


async def load_classification_audit_detail(
    session: AsyncSession,
    *,
    invoice: Invoice,
    tenant_id: uuid.UUID,
) -> dict[str, Any]:
    rows = (
        await session.execute(
            select(AuditLog)
            .where(
                AuditLog.invoice_id == invoice.id,
                AuditLog.tenant_id == tenant_id,
                AuditLog.event.in_(tuple(_CLASSIFICATION_DETAIL_EVENTS)),
            )
            .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
            .limit(40)
        )
    ).scalars().all()
    return merge_classification_audit_detail(invoice=invoice, logs=list(rows))
