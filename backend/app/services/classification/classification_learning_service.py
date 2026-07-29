"""Classification learning events and few-shot prompt snippets (tenant RLS)."""

from __future__ import annotations

import re
import uuid
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog
from app.models.classification_learning import ClassificationLearningEvent, InvoiceOcrArtifact
from app.models.invoice import Invoice
from app.schemas.classification_decision import ClassificationDecision
from app.schemas.llm_document import LlmDocumentResult
from app.schemas.ocr_artifact import OcrArtifact
from app.services.master_data.vendor_name_utils import normalize_vendor_name
from app.services.master_data.vendor_resolver import UNKNOWN_SLUG, slugify_vendor_name

_FEW_SHOT_TEXT_MAX = 600
_HEADING_MAX = 120


def resolve_vendor_learning_key(invoice: Invoice) -> str | None:
    """Stable vendor key for per-vendor template learning and drift stats."""
    slug = (invoice.storage_vendor_slug or "").strip().lower()
    if slug and slug != UNKNOWN_SLUG:
        return slug[:100]
    vendor = normalize_vendor_name(invoice.vendor)
    if vendor:
        return slugify_vendor_name(vendor)[:100]
    return None


def _heading_from_text(text: str | None) -> str:
    if not text:
        return ""
    for line in text.splitlines():
        token = line.strip()
        if len(token) >= 4:
            return token[:_HEADING_MAX]
    return ""


def _few_shot_note(
    *,
    llm_suggested_dt: str | None,
    human_confirmed_dt: str,
    policy_winner_dt: str | None,
    document_heading: str,
    vendor_key: str | None = None,
) -> str:
    llm = (llm_suggested_dt or "").strip().upper()
    human = human_confirmed_dt.strip().upper()
    policy = (policy_winner_dt or "").strip().upper()
    heading = document_heading.strip()
    if llm and llm != human:
        base = f"Reviewer corrected {llm} → {human}"
    else:
        base = f"Reviewer confirmed {human}"
    if policy and policy != human:
        base = f"{base} (policy had {policy})"
    if vendor_key:
        base = f"{base} for vendor '{vendor_key}'"
    if heading:
        return f"{base} for document headed '{heading}'"
    return base


def _learning_row_to_example(
    row: ClassificationLearningEvent,
    *,
    excerpt: str,
    heading: str,
) -> dict[str, str]:
    human = normalize_learning_dt_code(row.human_confirmed_dt)
    llm = (row.llm_suggested_dt or "").strip().upper()
    policy = (row.policy_winner_dt or "").strip().upper()
    reasons = row.review_reasons if isinstance(row.review_reasons, list) else []
    vendor_key = (row.vendor_key or "").strip().lower()
    example: dict[str, str] = {
        "llm_suggested_dt": llm,
        "human_confirmed_dt": human,
        "policy_winner_dt": policy,
        "document_heading": heading[:_HEADING_MAX],
        "text_excerpt": excerpt[:_FEW_SHOT_TEXT_MAX],
        "review_reasons": ",".join(str(r) for r in reasons if str(r).strip()),
        "note": _few_shot_note(
            llm_suggested_dt=llm,
            human_confirmed_dt=human,
            policy_winner_dt=policy,
            document_heading=heading,
            vendor_key=vendor_key or None,
        ),
    }
    if vendor_key:
        example["vendor_key"] = vendor_key
    return example


