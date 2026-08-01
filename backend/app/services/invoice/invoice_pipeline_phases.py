"""Named pipeline phases: Storage → File validity → Vision understand → Vision header extract → Image quality → Layout readiness → OCR → OCR quality confirm → LLM classify."""

from __future__ import annotations

import asyncio
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

    def _eval() -> object:
        with open_pdf_for_reading(invoice.raw_file_path, tenant_id=invoice.tenant_id) as path:
            return evaluate_file_validity(path)

    result = await asyncio.to_thread(_eval)
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


async def phase_vision_understand(
    session: AsyncSession,
    invoice: Invoice,
    *,
    doc_provider: DocumentAiProvider,
    document_ai_provider: str,
    vision_page_images: list[bytes] | None = None,
):
    """Vision LLM understandability gate — never raises for cannot_understand."""
    from app.services.invoice.vision_understand_gate import (
        evaluate_vision_understand,
        vision_understand_audit_detail,
    )

    with open_pdf_for_reading(invoice.raw_file_path, tenant_id=invoice.tenant_id) as path:
        result = await evaluate_vision_understand(
            path,
            provider=doc_provider,
            vision_page_images=vision_page_images,
        )
    await log_event(
        session,
        "vision_understand_passed" if result.can_understand else "vision_understand_failed",
        invoice_id=invoice.id,
        detail={
            **vision_understand_audit_detail(result),
            "document_ai_provider": document_ai_provider,
        },
    )
    return result


async def phase_vision_header_extract(
    session: AsyncSession,
    invoice: Invoice,
    *,
    org: OrgContext,
    doc_provider: DocumentAiProvider,
    document_ai_provider: str,
    vision_page_images: list[bytes] | None = None,
):
    """Vision header extract for can-understand path — never raises."""
    from dataclasses import replace

    from app.services.invoice.vision_header_extract import (
        evaluate_vision_header_extract,
        persist_vision_header_to_invoice,
        vision_header_extract_audit_detail,
        vision_header_should_review,
    )
    from app.services.invoice.vision_header_reconcile import (
        apply_vision_header_amount_consistency,
        apply_vision_header_text_reconcile,
        enrich_vision_header_refs_from_text,
        ground_vision_header_result,
        resolve_header_grounding_text,
    )

    async def _persist_lines(result_obj) -> None:
        # Lazy import avoids circular import with pipeline → phases.
        from app.services.invoice.pipeline import _replace_line_items

        await _replace_line_items(
            session,
            invoice,
            list(result_obj.line_items or ()),
        )

    with open_pdf_for_reading(invoice.raw_file_path, tenant_id=invoice.tenant_id) as path:
        from app.models.tenant import Tenant
        from app.tenant_settings import tenant_date_order

        tenant_row = await session.get(Tenant, invoice.tenant_id)
        date_order = tenant_date_order(tenant_row)
        result = await evaluate_vision_header_extract(
            path,
            provider=doc_provider,
            org=org,
            vision_page_images=vision_page_images,
            date_order=date_order,
        )
        reconcile_detail: dict[str, object] = {}
        grounding_detail: dict[str, object] = {}
        enrich_detail: dict[str, object] = {}
        consistency_detail: dict[str, object] = {}
        if result.success:
            try:
                text, text_source_detail = await asyncio.to_thread(
                    resolve_header_grounding_text,
                    path,
                )
                result, grounding_detail = ground_vision_header_result(
                    result, text, date_order=date_order
                )
                grounding_detail = {**grounding_detail, "text_source": text_source_detail}
                result, enrich_detail = enrich_vision_header_refs_from_text(
                    result, text, date_order=date_order
                )
                result, consistency_detail = apply_vision_header_amount_consistency(result)
                persist_vision_header_to_invoice(invoice, result)
                await _persist_lines(result)
                # Text grounding — fix ₹→INR / S$→SGD, clear bare-$, upgrade totals.
                reconcile_detail = apply_vision_header_text_reconcile(invoice, text)
                reconcile_detail = {
                    **reconcile_detail,
                    "text_source": text_source_detail,
                    "amount_consistency": consistency_detail,
                }
                # Safety net: only fill from Invoice/INV labels — never Permit/Doc No.
                if not (invoice.invoice_no or "").strip():
                    from app.services.extraction.invoice_no_sanitizer import (
                        extract_commercial_invoice_no_from_text,
                        sanitize_invoice_no_parts,
                    )

                    recovered = extract_commercial_invoice_no_from_text(text or "")
                    primary, _sec = sanitize_invoice_no_parts(recovered)
                    if primary:
                        invoice.invoice_no = primary
                        enrich_detail = dict(enrich_detail or {})
                        enrich_detail["filled"] = list(enrich_detail.get("filled") or []) + [
                            "invoice_no_post_persist"
                        ]
            except Exception as exc:
                persist_vision_header_to_invoice(invoice, result)
                try:
                    await _persist_lines(result)
                except Exception:
                    pass
                reconcile_detail = {
                    "currency_reason": "text_reconcile_failed",
                    "error": str(exc),
                }
                grounding_detail = {"skipped": True, "reason": "text_extract_failed"}

            if vision_header_should_review(
                result,
                grounding_cleared=list(grounding_detail.get("cleared") or []),
            ):
                result = replace(result, needs_review=True)
    if result.success:
        await log_event(
            session,
            "vision_header_extracted",
            invoice_id=invoice.id,
            detail={
                **vision_header_extract_audit_detail(result),
                "document_ai_provider": document_ai_provider,
                "text_reconcile": reconcile_detail,
                "text_grounding": grounding_detail,
                "text_enrich": enrich_detail,
                "persisted_invoice_no": invoice.invoice_no,
                "persisted_currency": invoice.currency,
                "persisted_subtotal": str(invoice.subtotal)
                if invoice.subtotal is not None
                else None,
                "persisted_gst": str(invoice.gst) if invoice.gst is not None else None,
                "persisted_abn": invoice.abn,
                "persisted_line_item_count": len(result.line_items or ()),
            },
        )
    else:
        await log_event(
            session,
            "vision_header_extract_failed",
            invoice_id=invoice.id,
            detail={
                **vision_header_extract_audit_detail(result),
                "document_ai_provider": document_ai_provider,
            },
        )
    return result


