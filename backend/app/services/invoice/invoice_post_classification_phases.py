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
    corrected_dt: str = ""
    review_reasons: list[str] = field(default_factory=list)
    pruned_field_keys: list[str] = field(default_factory=list)
    oscillation_hold: bool = False


_POLICY_AUTO_CORRECT_GAP = 0.12
_POLICY_REVIEW_GAP = 0.05

# Always retain routing / infra keys when pruning to a DT manifest.
_PRUNE_KEEP_EXTRACTED_KEYS = frozenset(
    {
        "perspective",
        "llm_perspective",
        "document_heading",
        "seller_name",
        "buyer_name",
        "seller_tax_id",
        "buyer_tax_id",
        "seller_address",
        "buyer_address",
        "seller_abn",
        "buyer_abn",
    }
)


def prune_invoice_fields_to_dt_manifest(
    invoice: Invoice,
    parsed: InvoiceData,
    *,
    document_types: Sequence[DocumentTypeDefinition],
    confirmed_dt: str,
) -> list[str]:
    """Drop extracted_fields / scalars not in the new DT schema. Returns pruned keys."""
    from app.services.extraction.extraction_field_values import (
        INVOICE_SCALAR_ATTRS,
        INFRASTRUCTURE_ATTRS,
        effective_extraction_field_keys_for_dt,
    )

    allowed = {
        str(k).strip().lower()
        for k in effective_extraction_field_keys_for_dt(document_types, confirmed_dt)
        if str(k).strip()
    }
    allowed |= {k.lower() for k in _PRUNE_KEEP_EXTRACTED_KEYS}
    allowed |= {k.lower() for k in INFRASTRUCTURE_ATTRS}
    # Currency is a shared display attribute — keep unless explicitly unwanted.
    allowed.add("currency")

    pruned: list[str] = []
    fields = dict(invoice.extracted_fields or {})
    for key in list(fields.keys()):
        token = str(key).strip().lower()
        if token and token not in allowed:
            pruned.append(str(key))
            del fields[key]
    invoice.extracted_fields = fields or None

    for attr in INVOICE_SCALAR_ATTRS:
        if attr in allowed:
            continue
        current = getattr(invoice, attr, None)
        if current is None or (isinstance(current, str) and not current.strip()):
            continue
        pruned.append(attr)
        setattr(invoice, attr, None)
        if hasattr(parsed, attr):
            setattr(parsed, attr, None)

    if "line_items" not in allowed and parsed.line_items:
        pruned.append("line_items")
        parsed.line_items = []

    return sorted(set(pruned))