async def _latest_ocr_artifact(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    invoice_id: int,
    file_hash: str | None,
) -> InvoiceOcrArtifact | None:
    if not file_hash:
        return None
    stmt = (
        select(InvoiceOcrArtifact)
        .where(
            InvoiceOcrArtifact.tenant_id == tenant_id,
            InvoiceOcrArtifact.invoice_id == invoice_id,
            InvoiceOcrArtifact.file_hash == file_hash,
        )
        .order_by(InvoiceOcrArtifact.created_at.desc())
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def store_ocr_artifact(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    invoice_id: int,
    file_hash: str,
    ocr: OcrArtifact,
) -> InvoiceOcrArtifact:
    payload = dict(ocr.payload_json or {})
    if ocr.layout_kv:
        payload["layout_kv"] = dict(ocr.layout_kv)
    if ocr.text:
        # Persist full OCR for merge/grounding; text_excerpt stays a short preview
        payload["ocr_text"] = ocr.text
    row = InvoiceOcrArtifact(
        tenant_id=tenant_id,
        invoice_id=invoice_id,
        file_hash=file_hash,
        di_model=ocr.di_model,
        payload_json=payload,
        text_excerpt=(ocr.text or "")[:8000],
    )
    session.add(row)
    await session.flush()
    return row


async def clear_ocr_artifacts_for_invoice(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    invoice_id: int,
) -> int:
    """Drop cached OCR rows so reprocess re-runs layout parse with current filters."""
    result = await session.execute(
        delete(InvoiceOcrArtifact).where(
            InvoiceOcrArtifact.tenant_id == tenant_id,
            InvoiceOcrArtifact.invoice_id == invoice_id,
        )
    )
    await session.flush()
    return int(result.rowcount or 0)

async def upsert_ocr_artifact_enrichment(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    invoice_id: int,
    file_hash: str,
    ocr: OcrArtifact,
) -> InvoiceOcrArtifact | None:
    """Persist DI enrich / route metadata onto the latest OCR artifact row (or create one)."""
    payload = dict(ocr.payload_json or {})
    has_enrich = (
        "invoice_fields" in payload
        or "extraction_route" in payload
        or "finance_document" in payload
        or "di_line_items" in payload
        or "field_resolution" in payload
    )
    if not has_enrich:
        return None
    row = await _latest_ocr_artifact(
        session,
        tenant_id=tenant_id,
        invoice_id=invoice_id,
        file_hash=file_hash,
    )
    if row is None:
        return await store_ocr_artifact(
            session,
            tenant_id=tenant_id,
            invoice_id=invoice_id,
            file_hash=file_hash,
            ocr=ocr,
        )
    merged_payload = dict(row.payload_json or {})
    enrich_keys = (
        "invoice_fields",
        "di_line_items",
        "di_scalar_sources",
        "di_party_fields",
        "di_party_sources",
        "table_line_items",
        "layout_table_grids",
        "document_heading",
        "extraction_route",
        "extraction_strategy",
        "di_models_run",
        "layout_line_mode",
        "field_confidence",
        "field_sources",
        "di_line_item_confidences",
        "review_hints",
        "fallback_reason",
        "route_reasons",
        "finance_document",
        "raw_di",
        "di_model",
        "provider",
        "layout_kv",
        "ocr_text",
        "field_resolution",
        "resolved_contracts",
        "selected_keys",
        "semantic_fields",
    )
    for key in enrich_keys:
        if key in payload:
            merged_payload[key] = payload[key]
    # When DI/layout line items refresh, drop stale counterparts that were not rewritten
    if "di_line_items" in payload and "table_line_items" not in payload:
        # Prefer keeping existing table rows unless grids supersede
        pass
    if payload.get("layout_table_grids") or payload.get("di_line_items"):
        # Replace stale table rows when new structured rows are present
        if "table_line_items" in payload:
            merged_payload["table_line_items"] = payload["table_line_items"]
        if "layout_table_grids" in payload:
            merged_payload["layout_table_grids"] = payload["layout_table_grids"]
    if ocr.layout_kv:
        merged_payload["layout_kv"] = dict(ocr.layout_kv)
    if ocr.text:
        merged_payload["ocr_text"] = ocr.text
    row.payload_json = merged_payload
    row.di_model = ocr.di_model or row.di_model
    if ocr.text:
        row.text_excerpt = (ocr.text or "")[:8000]
    await session.flush()
    return row


async def load_cached_ocr(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    invoice_id: int,
    file_hash: str,
) -> OcrArtifact | None:
    stmt = (
        select(InvoiceOcrArtifact)
        .where(
            InvoiceOcrArtifact.tenant_id == tenant_id,
            InvoiceOcrArtifact.invoice_id == invoice_id,
            InvoiceOcrArtifact.file_hash == file_hash,
        )
        .order_by(InvoiceOcrArtifact.created_at.desc())
        .limit(1)
    )
    row = (await session.execute(stmt)).scalar_one_or_none()
    if row is None:
        return None
    payload = dict(row.payload_json or {}) if isinstance(row.payload_json, dict) else {}
    text = str(payload.get("ocr_text") or "").strip() or (row.text_excerpt or "")
    raw_kv = payload.get("layout_kv") if isinstance(payload.get("layout_kv"), dict) else {}
    layout_kv = {str(k): str(v) for k, v in raw_kv.items() if v is not None}
    return OcrArtifact(
        success=True,
        sparse=len(text.strip()) < 80,
        text=text,
        text_length=len(text),
        di_model=row.di_model or "",
        layout_kv=layout_kv,
        payload_json=payload,
    )


async def record_learning_event(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    invoice_id: int,
    file_hash: str | None,
    human_confirmed_dt: str,
    decision: ClassificationDecision | None = None,
    llm: LlmDocumentResult | None = None,
    reviewer_user_id: uuid.UUID | None = None,
    ocr_artifact_id: uuid.UUID | None = None,
    llm_suggested_dt: str | None = None,
    policy_winner_dt: str | None = None,
    review_reasons: list[str] | None = None,
    document_heading: str | None = None,
    text_excerpt: str | None = None,
    vendor_key: str | None = None,
) -> ClassificationLearningEvent:
    ocr_row = None
    if ocr_artifact_id is None and file_hash:
        ocr_row = await _latest_ocr_artifact(
            session,
            tenant_id=tenant_id,
            invoice_id=invoice_id,
            file_hash=file_hash,
        )
        if ocr_row is not None:
            ocr_artifact_id = ocr_row.id

    resolved_llm_dt = (
        llm_suggested_dt
        or (decision.llm_suggested_dt if decision else None)
        or (llm.suggested_dt if llm else None)
    )
    resolved_policy_dt = policy_winner_dt or (decision.policy_winner_dt if decision else None)
    resolved_reasons = (
        list(review_reasons)
        if review_reasons is not None
        else ([r.value for r in decision.review_reasons] if decision else [])
    )
    excerpt_source = text_excerpt or (ocr_row.text_excerpt if ocr_row else "") or ""
    excerpt = excerpt_source.strip()[:8000]
    heading = (document_heading or _heading_from_text(excerpt)).strip()[:_HEADING_MAX]

    learning_context: dict[str, Any] = {
        "source": "human_resolution",
        "document_heading": heading,
        "text_excerpt": excerpt[:_FEW_SHOT_TEXT_MAX],
    }
    if vendor_key:
        learning_context["vendor_key"] = vendor_key.strip().lower()
    if llm is not None and llm.raw:
        learning_context["llm_raw"] = llm.raw

    event = ClassificationLearningEvent(
        tenant_id=tenant_id,
        invoice_id=invoice_id,
        file_hash=file_hash,
        ocr_artifact_id=ocr_artifact_id,
        llm_suggested_dt=(resolved_llm_dt or "").strip().upper() or None,
        llm_confidence=decision.llm_confidence if decision else (llm.confidence if llm else None),
        policy_winner_dt=(resolved_policy_dt or "").strip().upper() or None,
        human_confirmed_dt=human_confirmed_dt.strip().upper(),
        vendor_key=(vendor_key or "").strip().lower() or None,
        review_reasons=resolved_reasons,
        llm_response=learning_context,
        reviewer_user_id=reviewer_user_id,
    )
    session.add(event)
    await session.flush()
    return event


async def record_learning_from_resolution(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    invoice: Invoice,
    human_confirmed_dt: str,
    classification_detail: dict[str, Any] | None,
    reviewer_user_id: uuid.UUID | None = None,
) -> ClassificationLearningEvent:
    """Persist a rich learning row after POST /classification/resolve."""
    detail = classification_detail or {}
    heading = str(
        detail.get("document_heading")
        or getattr(invoice, "document_heading", None)
        or ""
    ).strip()
    if not heading and invoice.document_text:
        heading = _heading_from_text(invoice.document_text)

    return await record_learning_event(
        session,
        tenant_id=tenant_id,
        invoice_id=invoice.id,
        file_hash=invoice.file_hash,
        human_confirmed_dt=human_confirmed_dt,
        reviewer_user_id=reviewer_user_id,
        vendor_key=resolve_vendor_learning_key(invoice),
        llm_suggested_dt=str(
            detail.get("llm_suggested_dt") or invoice.llm_suggested_dt or ""
        ),
        policy_winner_dt=str(detail.get("policy_winner_dt") or ""),
        review_reasons=[str(r) for r in (detail.get("review_reasons") or []) if str(r).strip()],
        document_heading=heading or None,
        text_excerpt=(invoice.document_text or "")[:8000] or None,
    )


def normalize_learning_dt_code(code: str | None) -> str:
    return (code or "").strip().upper()


async def purge_learning_events_for_document_type(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    document_type_code: str,
) -> int:
    """Remove few-shot rows that teach a document type removed from the Rule Book."""
    token = normalize_learning_dt_code(document_type_code)
    if not token:
        return 0
    result = await session.execute(
        delete(ClassificationLearningEvent).where(
            ClassificationLearningEvent.tenant_id == tenant_id,
            ClassificationLearningEvent.human_confirmed_dt == token,
        )
    )
    await session.flush()
    return int(result.rowcount or 0)


def normalize_heading_for_learning(heading: str | None) -> str:
    """Normalize printed titles for tenant synonym / correction lookup."""
    token = (heading or "").strip().lower()
    if not token:
        return ""
    token = re.sub(r"[^\w\s/+.-]+", " ", token, flags=re.UNICODE)
    token = re.sub(r"\s+", " ", token).strip()
    return token[:_HEADING_MAX]


def _heading_from_learning_row(row: ClassificationLearningEvent) -> str:
    if isinstance(row.llm_response, dict):
        return str(row.llm_response.get("document_heading") or "").strip()
    return ""


async def learned_document_type_for_heading(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    document_heading: str | None,
    valid_dt_codes: set[str] | None = None,
    vendor_key: str | None = None,
    limit_scan: int = 40,
) -> tuple[str, float] | None:
    """Return (DT code, confidence) when reviewers previously confirmed this title.

    Prefers vendor-scoped corrections, then tenant-wide. Requires exact normalized
    heading match so "Despatch Advice" can teach a synonym without broad fuzzy risk.
    """
    needle = normalize_heading_for_learning(document_heading)
    if len(needle) < 4:
        return None

    async def _scan(rows: list[ClassificationLearningEvent]) -> str | None:
        counts: dict[str, int] = {}
        for row in rows:
            human = normalize_learning_dt_code(row.human_confirmed_dt)
            if not human:
                continue
            if valid_dt_codes is not None and human not in valid_dt_codes:
                continue
            stored = normalize_heading_for_learning(_heading_from_learning_row(row))
            if not stored or stored != needle:
                continue
            counts[human] = counts.get(human, 0) + 1
        if not counts:
            return None
        # Prefer most frequent; ties break by first seen (recent-first scan order).
        return max(counts.items(), key=lambda item: item[1])[0]

    vendor_token = (vendor_key or "").strip().lower()
    if vendor_token:
        vendor_stmt = (
            select(ClassificationLearningEvent)
            .where(
                ClassificationLearningEvent.tenant_id == tenant_id,
                ClassificationLearningEvent.vendor_key == vendor_token,
            )
            .order_by(ClassificationLearningEvent.created_at.desc())
            .limit(limit_scan)
        )
        vendor_hit = await _scan(list((await session.execute(vendor_stmt)).scalars().all()))
        if vendor_hit:
            return vendor_hit, 0.96

    stmt = (
        select(ClassificationLearningEvent)
        .where(ClassificationLearningEvent.tenant_id == tenant_id)
        .order_by(ClassificationLearningEvent.created_at.desc())
        .limit(limit_scan)
    )
    hit = await _scan(list((await session.execute(stmt)).scalars().all()))
    if hit:
        return hit, 0.93
    return None


async def few_shot_examples_for_tenant(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    limit: int = 5,
    valid_dt_codes: set[str] | None = None,
    vendor_key: str | None = None,
    vendor_limit: int = 3,
) -> list[dict[str, str]]:
    """Few-shot snippets; vendor-specific templates are preferred when vendor_key is known."""
    examples: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()

    async def _collect(rows: list[ClassificationLearningEvent]) -> None:
        for row in rows:
            if len(examples) >= limit:
                return
            if not row.human_confirmed_dt:
                continue

            heading = ""
            excerpt = ""
            if isinstance(row.llm_response, dict):
                heading = str(row.llm_response.get("document_heading") or "").strip()
                excerpt = str(row.llm_response.get("text_excerpt") or "").strip()

            if row.ocr_artifact_id and not excerpt:
                ocr = await session.get(InvoiceOcrArtifact, row.ocr_artifact_id)
                if ocr and ocr.text_excerpt:
                    excerpt = ocr.text_excerpt.strip()
                    if not heading:
                        heading = _heading_from_text(excerpt)

            human = normalize_learning_dt_code(row.human_confirmed_dt)
            if valid_dt_codes is not None and human not in valid_dt_codes:
                continue
            llm = (row.llm_suggested_dt or "").strip().upper()
            dedupe_key = (human, llm, excerpt[:120])
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            examples.append(_learning_row_to_example(row, excerpt=excerpt, heading=heading))

    vendor_token = (vendor_key or "").strip().lower()
    if vendor_token and vendor_limit > 0:
        vendor_stmt = (
            select(ClassificationLearningEvent)
            .where(
                ClassificationLearningEvent.tenant_id == tenant_id,
                ClassificationLearningEvent.vendor_key == vendor_token,
            )
            .order_by(ClassificationLearningEvent.created_at.desc())
            .limit(max(vendor_limit * 3, vendor_limit))
        )
        vendor_rows = (await session.execute(vendor_stmt)).scalars().all()
        await _collect(list(vendor_rows))
        if len(examples) >= limit:
            return examples[:limit]

    remaining = limit - len(examples)
    if remaining <= 0:
        return examples

    stmt = (
        select(ClassificationLearningEvent)
        .where(ClassificationLearningEvent.tenant_id == tenant_id)
        .order_by(ClassificationLearningEvent.created_at.desc())
        .limit(max(remaining * 3, remaining))
    )
    rows = (await session.execute(stmt)).scalars().all()
    await _collect(list(rows))
    return examples[:limit]


async def human_confirmed_document_type(
    session: AsyncSession,
    *,
    invoice_id: int,
) -> str | None:
    """Latest reviewer-confirmed DT for this invoice (classification/resolve)."""
    stmt = (
        select(AuditLog)
        .where(
            AuditLog.invoice_id == invoice_id,
            AuditLog.event == "classification_resolved",
        )
        .order_by(AuditLog.created_at.desc())
        .limit(1)
    )
    row = (await session.execute(stmt)).scalar_one_or_none()
    if row is None or not isinstance(row.detail, dict):
        return None
    code = str(row.detail.get("confirmed_dt") or "").strip().upper()
    return code or None