async def phase_vision_type_suggest(
    session: AsyncSession,
    invoice: Invoice,
    *,
    org: OrgContext,
    doc_provider: DocumentAiProvider,
    document_ai_provider: str,
    vision_page_images: list[bytes] | None = None,
):
    """Lean type suggest for can-understand path — never raises."""
    from app.services.invoice.vision_type_suggest import (
        evaluate_vision_type_suggest,
        persist_vision_type_suggest_to_invoice,
        vision_type_suggest_audit_detail,
    )

    with open_pdf_for_reading(invoice.raw_file_path, tenant_id=invoice.tenant_id) as path:
        result = await evaluate_vision_type_suggest(
            path,
            provider=doc_provider,
            org=org,
            vision_page_images=vision_page_images,
        )
    if result.success:
        persist_vision_type_suggest_to_invoice(invoice, result)
        await log_event(
            session,
            "vision_type_suggested",
            invoice_id=invoice.id,
            detail={
                **vision_type_suggest_audit_detail(result),
                "document_ai_provider": document_ai_provider,
                "persisted_document_heading": invoice.document_heading,
            },
        )
    else:
        await log_event(
            session,
            "vision_type_suggest_failed",
            invoice_id=invoice.id,
            detail={
                **vision_type_suggest_audit_detail(result),
                "document_ai_provider": document_ai_provider,
            },
        )
    return result


async def phase_vision_dt_extract(
    session: AsyncSession,
    invoice: Invoice,
    *,
    org: OrgContext,
    document_types: Sequence[DocumentTypeDefinition],
    confirmed_dt: str,
    doc_provider: DocumentAiProvider,
    document_ai_provider: str,
    vision_page_images: list[bytes] | None = None,
    few_shots: Sequence | None = None,
    definition: DocumentTypeDefinition | None = None,
):
    """DT-scoped field extract after org DT map — never raises."""
    from app.services.invoice.vision_dt_extract import (
        evaluate_vision_dt_extract,
        vision_dt_extract_audit_detail,
    )

    result = await evaluate_vision_dt_extract(
        session,
        invoice,
        org=org,
        document_types=list(document_types),
        confirmed_dt=confirmed_dt,
        doc_provider=doc_provider,
        vision_page_images=vision_page_images,
        few_shots=list(few_shots or []),
        definition=definition,
    )
    event = (
        "vision_dt_fields_extracted" if result.success else "vision_dt_fields_extract_failed"
    )
    await log_event(
        session,
        event,
        invoice_id=invoice.id,
        detail={
            **vision_dt_extract_audit_detail(result),
            "document_ai_provider": document_ai_provider,
            "document_type_code": (confirmed_dt or "").strip().upper(),
            "persisted_vendor": invoice.vendor,
            "persisted_total": str(invoice.total) if invoice.total is not None else None,
            "persisted_invoice_no": invoice.invoice_no,
        },
    )
    return result


