"""Named pipeline phases: Storage → OCR → LLM classify → Confidence gate."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.invoice import Invoice
from app.schemas.classification_decision import ReviewReason
from app.schemas.document_type import DocumentTypeDefinition
from app.schemas.llm_document import LlmDocumentResult
from app.schemas.ocr_artifact import OcrArtifact
from app.schemas.rule_book_config import AiClassificationConfig
from app.services.audit.audit_service import log_event
from app.services.classification.classification_learning_service import load_cached_ocr, store_ocr_artifact
from app.services.extraction.di_extract_service import OcrFailed
from app.services.extraction.document_ai_provider import (
    DocumentAiProvider,
    classify_only,
    provider_available,
    provider_unavailable_reason,
    read_for_classification,
)
from app.services.classification.document_type_playbook_service import confidence_gate_fields
from app.services.dossier.document_ref_service import audit_document_detail
from app.services.invoice.invoice_data import InvoiceData
from app.services.classification.document_type_catalog import (
    get_document_type_definition,
    min_route_confidence_for_document_type,
)
from app.services.classification.document_type_rule_engine import (
    classifier_rules_match_ocr,
    is_user_defined_document_type,
)
from app.services.shared.file_storage import open_pdf_for_reading, repair_invoice_stored_path, stored_file_available
from app.services.tenant.tenant_org_context import OrgContext
from app.utils.logger import get_logger

logger = get_logger(__name__)


def persist_llm_party_context(
    invoice: Invoice,
    llm: LlmDocumentResult,
    org: OrgContext,
) -> None:
    """Store inferred purchase/sales perspective and party names for routing."""
    from app.services.extraction.extraction_field_values import merge_invoice_extracted_fields
    from app.services.extraction.party_field_service import apply_party_normalization_to_llm

    ocr_text = getattr(invoice, "document_text", None) or ""
    _parties, perspective, _finance, party_fields = apply_party_normalization_to_llm(
        llm,
        ocr_text=ocr_text or None,
        org=org,
    )
    merge_invoice_extracted_fields(
        invoice,
        {
            "perspective": perspective,
            "llm_perspective": llm.perspective or "",
            **party_fields,
        },
    )


@dataclass
class GatePhaseResult:
    passed: bool
    confirmed_dt: str = ""
    confirmed_confidence: float = 0.0
    review_reasons: list[str] = field(default_factory=list)
    llm_suggested_dt: str | None = None
    llm_confidence: float | None = None
    llm_reasoning: str | None = None
    min_route_confidence: float = 0.0
    org_auto_route_min_confidence: float = 0.0
    dt_min_route_confidence: float = 0.0


@dataclass
class ImageQualityGateResult:
    passed: bool
    review_reasons: list[str] = field(default_factory=list)
    text_length: int = 0
    sparse: bool = False
    min_text_chars: int = 0


@dataclass
class FieldConfidenceGateResult:
    passed: bool
    low_confidence_fields: dict[str, float] = field(default_factory=dict)
    min_confidence: float = 0.0
    review_reasons: list[str] = field(default_factory=list)
    gate_fields: list[str] = field(default_factory=list)
    confirmed_dt: str = ""
    skipped_fields_present_after_merge: list[str] = field(default_factory=list)
    missing_gate_fields: list[str] = field(default_factory=list)


async def phase_storage_verify(
    session: AsyncSession,
    invoice: Invoice,
    *,
    document_ai_provider: str,
) -> None:
    """Verify persisted file is readable before OCR."""
    await repair_invoice_stored_path(session, invoice)
    if not stored_file_available(invoice.raw_file_path, tenant_id=invoice.tenant_id):
        raise OcrFailed("stored_file_missing")

    await log_event(
        session,
        "storage_verified",
        invoice_id=invoice.id,
        detail=audit_document_detail(
            invoice,
            path=invoice.raw_file_path,
            document_ai_provider=document_ai_provider,
        ),
    )


async def phase_file_validity(
    session: AsyncSession,
    invoice: Invoice,
    *,
    document_ai_provider: str,
) -> None:
    """Reject corrupt/unsupported files before OCR/DI."""
    from app.services.invoice.file_validity_gate import (
        evaluate_file_validity,
        file_validity_audit_detail,
    )

    with open_pdf_for_reading(invoice.raw_file_path, tenant_id=invoice.tenant_id) as path:
        result = evaluate_file_validity(path)
    await log_event(
        session,
        "file_validity_passed" if result.passed else "file_validity_failed",
        invoice_id=invoice.id,
        detail={
            **file_validity_audit_detail(result),
            "document_ai_provider": document_ai_provider,
        },
    )
    if not result.passed:
        raise OcrFailed(result.rejection_code or "file_invalid")


async def phase_ocr(
    session: AsyncSession,
    invoice: Invoice,
    *,
    org: OrgContext,
    document_types: Sequence[DocumentTypeDefinition],
    doc_provider: DocumentAiProvider,
    provider_token: str,
    human_locked_dt: str | None,
) -> OcrArtifact:
    """OCR / layout read only — no field extraction."""
    ocr: OcrArtifact | None = None
    if invoice.file_hash:
        ocr = await load_cached_ocr(
            session,
            tenant_id=invoice.tenant_id,
            invoice_id=invoice.id,
            file_hash=invoice.file_hash,
        )

    if ocr is None:
        with open_pdf_for_reading(invoice.raw_file_path, tenant_id=invoice.tenant_id) as path:
            if not provider_available(doc_provider) and not human_locked_dt:
                raise OcrFailed(provider_unavailable_reason(doc_provider))
            ocr = await read_for_classification(
                path,
                provider=doc_provider,
                org=org,
                document_types=document_types,
            )
        if invoice.file_hash:
            await store_ocr_artifact(
                session,
                tenant_id=invoice.tenant_id,
                invoice_id=invoice.id,
                file_hash=invoice.file_hash,
                ocr=ocr,
            )

    await log_event(
        session,
        "ocr_completed",
        invoice_id=invoice.id,
        detail={
            "source": provider_token,
            "confidence": "high" if not ocr.sparse else "low",
            "text_length": ocr.text_length,
            "di_model": ocr.di_model,
            "document_ai_provider": provider_token,
            "sparse": ocr.sparse,
        },
    )
    return ocr


def evaluate_image_quality_gate(
    ocr: OcrArtifact,
    *,
    ai_cfg: AiClassificationConfig,
) -> ImageQualityGateResult:
    """Block classify when OCR/image quality is too poor (skewed photos, unreadable scans)."""
    settings = get_settings()
    min_chars = ai_cfg.ocr_quality_min_text_chars
    if min_chars is None:
        min_chars = settings.ocr_min_text_chars

    reasons: list[str] = []
    if ai_cfg.block_sparse_ocr and ocr.sparse:
        reasons.append(ReviewReason.OCR_SPARSE.value)
    if ocr.text_length < min_chars:
        reasons.append(ReviewReason.IMAGE_QUALITY_LOW.value)

    quality_hint = str((ocr.payload_json or {}).get("image_quality") or "").strip().lower()
    if quality_hint in {"low", "poor", "unreadable"}:
        reasons.append(ReviewReason.IMAGE_QUALITY_LOW.value)

    # De-dupe while preserving order
    seen: set[str] = set()
    deduped = [r for r in reasons if not (r in seen or seen.add(r))]

    return ImageQualityGateResult(
        passed=not deduped,
        review_reasons=deduped,
        text_length=ocr.text_length,
        sparse=ocr.sparse,
        min_text_chars=min_chars,
    )


def image_quality_audit_detail(
    result: ImageQualityGateResult,
    *,
    provider_token: str,
) -> dict[str, object]:
    return {
        "gate": "image_quality",
        "compare_passed": result.passed,
        "review_reasons": result.review_reasons,
        "text_length": result.text_length,
        "sparse": result.sparse,
        "min_text_chars": result.min_text_chars,
        "document_ai_provider": provider_token,
        "resubmit_hint": "Please resend a flat, well-lit scan or PDF — avoid angled phone photos.",
    }


async def phase_llm_classify(
    session: AsyncSession,
    invoice: Invoice,
    *,
    ocr: OcrArtifact,
    org: OrgContext,
    document_types: Sequence[DocumentTypeDefinition],
    few_shots: Sequence[dict[str, str]],
    doc_provider: DocumentAiProvider,
    provider_token: str,
    file_path: str | Path,
) -> LlmDocumentResult | None:
    """LLM document-type classification with org prompt + few-shots."""
    settings = get_settings()
    result = await classify_only(
        ocr,
        file_path=file_path,
        org=org,
        document_types=document_types,
        few_shots=few_shots,
        provider=doc_provider,
    )

    if result is not None:
        invoice.llm_suggested_dt = result.suggested_dt or None
        invoice.llm_confidence = round(result.confidence, 4)

    await log_event(
        session,
        "llm_classified",
        invoice_id=invoice.id,
        detail={
            "llm_suggested_dt": result.suggested_dt if result else None,
            "llm_confidence": result.confidence if result else None,
            "llm_reasoning": result.reasoning if result else None,
            "document_ai_provider": provider_token,
            "prompt_version": settings.llm_classification_prompt_version,
        },
    )
    return result


def reconcile_llm_dt_with_heading(
    llm: LlmDocumentResult | None,
    *,
    invoice: Invoice,
    ocr: OcrArtifact,
    document_types: Sequence[DocumentTypeDefinition],
    ai_cfg: AiClassificationConfig,
) -> tuple[LlmDocumentResult | None, dict[str, object] | None]:
    """Adopt a heading-aligned DT when LLM omits or contradicts OCR document title."""
    from app.services.classification.segment_heading_classification import (
        classify_from_segment_heading,
        heading_conflicts_with_definition,
        resolve_segment_heading_kind,
    )

    document_text = ocr.text or ""
    heading_text = (llm.document_heading if llm is not None else "") or ""
    heading_kind = resolve_segment_heading_kind(
        document_text=f"{heading_text}\n{document_text}".strip(),
    )
    if heading_kind is None:
        return llm, None

    parsed = InvoiceData(
        document_text=document_text,
        document_heading=heading_text.strip(),
    )
    heading_match = classify_from_segment_heading(
        heading_kind=heading_kind,
        document_types=document_types,
        invoice=invoice,
        parsed=parsed,
    )
    if heading_match is None or heading_match.needs_review:
        return llm, None

    adopted_code = (heading_match.code or "").strip().upper()
    if not adopted_code:
        return llm, None

    route_min = max(
        ai_cfg.auto_route_min_confidence,
        min_route_confidence_for_document_type(adopted_code, document_types),
    )
    if heading_match.confidence < route_min:
        return llm, None

    previous_dt = (llm.suggested_dt if llm is not None else "") or ""
    previous_dt = previous_dt.strip().upper()
    adopt_reason: str | None = None

    if not previous_dt:
        adopt_reason = "empty_llm_suggested_dt"
    else:
        llm_defn = get_document_type_definition(previous_dt, document_types=document_types)
        if llm_defn is not None and heading_conflicts_with_definition(heading_kind, llm_defn):
            adopt_reason = "heading_conflicts_with_llm_dt"
        elif previous_dt != adopted_code:
            heading_defn = get_document_type_definition(adopted_code, document_types=document_types)
            if heading_defn is not None:
                from app.services.classification.segment_heading_classification import (
                    score_document_type_for_heading,
                )

                llm_score = (
                    score_document_type_for_heading(llm_defn, heading_kind) if llm_defn else 0.0
                )
                heading_score = score_document_type_for_heading(heading_defn, heading_kind)
                if heading_score >= 0.82 and heading_score > llm_score:
                    adopt_reason = "heading_stronger_than_llm_dt"

    if adopt_reason is None:
        return llm, None

    base = llm if llm is not None else LlmDocumentResult(
        suggested_dt="",
        confidence=0.0,
        reasoning="",
        perspective="purchase",
    )
    updated = base.model_copy(
        update={
            "suggested_dt": adopted_code,
            "confidence": max(float(base.confidence or 0.0), float(heading_match.confidence)),
            "reasoning": (heading_match.reason or base.reasoning or "").strip(),
            "document_heading": (base.document_heading or heading_text or "").strip(),
        }
    )
    return updated, {
        "heading_kind": heading_kind,
        "previous_dt": previous_dt or None,
        "adopted_dt": adopted_code,
        "heading_confidence": round(float(heading_match.confidence), 4),
        "reason": adopt_reason,
    }


def backfill_llm_dt_from_policy(
    llm: LlmDocumentResult | None,
    *,
    invoice: Invoice,
    ocr: OcrArtifact,
    document_types: Sequence[DocumentTypeDefinition],
    ai_cfg: AiClassificationConfig,
) -> tuple[LlmDocumentResult | None, dict[str, object] | None]:
    """When LLM omits suggested_dt (or is unavailable), adopt a confident Rule Book classifier winner."""
    if llm is not None and (llm.suggested_dt or "").strip():
        return llm, None

    from app.services.classification.document_type_classifier import rank_document_type_candidates

    parsed = InvoiceData(
        document_text=ocr.text or "",
        document_heading=(llm.document_heading if llm is not None else "").strip(),
    )
    candidates = rank_document_type_candidates(
        document_types=document_types,
        invoice=invoice,
        parsed=parsed,
        limit=1,
    )
    if not candidates:
        return llm, None

    winner = candidates[0]
    code = (winner.code or "").strip().upper()
    if not code or winner.needs_review:
        return llm, None

    route_min = max(
        ai_cfg.auto_route_min_confidence,
        min_route_confidence_for_document_type(code, document_types),
    )
    if winner.confidence < route_min:
        return llm, None

    base = llm if llm is not None else LlmDocumentResult(
        suggested_dt="",
        confidence=0.0,
        reasoning="",
        perspective="purchase",
    )
    updated = base.model_copy(
        update={
            "suggested_dt": code,
            "confidence": max(float(base.confidence or 0.0), float(winner.confidence)),
            "reasoning": (base.reasoning or winner.reason or "").strip(),
        }
    )
    return updated, {
        "policy_winner_dt": code,
        "policy_confidence": round(float(winner.confidence), 4),
        "llm_confidence_before": round(float(base.confidence or 0.0), 4),
        "policy_reason": winner.reason,
        "llm_unavailable": llm is None,
    }


def evaluate_confidence_gate(
    llm: LlmDocumentResult | None,
    *,
    document_types: Sequence[DocumentTypeDefinition],
    ai_cfg: AiClassificationConfig,
    provider_token: str,
) -> GatePhaseResult:
    """LLM confidence + catalogue gate (no policy scorer at pre-extract)."""
    settings = get_settings()
    org_route_min = ai_cfg.auto_route_min_confidence
    reasons: list[str] = []

    if llm is None:
        reasons.append(ReviewReason.LLM_INVALID.value)
        return GatePhaseResult(
            passed=False,
            review_reasons=reasons,
            llm_suggested_dt=None,
            llm_confidence=None,
            min_route_confidence=org_route_min,
            org_auto_route_min_confidence=org_route_min,
            dt_min_route_confidence=org_route_min,
        )

    suggested = (llm.suggested_dt or "").strip().upper()
    dt_route_min = (
        min_route_confidence_for_document_type(suggested, document_types)
        if suggested
        else org_route_min
    )
    route_min = max(org_route_min, dt_route_min)

    if not suggested:
        reasons.append(ReviewReason.DT_NOT_IN_CATALOGUE.value)
    else:
        defn = get_document_type_definition(suggested, document_types=document_types)
        if defn is None:
            reasons.append(ReviewReason.DT_NOT_IN_CATALOGUE.value)
        elif not defn.enabled:
            reasons.append(ReviewReason.DT_DISABLED.value)

    if llm.confidence < route_min:
        reasons.append(ReviewReason.LLM_LOW_CONF.value)

    passed = not reasons and bool(suggested)
    confirmed_conf = round(llm.confidence, 4) if passed else 0.0

    return GatePhaseResult(
        passed=passed,
        confirmed_dt=suggested if passed else "",
        confirmed_confidence=confirmed_conf,
        review_reasons=reasons,
        llm_suggested_dt=suggested or None,
        llm_confidence=round(llm.confidence, 4),
        llm_reasoning=llm.reasoning,
        min_route_confidence=route_min,
        org_auto_route_min_confidence=org_route_min,
        dt_min_route_confidence=dt_route_min,
    )


def apply_user_defined_classifier_gate(
    gate_result: GatePhaseResult,
    *,
    invoice: Invoice,
    ocr: OcrArtifact,
    document_types: Sequence[DocumentTypeDefinition],
) -> GatePhaseResult:
    """Fail auto-route when LLM picks a custom type whose match rules don't fit OCR."""
    if not gate_result.passed or not gate_result.confirmed_dt:
        return gate_result

    defn = get_document_type_definition(gate_result.confirmed_dt, document_types=document_types)
    if defn is None or not is_user_defined_document_type(defn):
        return gate_result

    if classifier_rules_match_ocr(defn, invoice=invoice, ocr=ocr):
        return gate_result

    reasons = list(gate_result.review_reasons)
    if ReviewReason.CLASSIFIER_RULE_MISMATCH.value not in reasons:
        reasons.append(ReviewReason.CLASSIFIER_RULE_MISMATCH.value)

    return GatePhaseResult(
        passed=False,
        confirmed_dt="",
        confirmed_confidence=0.0,
        review_reasons=reasons,
        llm_suggested_dt=gate_result.llm_suggested_dt,
        llm_confidence=gate_result.llm_confidence,
        llm_reasoning=gate_result.llm_reasoning,
        min_route_confidence=gate_result.min_route_confidence,
        org_auto_route_min_confidence=gate_result.org_auto_route_min_confidence,
        dt_min_route_confidence=gate_result.dt_min_route_confidence,
    )