async def apply_policy_scorer_after_extract(
    session: AsyncSession,
    *,
    invoice: Invoice,
    loaded: Invoice,
    parsed: InvoiceData,
    config: RuleBookConfigPayload,
    llm_dt: str,
    llm_confidence: float,
    force: bool = False,
    allow_auto_correct: bool = True,
    auto_correct_gap: float | None = None,
    review_gap: float | None = None,
) -> PolicyAfterExtractResult:
    """Run policy scorer on extracted fields; auto-correct or flag needs_review.

    Use ``force=True`` during ``process_invoice`` (status is often PARSING, which
    would otherwise skip reclassify). Set ``allow_auto_correct=False`` on the
    post-reextract pass so a second disagreement holds for review instead of looping.
    """
    from app.services.classification.document_type_reclassify_service import (
        should_reclassify_invoice_document_type,
    )

    correct_gap = (
        float(auto_correct_gap)
        if auto_correct_gap is not None
        else _POLICY_AUTO_CORRECT_GAP
    )
    rev_gap = float(review_gap) if review_gap is not None else _POLICY_REVIEW_GAP

    result = PolicyAfterExtractResult(
        applied=False,
        auto_corrected=False,
        needs_review=False,
        llm_dt=(llm_dt or "").strip().upper(),
    )
    if not await should_reclassify_invoice_document_type(
        session, loaded, config=config, force=force
    ):
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
    can_auto = (
        allow_auto_correct
        and gap >= correct_gap
        and result.policy_confidence >= float(llm_confidence or 0.0)
    )
    if can_auto:
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
        result.corrected_dt = winner
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

    # Disagreement without auto-correct: review hold (incl. post-reextract oscillation).
    if gap >= rev_gap or (not allow_auto_correct and gap >= correct_gap):
        loaded.evaluation_status = EVAL_NEEDS_REVIEW
        invoice.evaluation_status = EVAL_NEEDS_REVIEW
        result.needs_review = True
        if not allow_auto_correct:
            result.oscillation_hold = True
            result.review_reasons = ["DT_MISMATCH_AFTER_REEXTRACT"]
            await log_event(
                session,
                "policy_after_extract_oscillation",
                invoice_id=invoice.id,
                detail={
                    "gate": "policy_after_extract_reextract",
                    "review_reasons": result.review_reasons,
                    "current_dt": current,
                    "policy_winner_dt": winner,
                    "policy_confidence": result.policy_confidence,
                    "baseline_confidence": llm_confidence,
                },
            )
            await log_event(
                session,
                "routing_review_required",
                invoice_id=invoice.id,
                detail={
                    "gate": "policy_after_extract_reextract",
                    "review_reasons": result.review_reasons,
                    "llm_suggested_dt": current,
                    "policy_winner_dt": winner,
                    "policy_confidence": result.policy_confidence,
                    "llm_confidence": llm_confidence,
                },
            )
        else:
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