async def phase_image_quality(
    session: AsyncSession,
    invoice: Invoice,
    *,
    document_ai_provider: str,
    vision_page_images: list[bytes] | None = None,
) -> None:
    """Pre-OCR visual fitness — severe rejects; warn continues with audit."""
    from app.services.invoice.image_quality_gate import (
        evaluate_pre_ocr_image_quality,
        image_quality_pre_ocr_audit_detail,
    )

    def _eval() -> object:
        with open_pdf_for_reading(invoice.raw_file_path, tenant_id=invoice.tenant_id) as path:
            return evaluate_pre_ocr_image_quality(path, vision_page_images=vision_page_images)

    result = await asyncio.to_thread(_eval)
    await log_event(
        session,
        "image_quality_passed" if result.passed else "image_quality_failed",
        invoice_id=invoice.id,
        detail={
            **image_quality_pre_ocr_audit_detail(result),
            "document_ai_provider": document_ai_provider,
        },
    )
    if not result.passed:
        raise OcrFailed("image_quality_severe")


async def phase_layout_readiness(
    session: AsyncSession,
    invoice: Invoice,
    *,
    document_ai_provider: str,
):
    """Pre-OCR parser routing — never hard-rejects."""
    from app.services.invoice.layout_readiness import (
        evaluate_layout_readiness,
        layout_readiness_audit_detail,
    )

    def _eval() -> object:
        with open_pdf_for_reading(invoice.raw_file_path, tenant_id=invoice.tenant_id) as path:
            return evaluate_layout_readiness(path)

    result = await asyncio.to_thread(_eval)
    await log_event(
        session,
        "layout_readiness_evaluated",
        invoice_id=invoice.id,
        detail={
            **layout_readiness_audit_detail(result),
            "document_ai_provider": document_ai_provider,
        },
    )
    return result


async def phase_ocr(
    session: AsyncSession,
    invoice: Invoice,
    *,
    org: OrgContext,
    document_types: Sequence[DocumentTypeDefinition],
    doc_provider: DocumentAiProvider,
    provider_token: str,
    human_locked_dt: str | None,
    vision_page_images: list[bytes] | None = None,
    readiness=None,
) -> OcrArtifact:
    """OCR / layout read only — no field extraction. Consumes layout readiness hints."""
    from app.services.invoice.layout_readiness import (
        OcrMode,
        LayoutReadinessResult,
        native_text_looks_incomplete,
        native_text_ocr_artifact,
    )
    from app.services.invoice.processing_override_catalog import has_deferred_full_reset

    ocr: OcrArtifact | None = None
    bypass_cache = has_deferred_full_reset(invoice)
    cache_hit = False
    ocr_path_used = "provider_default"
    fallback_triggered = False
    readiness_mode = readiness.ocr_mode.value if isinstance(readiness, LayoutReadinessResult) else None

    if invoice.file_hash and not bypass_cache:
        ocr = await load_cached_ocr(
            session,
            tenant_id=invoice.tenant_id,
            invoice_id=invoice.id,
            file_hash=invoice.file_hash,
        )
        cache_hit = ocr is not None
        if cache_hit:
            ocr_path_used = "cache"

    if ocr is None:
        with open_pdf_for_reading(invoice.raw_file_path, tenant_id=invoice.tenant_id) as path:
            path_obj = Path(path)
            # Prefer native text when layout readiness says so (Azure DI provider family)
            if (
                isinstance(readiness, LayoutReadinessResult)
                and readiness.ocr_mode == OcrMode.NATIVE_TEXT
                and doc_provider == DocumentAiProvider.AZURE_DI
                and path_obj.suffix.lower() == ".pdf"
            ):
                try:
                    ocr = native_text_ocr_artifact(path_obj)
                    ocr_path_used = "native_text"
                    if native_text_looks_incomplete(ocr, readiness):
                        if not provider_available(doc_provider) and not human_locked_dt:
                            raise OcrFailed(provider_unavailable_reason(doc_provider))
                        ocr = await read_for_classification(
                            path,
                            provider=doc_provider,
                            org=org,
                            document_types=document_types,
                            vision_page_images=vision_page_images,
                        )
                        ocr_path_used = "di_fallback"
                        fallback_triggered = True
                except OcrFailed:
                    raise
                except Exception:
                    ocr = None

            if ocr is None:
                if not provider_available(doc_provider) and not human_locked_dt:
                    raise OcrFailed(provider_unavailable_reason(doc_provider))
                # Ensure vision pages for vision_fallback / vision providers
                if (
                    isinstance(readiness, LayoutReadinessResult)
                    and readiness.ocr_mode == OcrMode.VISION_FALLBACK
                    and vision_page_images is not None
                    and len(vision_page_images) == 0
                ):
                    from app.services.extraction.vision_pdf import resolve_pdf_page_images

                    resolve_pdf_page_images(path_obj, vision_page_images)
                ocr = await read_for_classification(
                    path,
                    provider=doc_provider,
                    org=org,
                    document_types=document_types,
                    vision_page_images=vision_page_images,
                )
                ocr_path_used = doc_provider.value
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
            "ocr_cache_hit": cache_hit,
            "ocr_cache_bypassed": bypass_cache,
            "ocr_mode": readiness_mode,
            "ocr_path_used": ocr_path_used,
            "fallback_triggered": fallback_triggered,
        },
    )
    return ocr


