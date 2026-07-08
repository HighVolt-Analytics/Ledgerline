"""Post-classification pipeline phases (extract → evaluate → playbook → route sync)."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import Invoice, InvoiceStatus
from app.schemas.document_type import DocumentTypeDefinition
from app.schemas.ocr_artifact import OcrArtifact
from app.schemas.rule_book_config import RuleBookConfigPayload
from app.services.audit.audit_service import log_event
from app.services.classification.document_type_catalog import get_document_type_definition
from app.services.classification.document_type_playbook_service import (
    PlaybookGateResult,
    evaluate_playbook_gates,
)
from app.services.classification.finance_dt_policy_scorer import score_all_enabled_dts
from app.services.extraction.document_ai_provider import DocumentAiProvider
from app.services.extraction.llm_document_service import apply_document_type_to_invoice
from app.services.invoice.invoice_data import InvoiceData
from app.services.invoice.invoice_evaluation_service import (
    EVAL_NEEDS_REVIEW,
    apply_invoice_evaluation,
)
from app.services.tenant.tenant_org_context import OrgContext

if TYPE_CHECKING:
    from app.schemas.llm_document import LlmDocumentResult


class PostPhaseStatus(str, Enum):
    CONTINUE = "continue"
    HOLD = "hold"
    TERMINAL = "terminal"


@dataclass
class PostPhaseResult:
    status: PostPhaseStatus
    audit_event: str | None = None
    detail: dict[str, object] = field(default_factory=dict)
    message: str = ""


@dataclass
class PolicyAfterExtractResult:
    applied: bool
    auto_corrected: bool
    needs_review: bool
    policy_winner_dt: str = ""
    policy_confidence: float = 0.0
    llm_dt: str = ""
    review_reasons: list[str] = field(default_factory=list)


_POLICY_AUTO_CORRECT_GAP = 0.12
_POLICY_REVIEW_GAP = 0.05


async def apply_policy_scorer_after_extract(
    session: AsyncSession,
    *,
    invoice: Invoice,
    loaded: Invoice,
    parsed: InvoiceData,
    config: RuleBookConfigPayload,
    llm_dt: str,
    llm_confidence: float,
) -> PolicyAfterExtractResult:
    """Run policy scorer on extracted fields; auto-correct or flag needs_review."""
    from app.services.classification.document_type_reclassify_service import (
        should_reclassify_invoice_document_type,
    )

    result = PolicyAfterExtractResult(
        applied=False,
        auto_corrected=False,
        needs_review=False,
        llm_dt=(llm_dt or "").strip().upper(),
    )
    if not await should_reclassify_invoice_document_type(session, loaded, config=config):
        return result

    policy = score_all_enabled_dts(
        invoice=loaded,
        parsed=parsed,
        document_types=config.document_types,
    )
    winner = (policy.winner_dt or "").strip().upper()
    if not winner:
        return result

    result.applied = True
    result.policy_winner_dt = winner
    result.policy_confidence = float(policy.winner_confidence or 0.0)
    current = (loaded.document_type_code or llm_dt or "").strip().upper()
    if not current or winner == current:
        return result

    gap = abs(result.policy_confidence - float(llm_confidence or 0.0))
    if gap >= _POLICY_AUTO_CORRECT_GAP and result.policy_confidence >= float(llm_confidence or 0.0):
        apply_document_type_to_invoice(
            loaded,
            code=winner,
            confidence=result.policy_confidence,
            llm_suggested_dt=llm_dt or None,
            llm_confidence=llm_confidence,
        )
        invoice.document_type_code = loaded.document_type_code
        invoice.document_type_confidence = loaded.document_type_confidence
        result.auto_corrected = True
        await apply_invoice_evaluation(session, loaded, config=config, enqueue_pending=False)
        await log_event(
            session,
            "policy_after_extract_corrected",
            invoice_id=invoice.id,
            detail={
                "from_dt": current,
                "to_dt": winner,
                "policy_confidence": result.policy_confidence,
                "llm_confidence": llm_confidence,
            },
        )
        return result

    if gap >= _POLICY_REVIEW_GAP:
        loaded.evaluation_status = EVAL_NEEDS_REVIEW
        invoice.evaluation_status = EVAL_NEEDS_REVIEW
        result.needs_review = True
        result.review_reasons = ["DT_MISMATCH"]
        await log_event(
            session,
            "routing_review_required",
            invoice_id=invoice.id,
            detail={
                "gate": "policy_after_extract",
                "review_reasons": result.review_reasons,
                "llm_suggested_dt": current,
                "policy_winner_dt": winner,
                "policy_confidence": result.policy_confidence,
                "llm_confidence": llm_confidence,
            },
        )
    return result


async def try_targeted_field_reextract(
    session: AsyncSession,
    *,
    invoice: Invoice,
    loaded: Invoice,
    parsed: InvoiceData,
    playbook: PlaybookGateResult,
    ocr: OcrArtifact,
    file_path: str,
    org: OrgContext,
    config: RuleBookConfigPayload,
    confirmed_dt: str,
    few_shots: Sequence[dict[str, str]],
    doc_provider: DocumentAiProvider,
) -> PlaybookGateResult:
    """Retry gap-fill once when only extraction fields are missing (no bundle gap)."""
    if playbook.missing_bundle_mandatory or playbook.linkage_key_missing:
        return playbook

    dt_definition = get_document_type_definition(
        confirmed_dt,
        document_types=config.document_types,
        tenant_id=invoice.tenant_id,
    )
    if dt_definition is None:
        return playbook

    from app.services.classification.document_type_field_checks import field_is_present
    from app.services.classification.document_type_playbook_service import effective_playbook_required_fields
    from app.services.classification.document_type_rule_engine import build_document_classifier_context

    ctx = build_document_classifier_context(invoice=loaded, parsed=parsed)
    missing_required = [
        key
        for key in effective_playbook_required_fields(dt_definition)
        if not field_is_present(key, invoice=loaded, parsed=parsed, ctx=ctx)
    ]
    if not missing_required and not playbook.missing_extraction_fields:
        return playbook

    from app.services.extraction.extraction_field_values import (
        INVOICE_SCALAR_ATTRS,
        apply_parsed_extraction_fields,
        effective_extraction_field_keys_for_dt,
    )
    from app.services.extraction.gap_fill_extraction_service import apply_extraction_gap_fill

    selected_keys = effective_extraction_field_keys_for_dt(config.document_types, confirmed_dt)
    retry_parsed, gap_detail = await apply_extraction_gap_fill(
        parsed,
        ocr=ocr,
        selected_keys=selected_keys,
        org=org,
        dt_definition=dt_definition,
        invoice=loaded,
    )
    if not gap_detail.get("gap_fill_attempted"):
        return playbook

    apply_parsed_extraction_fields(loaded, retry_parsed)
    invoice.extracted_fields = loaded.extracted_fields
    for field_name in INVOICE_SCALAR_ATTRS:
        value = getattr(retry_parsed, field_name, None)
        if field_name == "currency":
            if value is not None and str(value).strip():
                setattr(parsed, field_name, value)
                setattr(loaded, field_name, value)
                setattr(invoice, field_name, value)
            continue
        if value is not None and str(value).strip():
            setattr(parsed, field_name, value)
            setattr(loaded, field_name, value)
            setattr(invoice, field_name, value)

    retried = await evaluate_playbook_gates(
        session,
        invoice=loaded,
        parsed=retry_parsed,
        definition=dt_definition,
        document_types=list(config.document_types),
    )
    await log_event(
        session,
        "field_reextract_attempted",
        invoice_id=invoice.id,
        detail={
            "missing_required_before": missing_required,
            "missing_before": list(playbook.missing_extraction_fields),
            "missing_after": list(retried.missing_extraction_fields),
            "blocks_posting": retried.blocks_posting,
            "gap_fill": gap_detail,
        },
    )
    return retried


async def evaluate_playbook_with_reextract(
    session: AsyncSession,
    *,
    invoice: Invoice,
    loaded: Invoice,
    parsed: InvoiceData,
    definition: DocumentTypeDefinition | None,
    document_types: list[DocumentTypeDefinition],
    ocr: OcrArtifact,
    file_path: str,
    org: OrgContext,
    config: RuleBookConfigPayload,
    confirmed_dt: str,
    few_shots: Sequence[dict[str, str]],
    doc_provider: DocumentAiProvider,
) -> PlaybookGateResult:
    """Evaluate playbook gates; retry targeted re-extract when only fields are missing."""
    playbook = await evaluate_playbook_gates(
        session,
        invoice=loaded,
        parsed=parsed,
        definition=definition,
        document_types=document_types,
    )
    if (
        (playbook.missing_extraction_fields or playbook.missing_optional_extraction_fields)
        and not playbook.missing_bundle_mandatory
        and not playbook.linkage_key_missing
    ):
        playbook = await try_targeted_field_reextract(
            session,
            invoice=invoice,
            loaded=loaded,
            parsed=parsed,
            playbook=playbook,
            ocr=ocr,
            file_path=file_path,
            org=org,
            config=config,
            confirmed_dt=confirmed_dt,
            few_shots=few_shots,
            doc_provider=doc_provider,
        )
    return playbook


async def log_match_phase_evaluated(
    session: AsyncSession,
    *,
    invoice_id: int,
    detail: dict[str, object],
) -> PostPhaseResult:
    await log_event(
        session,
        "match_phase_evaluated",
        invoice_id=invoice_id,
        detail=detail,
    )
    if detail.get("evaluation_status") in {"awaiting_po", "awaiting_so"}:
        return PostPhaseResult(
            status=PostPhaseStatus.HOLD,
            audit_event="match_phase_evaluated",
            detail=detail,
            message="Awaiting order linkage for match",
        )
    return PostPhaseResult(
        status=PostPhaseStatus.CONTINUE,
        audit_event="match_phase_evaluated",
        detail=detail,
    )


def playbook_hold_result(
    playbook: PlaybookGateResult,
    *,
    gate: str = "playbook",
) -> PostPhaseResult | None:
    if not playbook.blocks_posting:
        return None
    return PostPhaseResult(
        status=PostPhaseStatus.HOLD,
        audit_event="routing_review_required",
        detail={"gate": gate, "playbook": playbook.audit_detail()},
        message="Playbook gate blocked posting",
    )