def gate_audit_detail(result: GatePhaseResult, *, provider_token: str) -> dict[str, object]:
    settings = get_settings()
    return {
        "gate": "classification",
        "compare_passed": result.passed,
        "llm_suggested_dt": result.llm_suggested_dt,
        "llm_confidence": result.llm_confidence,
        "llm_reasoning": result.llm_reasoning,
        "confirmed_dt": result.confirmed_dt,
        "confirmed_confidence": result.confirmed_confidence,
        "review_reasons": result.review_reasons,
        "min_route_confidence": result.min_route_confidence,
        "org_auto_route_min_confidence": result.org_auto_route_min_confidence,
        "dt_min_route_confidence": result.dt_min_route_confidence,
        "document_ai_provider": provider_token,
        "prompt_version": settings.llm_classification_prompt_version,
    }


def _llm_field_has_value(key: str, llm: LlmDocumentResult) -> bool:
    token = key.strip().lower()
    if token == "vendor":
        return bool((llm.vendor or llm.seller.name or "").strip())
    if token == "total":
        return llm.total is not None
    if token == "subtotal":
        return llm.subtotal is not None
    if token == "invoice_no":
        return bool((llm.invoice_no or "").strip())
    if token == "gst":
        return llm.gst is not None
    if token == "abn":
        return bool((llm.abn or llm.seller.abn or "").strip())
    if token == "invoice_date":
        return bool((llm.invoice_date or "").strip())
    if token == "due_date":
        return bool((llm.due_date or "").strip())
    if token == "po_reference":
        return bool((llm.po_reference or "").strip())
    if token == "line_items":
        return bool(llm.line_items)
    if token == "document_heading":
        return bool((llm.document_heading or "").strip())
    raw = llm.raw or {}
    extracted = raw.get("extracted_fields")
    if isinstance(extracted, dict) and str(extracted.get(token) or "").strip():
        return True
    return bool(str(raw.get(token) or "").strip())