def evaluate_ocr_quality_confirm(
    ocr: OcrArtifact,
    *,
    ai_cfg: AiClassificationConfig,
) -> ImageQualityGateResult:
    """Post-OCR quality confirm — sparse / short text / weak image_quality hints."""
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

    seen: set[str] = set()
    deduped = [r for r in reasons if not (r in seen or seen.add(r))]

    return ImageQualityGateResult(
        passed=not deduped,
        review_reasons=deduped,
        text_length=ocr.text_length,
        sparse=ocr.sparse,
        min_text_chars=min_chars,
    )


# Back-compat alias for callers/tests still using the old name
evaluate_image_quality_gate = evaluate_ocr_quality_confirm


def ocr_quality_confirm_audit_detail(
    result: ImageQualityGateResult,
    *,
    provider_token: str,
) -> dict[str, object]:
    return {
        "gate": "ocr_quality_confirm",
        "phase": "post_ocr",
        "compare_passed": result.passed,
        "review_reasons": result.review_reasons,
        "text_length": result.text_length,
        "sparse": result.sparse,
        "min_text_chars": result.min_text_chars,
        "document_ai_provider": provider_token,
        "resubmit_hint": "Please resend a flat, well-lit scan or PDF — avoid angled phone photos.",
    }


def image_quality_audit_detail(
    result: ImageQualityGateResult,
    *,
    provider_token: str,
) -> dict[str, object]:
    """Alias — dual-write compatible detail for legacy image_quality_gate_* events."""
    detail = ocr_quality_confirm_audit_detail(result, provider_token=provider_token)
    detail["gate"] = "image_quality"
    return detail


