"""Map vision header labels to a tenant Rule Book DT-xx.

Hybrid resolve order:
1) Human lock (reviewer confirmed DT on this invoice)
2) Catalogue title match — vision printed title vs Rule Book shortTitle/title
   (no hardcoded document-type names)
3) Known employee on email/WhatsApp/Viber → catalogue Team Expenses DT
   (expense claim vs advance requisition; any receipt/invoice shape)
4) Deterministic heading-kind scoring (same scorer as PDF segment classify)
5) Tenant heading learning (exact normalized title → prior human_confirmed_dt)
6) Configured classifiers (recognition / playbook identity signals)
7) Text-LLM catalogue fallback using description/summary — may pick ONLY a
   catalogue DT-xx, or leave empty
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Any
from uuid import UUID

from app.schemas.document_type import DocumentTypeDefinition
from app.services.classification.segment_heading_classification import (
    heading_conflicts_with_definition,
    resolve_segment_heading_with_source,
    score_document_type_for_heading,
)
from app.services.invoice.vision_header_extract import derive_canonical_document_type
from app.utils.logger import get_logger

logger = get_logger(__name__)

_MATCH_THRESHOLD = 0.82
_AMBIGUITY_MARGIN = 0.05
_METHOD_RULES = "heading_kind_score"
_METHOD_CATALOGUE_TITLE = "catalogue_title_match"
_METHOD_LEARNING = "tenant_heading_learning"
_METHOD_CLASSIFIER = "config_classifier"
_METHOD_LLM = "llm_catalogue_fallback"
_METHOD_TE_CHANNEL = "te_employee_channel"
_LLM_FALLBACK_REASONS = frozenset({"no_kind", "below_threshold", "ambiguous"})
_LLM_MIN_CONFIDENCE = 0.55
_PROMPT_KEY = "vision.dt_map_fallback.system"


@dataclass(frozen=True)
class VisionDocumentTypeMapResult:
    code: str | None
    confidence: float
    heading_kind: str | None
    reason: str
    # matched | below_threshold | ambiguous | no_kind | human_locked | empty_catalogue
    # | learning_matched | classifier_matched | classifier_no_match
    # | llm_matched | llm_empty | llm_rejected | llm_error | llm_unavailable
    method: str = _METHOD_RULES
    runner_up_code: str | None = None
    runner_up_score: float | None = None
    rule_reason: str | None = None  # prior rule outcome when a fallback ran
    llm_reasoning: str | None = None


def map_vision_label_to_document_type(
    *,
    document_heading: str,
    canonical_document_type: str,
    document_types: Sequence[DocumentTypeDefinition],
    human_locked_dt: str = "",
    filename: str | None = None,
    invoice: Any | None = None,
) -> VisionDocumentTypeMapResult:
    """Deterministic resolve vision heading/canonical label → Rule Book DT code."""
    from app.services.classification.document_role_resolve_service import (
        filter_document_types_for_perspective,
        filter_document_types_for_role,
        perspective_from_invoice,
        resolve_document_role,
    )

    locked = (human_locked_dt or "").strip().upper()
    if locked:
        return VisionDocumentTypeMapResult(
            code=locked,
            confidence=1.0,
            heading_kind=None,
            reason="human_locked",
            method=_METHOD_RULES,
        )

    enabled = [dt for dt in document_types if getattr(dt, "enabled", True)]
    if not enabled:
        return VisionDocumentTypeMapResult(
            code=None,
            confidence=0.0,
            heading_kind=None,
            reason="empty_catalogue",
            method=_METHOD_RULES,
        )

    # Title-first: match vision printed title to Rule Book titles (tenant catalogue).
    from app.services.classification.catalogue_title_match import (
        match_catalogue_dt_by_vision_title,
    )

    title_heading = (document_heading or "").strip() or (
        derive_canonical_document_type(
            document_heading=document_heading or "",
            canonical_document_type=canonical_document_type or "",
        )
        or ""
    ).strip()
    title_hit = match_catalogue_dt_by_vision_title(
        document_heading=title_heading,
        document_types=enabled,
    )
    if title_hit is not None:
        best_def, best_score, runner_up_code, runner_up_score = title_hit
        code = (best_def.code or "").strip().upper() or None
        if code:
            return VisionDocumentTypeMapResult(
                code=code,
                confidence=round(float(best_score), 4),
                heading_kind=None,
                reason="catalogue_title_matched",
                method=_METHOD_CATALOGUE_TITLE,
                runner_up_code=runner_up_code,
                runner_up_score=runner_up_score,
            )

    canonical = derive_canonical_document_type(
        document_heading=document_heading or "",
        canonical_document_type=canonical_document_type or "",
    )
    blob = "\n".join(
        part.strip()
        for part in (document_heading or "", canonical)
        if (part or "").strip()
    )
    if not blob.strip():
        return VisionDocumentTypeMapResult(
            code=None,
            confidence=0.0,
            heading_kind=None,
            reason="no_kind",
            method=_METHOD_RULES,
        )

    inferred = resolve_segment_heading_with_source(document_text=blob)
    heading_kind = inferred.kind if inferred else None
    if heading_kind is None:
        return VisionDocumentTypeMapResult(
            code=None,
            confidence=0.0,
            heading_kind=None,
            reason="no_kind",
            method=_METHOD_RULES,
        )

    attach = (filename or "").strip()
    if not attach and invoice is not None:
        attach = (
            getattr(invoice, "email_attachment_name", None)
            or getattr(invoice, "original_filename", None)
            or ""
        )
    doc_role = resolve_document_role(
        heading_kind=str(heading_kind),
        filename=attach or None,
        invoice=invoice,
        document_text=blob,
    )
    candidates = filter_document_types_for_role(enabled, doc_role)
    candidates = filter_document_types_for_perspective(
        candidates, perspective_from_invoice(invoice)
    )
    if doc_role and not candidates:
        return VisionDocumentTypeMapResult(
            code=None,
            confidence=0.0,
            heading_kind=str(heading_kind),
            reason=f"no_dt_for_role_{doc_role}",
            method=_METHOD_RULES,
        )

    scored: list[tuple[DocumentTypeDefinition, float]] = []
    for definition in candidates:
        if heading_conflicts_with_definition(heading_kind, definition):
            continue
        score = score_document_type_for_heading(definition, heading_kind)
        if score >= _MATCH_THRESHOLD:
            scored.append((definition, score))

    if not scored:
        # Role filter may have left only low-scoring supporting cards; still prefer
        # any non-conflicting role match over falling back to the full catalogue.
        if doc_role and candidates:
            for definition in candidates:
                if heading_conflicts_with_definition(heading_kind, definition):
                    continue
                score = score_document_type_for_heading(definition, heading_kind)
                scored.append((definition, max(score, 0.82)))
        if not scored:
            return VisionDocumentTypeMapResult(
                code=None,
                confidence=0.0,
                heading_kind=str(heading_kind),
                reason="below_threshold",
                method=_METHOD_RULES,
            )

    scored.sort(
        key=lambda item: (item[1], -int(getattr(item[0].classifier, "priority", 100) or 100)),
        reverse=True,
    )
    best_def, best_score = scored[0]
    runner_up_code: str | None = None
    runner_up_score: float | None = None
    if len(scored) > 1:
        runner_up_code = (scored[1][0].code or "").strip().upper() or None
        runner_up_score = scored[1][1]
        if (best_score - runner_up_score) < _AMBIGUITY_MARGIN:
            return VisionDocumentTypeMapResult(
                code=None,
                confidence=0.0,
                heading_kind=str(heading_kind),
                reason="ambiguous",
                method=_METHOD_RULES,
                runner_up_code=runner_up_code,
                runner_up_score=runner_up_score,
            )

    code = (best_def.code or "").strip().upper() or None
    if not code:
        return VisionDocumentTypeMapResult(
            code=None,
            confidence=0.0,
            heading_kind=str(heading_kind),
            reason="below_threshold",
            method=_METHOD_RULES,
        )

    return VisionDocumentTypeMapResult(
        code=code,
        confidence=round(float(best_score), 4),
        heading_kind=str(heading_kind),
        reason="matched",
        method=_METHOD_RULES,
        runner_up_code=runner_up_code,
        runner_up_score=runner_up_score,
    )


_INVOICE_LIKE_HEADING_KINDS = frozenset(
    {"invoice", "tax_invoice", "commercial_invoice"}
)

# Explicit claim / reimbursement cues — weak tokens like bare "meal" or "claim"
# must not flip a tax invoice onto a Team Expenses catalogue DT.
_STRONG_TEAM_CLAIM_RE = re.compile(
    r"(?i)(expense[\s_-]?claim|reimburse(?:ment)?|claim[\s_-]?form|"
    r"claim[\s_-]?receipt|team[\s_-]?expense)"
)


def has_strong_team_expense_claim_evidence(
    *,
    document_heading: str = "",
    canonical_document_type: str = "",
    invoice: Any | None = None,
) -> bool:
    """True when text/filename clearly indicates an employee claim (not a tax invoice)."""
    parts: list[str] = [
        (document_heading or "").strip(),
        (canonical_document_type or "").strip(),
    ]
    if invoice is not None:
        parts.append(str(getattr(invoice, "email_attachment_name", None) or "").strip())
        fields = getattr(invoice, "extracted_fields", None)
        if isinstance(fields, dict):
            for key in (
                "document_heading",
                "canonical_document_type",
                "document_type",
                "ocr_text",
                "full_text",
            ):
                val = fields.get(key)
                if val is not None and str(val).strip():
                    parts.append(str(val).strip())
    blob = "\n".join(p for p in parts if p)
    return bool(blob and _STRONG_TEAM_CLAIM_RE.search(blob))


def _pool_excluding_team_expenses_without_claim(
    pool: Sequence[DocumentTypeDefinition],
    *,
    heading_kind: str | None,
    document_heading: str,
    canonical_document_type: str,
    invoice: Any | None,
    force_team_expenses: bool = False,
) -> list[DocumentTypeDefinition]:
    """Drop Team Expenses DTs for upload, or on invoice-like headings without claim cues.

    When ``force_team_expenses`` is set (known employee on email/WhatsApp/Viber),
    keep TE catalogue rows so receipts / POS slips / tax-invoice-shaped claims can
    map without requiring explicit "expense claim" title wording.
    """
    from app.services.classification.document_type_catalog import (
        is_team_expenses_document_type,
    )
    from app.services.purchase.team_expense_route_policy import (
        team_expenses_blocked_for_upload,
    )

    rows = list(pool)
    if force_team_expenses:
        return rows
    if invoice is not None and team_expenses_blocked_for_upload(invoice):
        return [dt for dt in rows if not is_team_expenses_document_type(dt)]
    if (heading_kind or "") not in _INVOICE_LIKE_HEADING_KINDS:
        return rows
    if has_strong_team_expense_claim_evidence(
        document_heading=document_heading,
        canonical_document_type=canonical_document_type,
        invoice=invoice,
    ):
        return rows
    return [dt for dt in rows if not is_team_expenses_document_type(dt)]


def _resolve_force_team_expenses(
    *,
    invoice: Any | None,
    employees: Sequence[Any] | None,
    force_team_expenses: bool | None,
) -> bool:
    if force_team_expenses is not None:
        return bool(force_team_expenses)
    if invoice is None:
        return False
    from app.services.purchase.team_expense_route_policy import should_force_team_expenses

    return should_force_team_expenses(invoice, employees)


def _team_expense_channel_map_result(
    *,
    invoice: Any | None,
    document_types: Sequence[DocumentTypeDefinition],
    heading_kind: str | None,
    rule_reason: str | None = None,
    prior_code: str | None = None,
    prior_confidence: float | None = None,
) -> VisionDocumentTypeMapResult | None:
    """Pick claim vs advance TE DT for employee-channel force path."""
    from app.schemas.rule_book_config import TEAM_EXPENSE_KIND_CLAIM
    from app.services.purchase.team_expense_route_policy import (
        infer_preferred_team_expense_kind,
        primary_team_expenses_document_type,
    )

    preferred = infer_preferred_team_expense_kind(invoice, document_types)
    preferred_code = (prior_code or "").strip().upper() or None
    primary = primary_team_expenses_document_type(
        document_types,
        preferred_kind=preferred or TEAM_EXPENSE_KIND_CLAIM,
        preferred_code=preferred_code,
    )
    if primary is None:
        return None
    code = (primary.code or "").strip().upper() or None
    if not code:
        return None
    runner_up = (prior_code or "").strip().upper() or None
    return VisionDocumentTypeMapResult(
        code=code,
        confidence=0.95,
        heading_kind=heading_kind,
        reason="employee_channel_forced",
        method=_METHOD_TE_CHANNEL,
        rule_reason=rule_reason,
        runner_up_code=runner_up,
        runner_up_score=prior_confidence if runner_up else None,
        llm_reasoning=(
            "Known employee on email/WhatsApp/Viber: catalogue Team Expenses DT "
            f"({preferred or TEAM_EXPENSE_KIND_CLAIM})."
        ),
    )


def map_vision_via_configured_classifiers(
    *,
    invoice: Any,
    document_types: Sequence[DocumentTypeDefinition],
    heading_kind: str | None,
    rule_fail_reason: str,
) -> VisionDocumentTypeMapResult:
    """Deterministic tenant classifier match over persisted vision fields.

    Uses Rule Book recognition signals (and playbook-recommended identity
    signals when a DT only has playbookProfile). Field checks like
    ``has_po_reference`` separate PO-goods from non-PO invoice DTs without
    scraping prompt English.
    """
    from app.services.classification.segment_heading_classification import (
        list_heading_aware_document_type_matches,
        parse_segment_heading_kind,
    )
    from app.services.invoice.invoice_data import invoice_data_from_invoice

    parsed = invoice_data_from_invoice(invoice)
    matches = list_heading_aware_document_type_matches(
        list(document_types),
        invoice=invoice,
        parsed=parsed,
        heading_kind=parse_segment_heading_kind(heading_kind),
    )
    if not matches:
        return VisionDocumentTypeMapResult(
            code=None,
            confidence=0.0,
            heading_kind=heading_kind,
            reason="classifier_no_match",
            method=_METHOD_CLASSIFIER,
            rule_reason=rule_fail_reason,
        )

    definition, _source = matches[0]
    code = (definition.code or "").strip().upper() or None
    if not code:
        return VisionDocumentTypeMapResult(
            code=None,
            confidence=0.0,
            heading_kind=heading_kind,
            reason="classifier_no_match",
            method=_METHOD_CLASSIFIER,
            rule_reason=rule_fail_reason,
        )

    try:
        confidence = float(getattr(definition.classifier, "confidence", 0.85) or 0.85)
    except (TypeError, ValueError):
        confidence = 0.85
    runner_up = matches[1][0] if len(matches) > 1 else None
    return VisionDocumentTypeMapResult(
        code=code,
        confidence=round(min(max(confidence, 0.0), 1.0), 4),
        heading_kind=heading_kind,
        reason="classifier_matched",
        method=_METHOD_CLASSIFIER,
        rule_reason=rule_fail_reason,
        runner_up_code=(runner_up.code or "").strip().upper() or None
        if runner_up is not None
        else None,
    )


def _allowed_catalogue_codes(document_types: Sequence[DocumentTypeDefinition]) -> set[str]:
    return {
        (dt.code or "").strip().upper()
        for dt in document_types
        if getattr(dt, "enabled", True) and (dt.code or "").strip()
    }


def _parse_llm_confidence(raw: Any) -> float:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return 0.0
    if value > 1.0 and value <= 100.0:
        value = value / 100.0
    return max(0.0, min(1.0, value))


def _role_perspective_pool(
    document_types: Sequence[DocumentTypeDefinition],
    *,
    heading_kind: str | None,
    invoice: Any | None,
) -> list[DocumentTypeDefinition]:
    from app.services.classification.document_role_resolve_service import (
        filter_document_types_for_perspective,
        filter_document_types_for_role,
        perspective_from_invoice,
        resolve_document_role,
    )

    doc_role = resolve_document_role(
        heading_kind=heading_kind,
        filename=(getattr(invoice, "email_attachment_name", None) if invoice else None),
        invoice=invoice,
    )
    pool = filter_document_types_for_role(document_types, doc_role)
    pool = filter_document_types_for_perspective(
        pool, perspective_from_invoice(invoice)
    )
    return pool


def _org_tenant_block(org: Any | None) -> dict[str, Any]:
    if org is None:
        return {}
    return {
        "legal_name": getattr(org, "legal_name", "") or "",
        "abn": getattr(org, "abn", "") or "",
        "aliases": list(getattr(org, "aliases", None) or []),
        "default_perspective": getattr(org, "default_perspective", "") or "",
        "intake_summary": getattr(org, "intake_summary", "") or "",
        "classification_hints": getattr(org, "classification_hints", "") or "",
    }


def _few_shot_rows(few_shots: Sequence[dict[str, str]] | None) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for raw in list(few_shots or [])[:5]:
        if not isinstance(raw, dict):
            continue
        human = str(raw.get("human_confirmed_dt") or "").strip().upper()
        if not human:
            continue
        rows.append(
            {
                "document_heading": str(raw.get("document_heading") or "").strip()[:120],
                "human_confirmed_dt": human,
                "llm_suggested_dt": str(raw.get("llm_suggested_dt") or "").strip().upper(),
                "note": str(raw.get("note") or "").strip()[:240],
            }
        )
    return rows


async def _try_tenant_heading_learning(
    *,
    session: Any,
    tenant_id: UUID,
    document_heading: str,
    document_types: Sequence[DocumentTypeDefinition],
    heading_kind: str | None,
    invoice: Any | None,
    vendor_key: str | None,
    rule_reason: str,
) -> VisionDocumentTypeMapResult | None:
    """Exact normalized heading → prior reviewer DT (tenant synonym memory)."""
    from app.services.classification.classification_learning_service import (
        learned_document_type_for_heading,
    )
    from app.services.classification.document_role_resolve_service import (
        filter_document_types_for_perspective,
        perspective_from_invoice,
    )

    enabled = [dt for dt in document_types if getattr(dt, "enabled", True)]
    # Prefer role+perspective pool when kind known; else perspective-only; else all.
    pool = _role_perspective_pool(
        enabled, heading_kind=heading_kind, invoice=invoice
    )
    if heading_kind and not pool:
        # Role says no card — do not learn around that structural guard.
        return None
    if not pool:
        pool = filter_document_types_for_perspective(
            enabled, perspective_from_invoice(invoice)
        ) or enabled
    allowed = _allowed_catalogue_codes(pool)
    if not allowed:
        return None

    hit = await learned_document_type_for_heading(
        session,
        tenant_id=tenant_id,
        document_heading=document_heading,
        valid_dt_codes=allowed,
        vendor_key=vendor_key,
    )
    if hit is None:
        return None
    code, confidence = hit
    return VisionDocumentTypeMapResult(
        code=code,
        confidence=round(float(confidence), 4),
        heading_kind=heading_kind,
        reason="learning_matched",
        method=_METHOD_LEARNING,
        rule_reason=rule_reason,
    )


async def _llm_pick_catalogue_dt(
    *,
    document_heading: str,
    canonical_document_type: str,
    heading_kind: str | None,
    rule_fail_reason: str,
    document_types: Sequence[DocumentTypeDefinition],
    org: Any | None = None,
    few_shots: Sequence[dict[str, str]] | None = None,
    perspective: str | None = None,
    document_summary: str = "",
    document_role_hints: dict[str, str] | None = None,
    invoice: Any | None = None,
) -> VisionDocumentTypeMapResult:
    from app.config import get_settings
    from app.services.extraction.azure_openai_client import chat_json_async
    from app.services.extraction.llm_catalogue_rows import build_llm_catalogue_rows
    from app.services.invoice.vision_type_suggest import (
        document_role_hints_from_invoice,
        document_summary_from_invoice,
    )
    from app.services.prompt_registry.service import resolve_system_prompt_text

    enabled = [dt for dt in document_types if getattr(dt, "enabled", True)]
    allowed = _allowed_catalogue_codes(enabled)
    if not allowed:
        return VisionDocumentTypeMapResult(
            code=None,
            confidence=0.0,
            heading_kind=heading_kind,
            reason="empty_catalogue",
            method=_METHOD_LLM,
            rule_reason=rule_fail_reason,
        )

    summary = (document_summary or "").strip() or document_summary_from_invoice(invoice)
    hints = dict(document_role_hints or {}) or document_role_hints_from_invoice(invoice)

    system = resolve_system_prompt_text(_PROMPT_KEY)
    user: dict[str, Any] = {
        "task": "map_vision_label_to_catalogue_dt",
        "document_heading": (document_heading or "").strip(),
        "canonical_document_type": (canonical_document_type or "").strip(),
        "document_summary": summary[:1200],
        "document_role_hints": hints,
        "heading_kind": heading_kind or "",
        "rule_fail_reason": rule_fail_reason,
        "perspective": (perspective or "").strip().lower(),
        "tenant": _org_tenant_block(org),
        "few_shot_examples": _few_shot_rows(few_shots),
        "catalogue": build_llm_catalogue_rows(enabled),
        "output_keys": ["suggested_dt", "confidence", "reasoning"],
    }

    settings = get_settings()
    try:
        raw = await chat_json_async(
            system=system,
            user=json.dumps(user, default=str),
            timeout_seconds=settings.runtime_llm_timeout_seconds,
            require_runtime=True,
        )
    except Exception as exc:
        logger.warning("vision_dt_map_llm_error", error=str(exc), reason=rule_fail_reason)
        return VisionDocumentTypeMapResult(
            code=None,
            confidence=0.0,
            heading_kind=heading_kind,
            reason="llm_error",
            method=_METHOD_LLM,
            rule_reason=rule_fail_reason,
            llm_reasoning=str(exc)[:300],
        )

    if not isinstance(raw, dict):
        return VisionDocumentTypeMapResult(
            code=None,
            confidence=0.0,
            heading_kind=heading_kind,
            reason="llm_unavailable",
            method=_METHOD_LLM,
            rule_reason=rule_fail_reason,
        )

    suggested = str(raw.get("suggested_dt") or "").strip().upper()
    confidence = _parse_llm_confidence(raw.get("confidence"))
    reasoning = str(raw.get("reasoning") or "").strip()[:500] or None

    if not suggested:
        return VisionDocumentTypeMapResult(
            code=None,
            confidence=confidence,
            heading_kind=heading_kind,
            reason="llm_empty",
            method=_METHOD_LLM,
            rule_reason=rule_fail_reason,
            llm_reasoning=reasoning,
        )

    if suggested not in allowed:
        return VisionDocumentTypeMapResult(
            code=None,
            confidence=0.0,
            heading_kind=heading_kind,
            reason="llm_rejected",
            method=_METHOD_LLM,
            rule_reason=rule_fail_reason,
            llm_reasoning=f"invalid_code:{suggested}" + (f"; {reasoning}" if reasoning else ""),
        )

    if confidence < _LLM_MIN_CONFIDENCE:
        return VisionDocumentTypeMapResult(
            code=None,
            confidence=confidence,
            heading_kind=heading_kind,
            reason="llm_rejected",
            method=_METHOD_LLM,
            rule_reason=rule_fail_reason,
            llm_reasoning=f"low_confidence:{confidence}" + (f"; {reasoning}" if reasoning else ""),
        )

    return VisionDocumentTypeMapResult(
        code=suggested,
        confidence=round(confidence, 4),
        heading_kind=heading_kind,
        reason="llm_matched",
        method=_METHOD_LLM,
        rule_reason=rule_fail_reason,
        llm_reasoning=reasoning,
    )


async def map_vision_label_to_document_type_with_llm_fallback(
    *,
    document_heading: str,
    canonical_document_type: str,
    document_types: Sequence[DocumentTypeDefinition],
    human_locked_dt: str = "",
    invoice: Any | None = None,
    session: Any | None = None,
    tenant_id: UUID | None = None,
    org: Any | None = None,
    few_shots: Sequence[dict[str, str]] | None = None,
    vendor_key: str | None = None,
    employees: Sequence[Any] | None = None,
    force_team_expenses: bool | None = None,
) -> VisionDocumentTypeMapResult:
    """Hybrid: rules → tenant heading learning → classifiers → LLM catalogue pick.

    Learning uses exact normalized title matches from prior reviewer confirmations
    (synonyms / org-specific naming). LLM receives the same few-shots + org block
    when deterministic scoring fails. Structural ``no_dt_for_role_*`` and human
    locks are never bypassed — except known employee email/WhatsApp/Viber senders,
    which always resolve to a catalogue Team Expenses DT (claim vs advance).
    """
    from app.services.classification.document_role_resolve_service import (
        perspective_from_invoice,
    )

    rule = map_vision_label_to_document_type(
        document_heading=document_heading,
        canonical_document_type=canonical_document_type,
        document_types=document_types,
        human_locked_dt=human_locked_dt,
        invoice=invoice,
    )
    if rule.reason == "human_locked":
        return rule

    from app.services.classification.catalogue_title_match import (
        _TITLE_MATCH_THRESHOLD,
    )

    if (
        rule.reason == "catalogue_title_matched"
        and rule.code
        and rule.confidence >= _TITLE_MATCH_THRESHOLD
    ):
        return rule

    force_te = _resolve_force_team_expenses(
        invoice=invoice,
        employees=employees,
        force_team_expenses=force_team_expenses,
    )
    if force_te:
        forced = _team_expense_channel_map_result(
            invoice=invoice,
            document_types=document_types,
            heading_kind=rule.heading_kind,
            rule_reason=rule.reason,
            prior_code=rule.code,
            prior_confidence=rule.confidence if rule.code else None,
        )
        if forced is not None:
            return forced

    # Never learn/LLM into a commercial DT when role resolution already said
    # there is no supporting PO/GRN/SO/DN card in the catalogue.
    if (rule.reason or "").startswith("no_dt_for_role_"):
        return rule

    if session is not None and tenant_id is not None:
        learned = await _try_tenant_heading_learning(
            session=session,
            tenant_id=tenant_id,
            document_heading=document_heading or "",
            document_types=document_types,
            heading_kind=rule.heading_kind,
            invoice=invoice,
            vendor_key=vendor_key,
            rule_reason=rule.reason,
        )
        if learned is not None and learned.code:
            return replace(
                learned,
                runner_up_code=rule.code or rule.runner_up_code,
                runner_up_score=rule.confidence if rule.code else rule.runner_up_score,
            )

    invoice_like = (rule.heading_kind or "") in _INVOICE_LIKE_HEADING_KINDS
    from app.services.invoice.vision_type_suggest import document_summary_from_invoice
    from app.services.purchase.po_reference import effective_po_reference
    from app.services.sales.so_reference import effective_so_reference

    summary_text = document_summary_from_invoice(invoice)
    has_distinguishing_link = bool(
        effective_po_reference(getattr(invoice, "po_reference", None) if invoice else None)
        or effective_so_reference(getattr(invoice, "so_reference", None) if invoice else None)
    )
    # Ambiguous/weak heading + summary: prefer LLM over a generic classifier win,
    # unless link columns are already seeded (classifier can resolve PO vs Non-PO).
    prefer_llm_over_classifier = bool(
        summary_text
        and rule.reason in _LLM_FALLBACK_REASONS
        and not has_distinguishing_link
    )

    if (
        invoice is not None
        and not prefer_llm_over_classifier
        and (rule.reason in _LLM_FALLBACK_REASONS or invoice_like)
    ):
        classifier_pool = _role_perspective_pool(
            document_types, heading_kind=rule.heading_kind, invoice=invoice
        )
        classifier_pool = _pool_excluding_team_expenses_without_claim(
            classifier_pool or document_types,
            heading_kind=rule.heading_kind,
            document_heading=document_heading or "",
            canonical_document_type=canonical_document_type or "",
            invoice=invoice,
            force_team_expenses=force_te,
        )
        classifier = map_vision_via_configured_classifiers(
            invoice=invoice,
            document_types=classifier_pool or document_types,
            heading_kind=rule.heading_kind,
            rule_fail_reason=rule.reason
            if rule.reason in _LLM_FALLBACK_REASONS
            else "field_refine",
        )
        if classifier.reason == "classifier_matched" and classifier.code:
            from app.services.classification.document_type_catalog import (
                get_document_type_definition,
                is_team_expenses_document_type,
            )

            matched_defn = get_document_type_definition(
                classifier.code, document_types=document_types
            )
            allow_team = (
                force_te
                or not invoice_like
                or not is_team_expenses_document_type(matched_defn)
                or has_strong_team_expense_claim_evidence(
                    document_heading=document_heading or "",
                    canonical_document_type=canonical_document_type or "",
                    invoice=invoice,
                )
            )
            if allow_team:
                return replace(
                    classifier,
                    runner_up_score=classifier.runner_up_score or rule.runner_up_score,
                )

    # Prefer LLM + document summary when heading rules are ambiguous/weak,
    # or when we skipped a generic classifier win because summary is available.
    run_llm = rule.reason in _LLM_FALLBACK_REASONS or prefer_llm_over_classifier
    if not run_llm:
        return rule

    llm_pool = _role_perspective_pool(
        document_types, heading_kind=rule.heading_kind, invoice=invoice
    )
    llm_pool = _pool_excluding_team_expenses_without_claim(
        llm_pool or document_types,
        heading_kind=rule.heading_kind,
        document_heading=document_heading or "",
        canonical_document_type=canonical_document_type or "",
        invoice=invoice,
        force_team_expenses=force_te,
    )
    if rule.heading_kind and not llm_pool:
        return rule

    canonical = derive_canonical_document_type(
        document_heading=document_heading or "",
        canonical_document_type=canonical_document_type or "",
    )
    llm = await _llm_pick_catalogue_dt(
        document_heading=document_heading or "",
        canonical_document_type=canonical,
        heading_kind=rule.heading_kind,
        rule_fail_reason=rule.reason,
        document_types=llm_pool or document_types,
        org=org,
        few_shots=few_shots,
        perspective=perspective_from_invoice(invoice),
        document_summary=summary_text,
        invoice=invoice,
    )
    if llm.reason == "llm_matched" and llm.code:
        return replace(
            llm,
            runner_up_code=rule.runner_up_code,
            runner_up_score=rule.runner_up_score,
        )
    if llm.reason in {"llm_empty", "llm_rejected", "llm_error", "llm_unavailable"}:
        return replace(
            llm,
            runner_up_code=rule.runner_up_code,
            runner_up_score=rule.runner_up_score,
        )
    return rule
