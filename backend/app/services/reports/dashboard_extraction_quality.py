"""Extraction Quality dashboard metrics.

Prefer real model confidence from:
1. Document Intelligence / OCR ``field_confidence`` on ``invoice_ocr_artifacts``
2. Understood-path vision: ``vision_header_confidence`` + optional per-field
   ``field_confidence`` on ``invoice.extracted_fields``

Fall back to completeness / validation heuristics only when model confidence
is missing for a field group.
"""

from __future__ import annotations

import json
from typing import Any, Iterable, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.classification_learning import InvoiceOcrArtifact
from app.models.invoice import Invoice
from app.services.extraction.field_extraction_confidence import (
    compute_extraction_field_confidence,
)
from app.services.invoice.invoice_evaluation_service import EVAL_AUTO_CODED
from app.services.invoice.invoice_response_service import _extracted_fields_if_loaded

HEADER_FIELDS: tuple[str, ...] = (
    "vendor",
    "invoice_no",
    "invoice_date",
    "due_date",
    "currency",
    "po_reference",
)
TAX_FIELDS: tuple[str, ...] = ("gst", "subtotal", "total")
LINE_FIELDS: tuple[str, ...] = ("line_items",)
GL_FIELDS: tuple[str, ...] = ("account_code", "account_name")

# Vision header extract fills these commercial fields — overall vision confidence
# applies to these groups when per-field vision scores are absent.
_VISION_HEADER_APPLIES: frozenset[str] = frozenset(
    {
        "vendor",
        "invoice_no",
        "invoice_date",
        "due_date",
        "currency",
        "po_reference",
        "gst",
        "subtotal",
        "total",
        "line_items",
    }
)

METRIC_ORDER: tuple[str, ...] = ("Header", "Line items", "Tax/GST", "GL coding")

# DI / layout payloads sometimes use alternate keys for the same concept.
_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "vendor": ("vendor", "vendor_name", "counterparty_name"),
    "invoice_no": ("invoice_no", "document_number", "invoice_id"),
    "invoice_date": ("invoice_date", "document_date"),
    "due_date": ("due_date",),
    "currency": ("currency", "currency_code"),
    "po_reference": ("po_reference", "purchase_order"),
    "gst": ("gst", "tax", "total_tax"),
    "subtotal": ("subtotal", "sub_total"),
    "total": ("total", "invoice_total", "amount_due"),
    "line_items": ("line_items",),
    "account_code": ("account_code", "gl_code"),
    "account_name": ("account_name", "gl_name"),
}


def normalize_confidence_pct(raw: Any) -> float | None:
    """Normalize model confidence to 0–100. Accepts 0–1 or 0–100 scales."""
    if raw is None:
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if value < 0:
        return None
    if value <= 1.0:
        return round(value * 100.0, 1)
    if value <= 100.0:
        return round(value, 1)
    return None


def _parse_confidence_map(raw: Any) -> dict[str, float]:
    if isinstance(raw, str) and raw.strip():
        try:
            raw = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return {}
    if not isinstance(raw, dict):
        return {}
    out: dict[str, float] = {}
    for key, value in raw.items():
        pct = normalize_confidence_pct(value)
        if pct is None:
            continue
        token = str(key or "").strip().lower()
        if token:
            out[token] = pct
    return out


def _di_confidence_map(payload: dict[str, Any] | None) -> dict[str, float]:
    if not isinstance(payload, dict):
        return {}
    return _parse_confidence_map(payload.get("field_confidence"))


def _line_item_confidences(payload: dict[str, Any] | None) -> list[float]:
    if not isinstance(payload, dict):
        return []
    raw = payload.get("di_line_item_confidences")
    if not isinstance(raw, list):
        return []
    out: list[float] = []
    for value in raw:
        pct = normalize_confidence_pct(value)
        if pct is not None:
            out.append(pct)
    return out


def _vision_signals(invoice: Invoice) -> tuple[dict[str, float], float | None]:
    """Per-field vision/LLM confidences + overall vision_header_confidence."""
    fields = _extracted_fields_if_loaded(invoice)
    per_field = _parse_confidence_map(fields.get("field_confidence"))
    overall = normalize_confidence_pct(fields.get("vision_header_confidence"))
    return per_field, overall


def _invoice_overall_confidence(invoice: Invoice) -> float | None:
    """Document-level AI confidence from classification / extraction (DI path)."""
    candidates: list[float] = []
    for raw in (
        getattr(invoice, "llm_confidence", None),
        getattr(invoice, "document_type_confidence", None),
        getattr(invoice, "vendor_confidence", None),
    ):
        pct = normalize_confidence_pct(raw)
        if pct is not None and pct > 0:
            candidates.append(pct)
    if not candidates:
        return None
    return max(candidates)


def _is_understood_path(invoice: Invoice) -> bool:
    fields = _extracted_fields_if_loaded(invoice)
    if fields.get("vision_header_confidence"):
        return True
    if str(fields.get("canonical_document_type") or "").strip():
        return True
    eval_status = (invoice.evaluation_status or "").strip()
    return eval_status.startswith("vision_")


def _lookup_conf(conf_map: dict[str, float], field: str) -> float | None:
    for alias in _FIELD_ALIASES.get(field, (field,)):
        if alias in conf_map:
            return conf_map[alias]
    return None


def _mean(values: Sequence[float]) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values), 1)