async def phase_ocr_quality_confirm(
    session: AsyncSession,
    invoice: Invoice,
    *,
    ocr: OcrArtifact,
    ai_cfg: AiClassificationConfig,
    document_ai_provider: str,
) -> ImageQualityGateResult:
    """Post-OCR sparse/text-length confirm. Caller handles skip override + exception status."""
    result = evaluate_ocr_quality_confirm(ocr, ai_cfg=ai_cfg)
    detail = {
        **ocr_quality_confirm_audit_detail(result, provider_token=document_ai_provider),
        **image_quality_audit_detail(result, provider_token=document_ai_provider),
        "gate": "ocr_quality_confirm",
    }
    # Dual-write legacy + new event names for dossier/UI compatibility
    passed = result.passed
    await log_event(
        session,
        "ocr_quality_confirm_passed" if passed else "ocr_quality_confirm_failed",
        invoice_id=invoice.id,
        detail=detail,
    )
    await log_event(
        session,
        "image_quality_gate_passed" if passed else "image_quality_gate_failed",
        invoice_id=invoice.id,
        detail=image_quality_audit_detail(result, provider_token=document_ai_provider),
    )
    return result


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
    vision_page_images: list[bytes] | None = None,
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
        vision_page_images=vision_page_images,
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
        resolve_segment_heading_with_source,
    )

    document_text = ocr.text or ""
    heading_text = (llm.document_heading if llm is not None else "") or ""
    inferred = resolve_segment_heading_with_source(
        document_text=f"{heading_text}\n{document_text}".strip(),
    )
    if inferred is None:
        return llm, None

    # Body-keyword-only matches (role labels, embedded keywords) must not override LLM.
    if inferred.source == "body_keyword":
        return llm, None

    heading_kind = inferred.kind
    parsed = InvoiceData(
        document_text=document_text,
        document_heading=heading_text.strip(),
    )
    previous_dt = (llm.suggested_dt if llm is not None else "") or ""
    previous_dt = previous_dt.strip().upper()
    llm_defn = (
        get_document_type_definition(previous_dt, document_types=document_types)
        if previous_dt
        else None
    )
    llm_conflicts = bool(
        llm_defn is not None and heading_conflicts_with_definition(heading_kind, llm_defn)
    )

    heading_match = classify_from_segment_heading(
        heading_kind=heading_kind,
        document_types=document_types,
        invoice=invoice,
        parsed=parsed,
    )

    # Invoice-like heading vs GRN/PO (etc.): never keep the conflicting LLM pick.
    if llm_conflicts and (heading_match is None or heading_match.needs_review):
        cleared = (llm or LlmDocumentResult()).model_copy(
            update={
                "suggested_dt": "",
                "confidence": 0.0,
                "reasoning": (
                    f"Cleared {previous_dt}: conflicts with segment heading ({heading_kind})"
                ),
                "document_heading": (heading_text or "").strip()
                or ((llm.document_heading if llm else "") or ""),
            }
        )
        return cleared, {
            "heading_kind": heading_kind,
            "heading_source": inferred.source,
            "previous_dt": previous_dt or None,
            "adopted_dt": None,
            "heading_confidence": None,
            "reason": "heading_conflicts_with_llm_dt",
            "cleared_conflicting_llm_dt": True,
        }

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

    adopt_reason: str | None = None

    if not previous_dt or llm_conflicts:
        adopt_reason = (
            "heading_conflicts_with_llm_dt" if llm_conflicts else "empty_llm_suggested_dt"
        )
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
            if heading_score >= float(ai_cfg.heading_catalogue_match_min) and heading_score > llm_score:
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
        "heading_source": inferred.source,
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


def apply_recognition_mode_gate(
    gate_result: GatePhaseResult,
    *,
    invoice: Invoice,
    ocr: OcrArtifact,
    document_types: Sequence[DocumentTypeDefinition],
) -> GatePhaseResult:
    """Enforce recognition_mode: signals DTs must match OCR; prompt DTs skip signal check."""
    if not gate_result.passed or not gate_result.confirmed_dt:
        return gate_result

    defn = get_document_type_definition(gate_result.confirmed_dt, document_types=document_types)
    if defn is None:
        return gate_result

    from app.services.classification.document_type_rule_engine import (
        effective_signals_mode_definition,
        is_prompt_recognition_mode,
    )
    from app.services.classification.segment_heading_classification import (
        heading_conflicts_with_definition,
        resolve_segment_heading_with_source,
    )

    inferred = resolve_segment_heading_with_source(document_text=ocr.text or "")
    if (
        inferred is not None
        and inferred.source != "body_keyword"
        and heading_conflicts_with_definition(inferred.kind, defn)
    ):
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

    if is_prompt_recognition_mode(defn):
        return gate_result

    # Only enforce OCR against explicit recognition_signals / match-rules.
    # Playbook-inferred identity (via effective_signals_mode_definition) is for
    # catalogue matching — applying it here rejects shipped DTs that only set
    # a playbook profile or rely on code defaults.
    has_explicit_signals = bool(
        [s for s in (defn.recognition_signals or []) if str(s).strip()]
    )
    from app.services.rule_book.rule_engine import classifier_has_actionable_conditions

    has_explicit_rules = bool(
        defn.classifier.enabled
        and classifier_has_actionable_conditions(defn.classifier.root)
    )
    if not has_explicit_signals and not has_explicit_rules:
        return gate_result

    effective = effective_signals_mode_definition(defn)
    # No configured signals / match rules → nothing to verify.
    if effective is None:
        return gate_result

    if classifier_rules_match_ocr(effective, invoice=invoice, ocr=ocr):
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