def evaluate_field_confidence_gate(
    llm: LlmDocumentResult | None,
    *,
    ai_cfg: AiClassificationConfig,
    dt_definition: DocumentTypeDefinition | None = None,
    parsed: InvoiceData | None = None,
    invoice: Invoice | None = None,
    confirmed_dt: str = "",
) -> FieldConfidenceGateResult:
    """Flag DT compulsory fields below per-field LLM confidence threshold."""
    from app.services.classification.document_type_field_checks import field_is_present
    from app.services.classification.document_type_rule_engine import build_document_classifier_context

    floor = ai_cfg.min_field_extract_confidence
    gate_fields = confidence_gate_fields(dt_definition)
    dt_code = (confirmed_dt or (dt_definition.code if dt_definition else "") or "").strip().upper()

    ctx = None
    if parsed is not None and invoice is not None:
        ctx = build_document_classifier_context(invoice=invoice, parsed=parsed)

    missing_gate_fields: list[str] = []
    if ctx is not None:
        for key in gate_fields:
            if not field_is_present(key, invoice=invoice, parsed=parsed, ctx=ctx):
                missing_gate_fields.append(key)

    if llm is None or not llm.field_confidence:
        return FieldConfidenceGateResult(
            passed=True,
            min_confidence=floor,
            gate_fields=gate_fields,
            confirmed_dt=dt_code,
            missing_gate_fields=missing_gate_fields,
            review_reasons=[],
            skipped_fields_present_after_merge=[
                key for key in gate_fields if key not in missing_gate_fields
            ],
        )

    low: dict[str, float] = {}
    skipped_after_merge: list[str] = []
    for key in gate_fields:
        conf = llm.field_confidence.get(key)
        if conf is None:
            continue
        if ctx is not None and field_is_present(key, invoice=invoice, parsed=parsed, ctx=ctx):
            if conf < floor and _llm_field_has_value(key, llm):
                skipped_after_merge.append(key)
            continue
        if _llm_field_has_value(key, llm) and conf < floor:
            low[key] = round(conf, 4)

    reasons: list[str] = []
    if low:
        reasons.append(ReviewReason.FIELD_CONFIDENCE_LOW.value)
    return FieldConfidenceGateResult(
        passed=not low,
        low_confidence_fields=low,
        min_confidence=floor,
        review_reasons=reasons,
        gate_fields=gate_fields,
        confirmed_dt=dt_code,
        skipped_fields_present_after_merge=skipped_after_merge,
        missing_gate_fields=missing_gate_fields,
    )