async def reextract_fields_for_corrected_dt(
    session: AsyncSession,
    *,
    invoice: Invoice,
    loaded: Invoice,
    ocr: OcrArtifact,
    file_path: str,
    org: OrgContext,
    config: RuleBookConfigPayload,
    confirmed_dt: str,
    few_shots: Sequence[dict[str, str]],
    doc_provider: DocumentAiProvider,
) -> tuple[InvoiceData, list[str]]:
    """Re-run extract for ``confirmed_dt``, apply fields, prune old-schema keys."""
    from dataclasses import replace

    from app.services.classification.playbook_profile_catalog import (
        effective_counterparty_source,
    )
    from app.services.extraction.document_ai_provider import extract_fields
    from app.services.extraction.extraction_field_values import (
        apply_parsed_extraction_fields,
        effective_extraction_field_keys_for_dt,
        enrich_parsed_from_ocr,
        non_canonical_extraction_keys,
    )
    from app.services.extraction.field_grounding_service import ground_parsed_fields
    from app.services.extraction.gap_fill_extraction_service import apply_extraction_gap_fill
    from app.services.extraction.line_items_fallback_service import apply_line_items_fallback
    from app.services.extraction.llm_document_service import llm_result_to_invoice_data
    from app.services.extraction.pdf_parser import parse_local_text
    from app.models.line_item import LineItem
    from sqlalchemy import delete

    extract_result = await extract_fields(
        ocr,
        file_path=file_path,
        org=org,
        document_types=config.document_types,
        confirmed_dt=confirmed_dt,
        few_shots=few_shots,
        provider=doc_provider,
    )
    llm_result = extract_result.llm
    ocr_out = extract_result.ocr
    if invoice.file_hash and (
        (ocr_out.payload_json or {}).get("invoice_fields")
        or (ocr_out.payload_json or {}).get("extraction_route")
        or (ocr_out.payload_json or {}).get("finance_document")
        or (ocr_out.payload_json or {}).get("di_line_items")
    ):
        from app.services.classification.classification_learning_service import (
            upsert_ocr_artifact_enrichment,
        )

        await upsert_ocr_artifact_enrichment(
            session,
            tenant_id=invoice.tenant_id,
            invoice_id=invoice.id,
            file_hash=invoice.file_hash,
            ocr=ocr_out,
        )
    selected_keys = effective_extraction_field_keys_for_dt(
        config.document_types, confirmed_dt
    )
    custom_keys = non_canonical_extraction_keys(selected_keys)
    dt_definition = get_document_type_definition(
        confirmed_dt,
        document_types=config.document_types,
        tenant_id=invoice.tenant_id,
    )

    if llm_result is not None:
        parsed = llm_result_to_invoice_data(
            llm_result,
            ocr=ocr_out,
            custom_keys=custom_keys or None,
            selected_keys=selected_keys,
            org=org,
            counterparty_source=effective_counterparty_source(dt_definition)
            if dt_definition
            else "letterhead",
            route_target=dt_definition.route_target if dt_definition else None,
        )
    else:
        local = parse_local_text(ocr_out.text or "")
        parsed = replace(local, document_text=ocr_out.text or local.document_text)

    parsed = ground_parsed_fields(
        parsed,
        ocr_out.text,
        selected_keys,
        ocr_out.payload_json,
        org_country=org.country if org else None,
    )
    parsed = enrich_parsed_from_ocr(parsed, ocr_out, dt_definition=dt_definition)
    parsed, _gap = await apply_extraction_gap_fill(
        parsed,
        ocr=ocr_out,
        selected_keys=selected_keys,
        org=org,
        dt_definition=dt_definition,
        invoice=loaded,
    )
    parsed, _tier = apply_line_items_fallback(
        parsed,
        ocr_text=ocr_out.text,
        ocr_payload=ocr_out.payload_json or {},
        dt_definition=dt_definition,
    )

    # Replace prior extraction rather than merging stale keys.
    loaded.extracted_fields = None
    invoice.extracted_fields = None
    apply_parsed_extraction_fields(loaded, parsed)
    invoice.extracted_fields = loaded.extracted_fields

    from app.services.extraction.extraction_field_values import INVOICE_SCALAR_ATTRS

    for field_name in INVOICE_SCALAR_ATTRS:
        value = getattr(parsed, field_name, None)
        setattr(loaded, field_name, value)
        setattr(invoice, field_name, value)

    # Replace line items without importing pipeline (avoids circular import).
    stale = list(loaded.line_items or [])
    for item in stale:
        await session.delete(item)
    if not stale and loaded.id:
        await session.execute(delete(LineItem).where(LineItem.invoice_id == loaded.id))
    if hasattr(loaded, "line_items") and loaded.line_items is not None:
        loaded.line_items.clear()
    await session.flush()
    if "line_items" in {str(k).strip().lower() for k in selected_keys}:
        from app.services.shared.amount_sanity import sanitize_parsed_line_item

        for line in parsed.line_items or []:
            cleaned = sanitize_parsed_line_item(line)
            loaded.line_items.append(
                LineItem(
                    tenant_id=loaded.tenant_id,
                    invoice_id=loaded.id,
                    description=cleaned.description,
                    qty=cleaned.qty,
                    unit_price=cleaned.unit_price,
                    amount=cleaned.amount,
                    tax_amount=cleaned.tax_amount,
                    extraction_source=cleaned.source,
                    source_confidence=cleaned.source_confidence,
                    fused_from=list(cleaned.fused_from) if cleaned.fused_from else None,
                )
            )

    pruned = prune_invoice_fields_to_dt_manifest(
        loaded,
        parsed,
        document_types=config.document_types,
        confirmed_dt=confirmed_dt,
    )
    invoice.extracted_fields = loaded.extracted_fields
    for field_name in INVOICE_SCALAR_ATTRS:
        setattr(invoice, field_name, getattr(loaded, field_name, None))

    await log_event(
        session,
        "policy_after_extract_reextract",
        invoice_id=invoice.id,
        detail={
            "confirmed_dt": confirmed_dt,
            "pruned_field_keys": pruned,
            "selected_keys": list(selected_keys),
        },
    )
    return parsed, pruned


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