def _gl_quality_score(invoice: Invoice, heuristic: dict[str, float]) -> float:
    """GL is mapping quality — not OCR. Down-rank empty / suspense defaults."""
    code = (invoice.account_code or "").strip()
    name = (invoice.account_name or "").strip().lower()
    auto = (invoice.evaluation_status or "").strip() == EVAL_AUTO_CODED
    if not code:
        vals = [heuristic[f] for f in GL_FIELDS if f in heuristic]
        return _mean(vals) or 0.0

    suspense = (
        code in {"9999", "0000", "99999"}
        or "suspense" in name
        or "uncategor" in name
        or "unallocated" in name
    )
    if suspense:
        return 28.0 if auto else 18.0

    has_name = bool(name)
    if has_name and auto:
        return 96.0
    if has_name:
        return 90.0
    if auto:
        return 88.0
    return 82.0


def _has_model_confidence(
    invoice: Invoice,
    *,
    ocr_payload: dict[str, Any] | None,
) -> bool:
    """True when DI, vision, or document-level AI confidence is available."""
    if _di_confidence_map(ocr_payload) or _line_item_confidences(ocr_payload):
        return True
    vision_map, vision_overall = _vision_signals(invoice)
    if vision_map or vision_overall is not None:
        return True
    if _invoice_overall_confidence(invoice) is not None:
        return True
    return False


def _field_model_score(
    field: str,
    *,
    di_map: dict[str, float],
    vision_map: dict[str, float],
    vision_overall: float | None,
    invoice_overall: float | None,
    heuristic: dict[str, float],
) -> float | None:
    """Resolve one field: DI → vision per-field → doc-level AI → heuristic."""
    di = _lookup_conf(di_map, field)
    if di is not None:
        return di
    vision = _lookup_conf(vision_map, field)
    if vision is not None:
        return vision
    if vision_overall is not None and field in _VISION_HEADER_APPLIES:
        return vision_overall
    if invoice_overall is not None and field in _VISION_HEADER_APPLIES:
        return invoice_overall
    if field in heuristic:
        return float(heuristic[field])
    return None


def score_invoice_metrics(
    invoice: Invoice,
    *,
    ocr_payload: dict[str, Any] | None,
) -> dict[str, float]:
    """Return Header / Line items / Tax/GST / GL coding scores (0–100) for one invoice."""
    di_map = _di_confidence_map(ocr_payload)
    line_confs = _line_item_confidences(ocr_payload)
    vision_map, vision_overall = _vision_signals(invoice)
    invoice_overall = _invoice_overall_confidence(invoice)
    heuristic = compute_extraction_field_confidence(invoice)

    def group_score(fields: tuple[str, ...]) -> float:
        vals: list[float] = []
        for field in fields:
            score = _field_model_score(
                field,
                di_map=di_map,
                vision_map=vision_map,
                vision_overall=vision_overall,
                invoice_overall=invoice_overall,
                heuristic=heuristic,
            )
            if score is not None:
                vals.append(score)
        return _mean(vals) or 0.0

    line_score: float
    if line_confs:
        line_score = _mean(line_confs) or 0.0
    else:
        line_di = _lookup_conf(di_map, "line_items")
        line_vision = _lookup_conf(vision_map, "line_items")
        if line_di is not None:
            line_score = line_di
        elif line_vision is not None:
            line_score = line_vision
        elif vision_overall is not None and (
            _is_understood_path(invoice) or bool(getattr(invoice, "line_items", None))
        ):
            line_score = round(vision_overall * 0.85, 1)
        elif invoice_overall is not None:
            line_score = round(invoice_overall * 0.85, 1)
        else:
            line_score = group_score(LINE_FIELDS)

    return {
        "Header": group_score(HEADER_FIELDS),
        "Line items": line_score,
        "Tax/GST": group_score(TAX_FIELDS),
        "GL coding": _gl_quality_score(invoice, heuristic),
    }


async def load_latest_ocr_payloads(
    db: AsyncSession,
    *,
    tenant_id: Any,
    invoice_ids: Iterable[int],
) -> dict[int, dict[str, Any]]:
    """Map invoice_id → latest OCR artifact payload_json."""
    ids = [int(i) for i in invoice_ids if i]
    if not ids:
        return {}
    rows = (
        await db.execute(
            select(InvoiceOcrArtifact)
            .where(
                InvoiceOcrArtifact.tenant_id == tenant_id,
                InvoiceOcrArtifact.invoice_id.in_(ids),
            )
            .order_by(
                InvoiceOcrArtifact.invoice_id.asc(),
                InvoiceOcrArtifact.created_at.desc(),
            )
        )
    ).scalars().all()
    out: dict[int, dict[str, Any]] = {}
    for row in rows:
        iid = int(row.invoice_id)
        if iid in out:
            continue
        payload = row.payload_json if isinstance(row.payload_json, dict) else {}
        out[iid] = payload
    return out


def aggregate_extraction_quality(
    invoices: Sequence[Invoice],
    ocr_by_invoice: dict[int, dict[str, Any]],
) -> list[tuple[str, float]]:
    """Aggregate per-metric means across invoices with model confidence.

    Invoices lacking DI / vision confidence are excluded so the chart does not
    look like a fake heuristic curve. Always returns METRIC_ORDER (zeros when
    no model-backed sample).
    """
    buckets: dict[str, list[float]] = {m: [] for m in METRIC_ORDER}
    for inv in invoices:
        payload = ocr_by_invoice.get(int(inv.id))
        if not _has_model_confidence(inv, ocr_payload=payload):
            continue
        scores = score_invoice_metrics(inv, ocr_payload=payload)
        for metric in METRIC_ORDER:
            buckets[metric].append(float(scores.get(metric, 0.0)))
    return [
        (metric, _mean(vals) if vals else 0.0)
        for metric, vals in ((m, buckets[m]) for m in METRIC_ORDER)
    ]