def evaluate_line_item_review_gate(
    parsed: InvoiceData | None,
    *,
    dt_definition: DocumentTypeDefinition | None = None,
    threshold: float | None = None,
) -> tuple[bool, float | None, list[str]]:
    """Return whether line-item confidence meets review threshold."""
    from app.services.classification.document_type_playbook_service import confidence_gate_fields
    from app.services.extraction.extraction_orchestrator import _doc_line_items_confidence
    from app.services.extraction.field_extraction_confidence import _score_line_items
    from app.services.extraction.line_item_parsing_config import DEFAULT_THRESHOLDS

    if parsed is None or not parsed.line_items:
        return True, None, []
    gate_fields = confidence_gate_fields(dt_definition)
    if "line_items" not in gate_fields:
        return True, None, []

    confidence = _doc_line_items_confidence(parsed)
    if confidence is None:
        confidence = _score_line_items(parsed) / 100.0

    floor = threshold if threshold is not None else DEFAULT_THRESHOLDS.line_item_review_confidence_threshold
    if confidence < floor:
        return False, confidence, ["line_item_confidence_low"]
    return True, confidence, []


def field_confidence_audit_detail(result: FieldConfidenceGateResult) -> dict[str, object]:
    return {
        "gate": "field_confidence",
        "compare_passed": result.passed,
        "low_confidence_fields": result.low_confidence_fields,
        "min_field_extract_confidence": result.min_confidence,
        "review_reasons": result.review_reasons,
        "confirmed_dt": result.confirmed_dt,
        "gate_fields": result.gate_fields,
        "skipped_fields_present_after_merge": result.skipped_fields_present_after_merge,
        "missing_gate_fields": result.missing_gate_fields,
    }