def apply_user_defined_classifier_gate(
    gate_result: GatePhaseResult,
    *,
    invoice: Invoice,
    ocr: OcrArtifact,
    document_types: Sequence[DocumentTypeDefinition],
) -> GatePhaseResult:
    """Back-compat alias: recognition_mode gate covers user-defined signals DTs."""
    return apply_recognition_mode_gate(
        gate_result,
        invoice=invoice,
        ocr=ocr,
        document_types=document_types,
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
    ocr_payload: dict[str, object] | None = None,
) -> FieldConfidenceGateResult:
    """Flag DT compulsory fields below per-field LLM or DI confidence threshold."""
    from app.config import get_settings
    from app.services.classification.document_type_field_checks import field_is_present
    from app.services.classification.document_type_rule_engine import build_document_classifier_context

    floor = ai_cfg.min_field_extract_confidence
    di_floor = get_settings().di_field_trust_min_confidence
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

    low: dict[str, float] = {}
    skipped_after_merge: list[str] = []

    # Azure DI / layout field confidence — any key present in payload, plus DT gate fields.
    # Prefer route-neutral keys (document_number, vendor_name) alongside legacy invoice aliases.
    di_conf_map: dict[str, object] = {}
    if isinstance(ocr_payload, dict):
        raw = ocr_payload.get("field_confidence")
        if isinstance(raw, dict):
            di_conf_map = raw
    core_trust_keys = {
        "subtotal",
        "gst",
        "tax",
        "total",
        "amount_due",
        "vendor",
        "vendor_name",
        "invoice_no",
        "document_number",
        "po_reference",
        "grn_reference",
        "line_items",
    }
    check_keys = set(gate_fields) | (core_trust_keys & set(di_conf_map.keys()))
    for key in check_keys:
        if key not in core_trust_keys and key not in gate_fields:
            continue
        conf_raw = di_conf_map.get(key)
        if conf_raw is None:
            continue
        try:
            conf = float(conf_raw)
        except (TypeError, ValueError):
            continue
        if conf < di_floor:
            low[f"di:{key}"] = round(conf, 4)

    if llm is None or not llm.field_confidence:
        reasons: list[str] = []
        if low:
            reasons.append(ReviewReason.FIELD_CONFIDENCE_LOW.value)
        return FieldConfidenceGateResult(
            passed=not low,
            low_confidence_fields=low,
            min_confidence=floor,
            gate_fields=gate_fields,
            confirmed_dt=dt_code,
            missing_gate_fields=missing_gate_fields,
            review_reasons=reasons,
            skipped_fields_present_after_merge=[
                key for key in gate_fields if key not in missing_gate_fields
            ],
        )

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

    reasons = []
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
    """Return whether line items meet review threshold (present + confidence)."""
    from app.services.classification.document_type_playbook_service import confidence_gate_fields
    from app.services.extraction.extraction_orchestrator import _doc_line_items_confidence
    from app.services.extraction.field_extraction_confidence import _score_line_items
    from app.services.extraction.line_item_extraction_policy import (
        classify_line_document_shape,
        document_requires_line_items,
        line_items_extraction_incomplete,
    )
    from app.services.extraction.line_item_parsing_config import DEFAULT_THRESHOLDS

    wants_lines = document_requires_line_items(dt_definition) or (
        "line_items" in confidence_gate_fields(dt_definition)
    )
    if parsed is None:
        if wants_lines:
            return False, None, ["line_items_missing"]
        return True, None, []

    shape = classify_line_document_shape(
        parsed.document_text or "",
        None,
        dt_definition=dt_definition,
        parsed=parsed,
    )
    if line_items_extraction_incomplete(
        wants_line_items=wants_lines,
        rows=list(parsed.line_items or []),
        shape=shape if wants_lines else None,
    ):
        return False, None, ["line_items_missing"]

    if not parsed.line_items:
        return True, None, []

    gate_fields = confidence_gate_fields(dt_definition)
    if "line_items" not in gate_fields and not wants_lines:
        return True, None, []
    if "line_items" not in gate_fields:
        # Required via extraction fields but not confidence-gated — presence only.
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
