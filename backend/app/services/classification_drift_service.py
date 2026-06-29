"""Vendor-level classification confidence drift detection."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import Invoice, InvoiceStatus
from app.schemas.classification_decision import ReviewReason
from app.schemas.llm_document import LlmDocumentResult
from app.schemas.rule_book_config import AiClassificationConfig


@dataclass
class VendorDriftResult:
    detected: bool
    vendor_key: str = ""
    current_confidence: float = 0.0
    baseline_mean: float | None = None
    sample_count: int = 0
    confidence_drop: float = 0.0
    review_reasons: list[str] = field(default_factory=list)


def drift_audit_detail(result: VendorDriftResult) -> dict[str, object]:
    return {
        "gate": "vendor_classification_drift",
        "vendor_key": result.vendor_key,
        "current_confidence": round(result.current_confidence, 4),
        "baseline_mean": round(result.baseline_mean, 4) if result.baseline_mean is not None else None,
        "sample_count": result.sample_count,
        "confidence_drop": round(result.confidence_drop, 4),
        "review_reasons": result.review_reasons,
        "alert": result.detected,
    }


async def vendor_classification_baseline(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    vendor_key: str,
    exclude_invoice_id: int | None = None,
) -> tuple[float | None, int]:
    """Rolling mean LLM confidence for prior invoices from the same vendor."""
    token = vendor_key.strip().lower()
    if not token:
        return None, 0

    stmt = (
        select(func.avg(Invoice.llm_confidence), func.count(Invoice.id))
        .where(
            Invoice.tenant_id == tenant_id,
            Invoice.storage_vendor_slug == token,
            Invoice.llm_confidence.isnot(None),
            Invoice.status.notin_(
                [InvoiceStatus.REJECTED, InvoiceStatus.DUPLICATE_SKIPPED]
            ),
        )
    )
    if exclude_invoice_id is not None:
        stmt = stmt.where(Invoice.id != exclude_invoice_id)

    row = (await session.execute(stmt)).one()
    mean_val, count_val = row[0], int(row[1] or 0)
    if count_val == 0 or mean_val is None:
        return None, 0
    return float(mean_val), count_val


def evaluate_vendor_classification_drift(
    *,
    vendor_key: str,
    current_confidence: float,
    baseline_mean: float | None,
    sample_count: int,
    ai_cfg: AiClassificationConfig,
) -> VendorDriftResult:
    """Alert when confidence drops materially below the vendor's historical average."""
    min_samples = ai_cfg.vendor_drift_min_samples
    drop_threshold = ai_cfg.vendor_drift_confidence_drop

    if not vendor_key.strip() or baseline_mean is None or sample_count < min_samples:
        return VendorDriftResult(
            detected=False,
            vendor_key=vendor_key,
            current_confidence=current_confidence,
            baseline_mean=baseline_mean,
            sample_count=sample_count,
        )

    drop = baseline_mean - current_confidence
    detected = drop >= drop_threshold
    reasons = [ReviewReason.VENDOR_CLASSIFICATION_DRIFT.value] if detected else []

    return VendorDriftResult(
        detected=detected,
        vendor_key=vendor_key,
        current_confidence=current_confidence,
        baseline_mean=baseline_mean,
        sample_count=sample_count,
        confidence_drop=drop,
        review_reasons=reasons,
    )


async def check_vendor_classification_drift(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    invoice_id: int,
    vendor_key: str | None,
    classify_llm: LlmDocumentResult | None,
    ai_cfg: AiClassificationConfig,
) -> VendorDriftResult | None:
    if not vendor_key or classify_llm is None:
        return None

    baseline_mean, sample_count = await vendor_classification_baseline(
        session,
        tenant_id=tenant_id,
        vendor_key=vendor_key,
        exclude_invoice_id=invoice_id,
    )
    return evaluate_vendor_classification_drift(
        vendor_key=vendor_key,
        current_confidence=classify_llm.confidence,
        baseline_mean=baseline_mean,
        sample_count=sample_count,
        ai_cfg=ai_cfg,
    )
