"""Compare LLM classification with Rule Book policy; fail closed to review."""

from __future__ import annotations

from collections.abc import Sequence

from app.config import get_settings
from app.models.invoice import Invoice
from app.schemas.classification_decision import ClassificationDecision, PolicyScoreResult, ReviewReason
from app.schemas.document_type import DocumentTypeDefinition
from app.schemas.llm_document import LlmDocumentResult
from app.services.document_type_catalog import get_document_type_definition, min_route_confidence_for_document_type
from app.services.document_type_playbook_service import (
    effective_extraction_fields,
    missing_extraction_fields,
    resolve_definition_for_invoice,
)
from app.services.document_type_rule_engine import build_document_classifier_context
from app.services.invoice_data import InvoiceData
from app.services.tenant_org_context import OrgContext, infer_perspective


def _dt_enabled(code: str, document_types: Sequence[DocumentTypeDefinition]) -> bool:
    defn = get_document_type_definition(code, document_types=document_types)
    return defn is not None and defn.enabled


def compare_classification(
    *,
    llm: LlmDocumentResult | None,
    policy: PolicyScoreResult,
    invoice: Invoice,
    parsed: InvoiceData,
    document_types: Sequence[DocumentTypeDefinition],
    org: OrgContext,
    ocr_sparse: bool = False,
    auto_route_min_confidence: float | None = None,
    pre_extract: bool = False,
    document_ai_provider: str | None = None,
) -> ClassificationDecision:
    settings = get_settings()
    org_route_min = (
        auto_route_min_confidence
        if auto_route_min_confidence is not None
        else settings.runtime_llm_min_confidence
    )

    reasons: list[ReviewReason] = []
    decision = ClassificationDecision(
        policy_winner_dt=policy.winner_dt,
        policy_winner_confidence=policy.winner_confidence,
        policy_scores=policy.scores,
    )

    if ocr_sparse:
        reasons.append(ReviewReason.OCR_SPARSE)

    if llm is None:
        reasons.append(ReviewReason.LLM_INVALID)
        decision.review_reasons = reasons
        decision.audit_detail = _audit_detail(
            decision,
            route_min=org_route_min,
            document_ai_provider=document_ai_provider,
        )
        return decision

    decision.llm_suggested_dt = llm.suggested_dt
    decision.llm_confidence = llm.confidence
    decision.llm_reasoning = llm.reasoning

    llm_route_min = max(
        min_route_confidence_for_document_type(llm.suggested_dt, document_types)
        if llm.suggested_dt
        else org_route_min,
        org_route_min,
    )
    policy_route_min = max(
        min_route_confidence_for_document_type(policy.winner_dt, document_types)
        if policy.winner_dt
        else org_route_min,
        org_route_min,
    )

    if not llm.suggested_dt:
        reasons.append(ReviewReason.DT_NOT_IN_CATALOGUE)
    elif not _dt_enabled(llm.suggested_dt, document_types):
        reasons.append(ReviewReason.DT_DISABLED if llm.suggested_dt else ReviewReason.DT_NOT_IN_CATALOGUE)
        if llm.suggested_dt and not get_document_type_definition(llm.suggested_dt, document_types=document_types):
            reasons.append(ReviewReason.DT_NOT_IN_CATALOGUE)

    if llm.confidence < llm_route_min:
        reasons.append(ReviewReason.LLM_LOW_CONF)

    if policy.winner_confidence < policy_route_min or not policy.winner_dt:
        reasons.append(ReviewReason.POLICY_LOW_CONF)

    if llm.suggested_dt and policy.winner_dt and llm.suggested_dt != policy.winner_dt:
        reasons.append(ReviewReason.DT_MISMATCH)

    perspective = infer_perspective(
        org=org,
        seller_name=llm.seller.name,
        seller_abn=llm.seller.abn,
        buyer_name=llm.buyer.name,
        buyer_abn=llm.buyer.abn,
        llm_perspective=llm.perspective,
    )
    decision.perspective = perspective
    if perspective == "unknown":
        reasons.append(ReviewReason.PERSPECTIVE_AMBIGUOUS)

    # Playbook extraction on suggested DT
    defn = get_document_type_definition(llm.suggested_dt, document_types=document_types) if llm.suggested_dt else None
    if defn is not None and not pre_extract:
        missing = missing_extraction_fields(defn, invoice=invoice, parsed=parsed)
        if missing:
            reasons.append(ReviewReason.EXTRACTION_GAP)

    if defn is not None and (defn.posting or "").strip().lower() == "conditional":
        reasons.append(ReviewReason.NEVER_AUTO_POLICY)

    confirmed_dt = ""
    confirmed_conf = 0.0
    if not reasons and llm.suggested_dt and policy.winner_dt:
        confirmed_dt = llm.suggested_dt
        confirmed_conf = round(min(llm.confidence, policy.winner_confidence), 4)

    decision.confirmed_dt = confirmed_dt
    decision.confirmed_confidence = confirmed_conf
    decision.review_reasons = reasons
    decision.auto_eligible = not reasons and bool(confirmed_dt)
    agreed_route_min = (
        min_route_confidence_for_document_type(confirmed_dt, document_types)
        if confirmed_dt
        else max(llm_route_min, policy_route_min)
    )
    decision.audit_detail = _audit_detail(
        decision,
        route_min=agreed_route_min,
        llm_route_min=llm_route_min,
        policy_route_min=policy_route_min,
        extraction_fields=list(effective_extraction_fields(defn)) if defn else [],
        document_ai_provider=document_ai_provider,
        pre_extract=pre_extract,
        org_auto_route_min=org_route_min,
    )
    return decision


def _audit_detail(
    decision: ClassificationDecision,
    *,
    route_min: float,
    llm_route_min: float | None = None,
    policy_route_min: float | None = None,
    extraction_fields: list[str] | None = None,
    document_ai_provider: str | None = None,
    pre_extract: bool = False,
    org_auto_route_min: float | None = None,
) -> dict[str, object]:
    settings = get_settings()
    return {
        "llm_suggested_dt": decision.llm_suggested_dt,
        "llm_confidence": decision.llm_confidence,
        "llm_reasoning": decision.llm_reasoning,
        "policy_winner_dt": decision.policy_winner_dt,
        "policy_winner_confidence": decision.policy_winner_confidence,
        "policy_scores": [row.model_dump() for row in decision.policy_scores],
        "confirmed_dt": decision.confirmed_dt,
        "confirmed_confidence": decision.confirmed_confidence,
        "perspective": decision.perspective,
        "review_reasons": [r.value for r in decision.review_reasons],
        "compare_passed": decision.auto_eligible,
        "min_route_confidence": route_min,
        "llm_min_route_confidence": llm_route_min,
        "policy_min_route_confidence": policy_route_min,
        "prompt_version": settings.llm_classification_prompt_version,
        "extraction_fields": extraction_fields or [],
        "document_ai_provider": document_ai_provider,
        "pre_extract": pre_extract,
        "org_auto_route_min_confidence": org_auto_route_min,
    }

