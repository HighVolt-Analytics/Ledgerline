"""Orchestrate heuristic + optional LLM sample proposals."""

from __future__ import annotations

import json
from collections.abc import Sequence

from pydantic import ValidationError

from app.schemas.document_type import DocumentTypeDefinition
from app.schemas.document_type_sample_analysis import DocumentTypeSampleProposal
from app.schemas.sample_proposal_llm import LlmSampleProposal
from app.services.extraction.azure_openai_client import chat_json, is_azure_openai_enabled
from app.services.classification.document_type_catalogue_match import match_catalogue_for_samples
from app.services.classification.document_type_recognition_signals import refine_recognition_signals
from app.services.classification.document_type_rule_engine import build_document_classifier_context
from app.services.classification.document_type_sample_types import ParsedDocumentSample
from app.services.classification.document_type_sample_analyzer import (
    analyze_parsed_document_samples,
)


def _sample_prompt_payload(
    samples: Sequence[ParsedDocumentSample],
    catalogue: Sequence[DocumentTypeDefinition],
) -> str:
    sample_rows = []
    for sample in samples:
        kv = sample.parsed.raw_fields.get("layout_kv") or {}
        sample_rows.append(
            {
                "filename": sample.filename,
                "heading": sample.parsed.document_heading,
                "layout_hint": sample.layout_hint or sample.parsed.raw_fields.get("layout_hint"),
                "fields": {
                    key: getattr(sample.parsed, key, None)
                    for key in (
                        "vendor",
                        "invoice_no",
                        "po_reference",
                        "total",
                        "abn",
                    )
                },
                "layout_kv": kv,
                "text_excerpt": (sample.parsed.document_text or "")[:2000],
            }
        )
    catalogue_rows = [
        {
            "code": defn.code,
            "title": defn.title,
            "one_line": defn.one_line,
            "playbook_profile": defn.playbook_profile,
        }
        for defn in catalogue
        if defn.enabled
    ][:40]
    return json.dumps(
        {"samples": sample_rows, "catalogue": catalogue_rows},
        default=str,
    )


_LLM_SYSTEM = """You analyze uploaded business document samples for an accounts-payable rule book.
Return JSON only with keys:
playbook_profile, recognition_signals, extraction_fields, required_fields, absent_fields,
classifier_layout, one_line, suggested_title, purchase_bundle_role, confidence, reasoning.

Use only known recognition signal ids and canonical field keys.
confidence is 0.0-1.0. reasoning is one short paragraph for the user."""


def _request_llm_proposal(
    samples: Sequence[ParsedDocumentSample],
    catalogue: Sequence[DocumentTypeDefinition],
) -> LlmSampleProposal | None:
    if not is_azure_openai_enabled():
        return None
    payload = _sample_prompt_payload(samples, catalogue)
    raw = chat_json(system=_LLM_SYSTEM, user=payload)
    if raw is None:
        return None
    try:
        return LlmSampleProposal.model_validate(raw)
    except ValidationError:
        return None


def _merge_llm_into_proposal(
    heuristic: DocumentTypeSampleProposal,
    llm: LlmSampleProposal,
    samples: Sequence[ParsedDocumentSample],
) -> DocumentTypeSampleProposal:
    merged_signals = set(heuristic.recognition_signals)
    merged_signals.update(llm.recognition_signals)
    for sample in samples:
        ctx = build_document_classifier_context(invoice=sample.invoice, parsed=sample.parsed)
        merged_signals = set(refine_recognition_signals(frozenset(merged_signals), ctx=ctx))

    extraction = sorted(set(heuristic.extraction_fields) | set(llm.extraction_fields))
    required = sorted(set(heuristic.required_fields) | set(llm.required_fields))
    absent = list(dict.fromkeys([*heuristic.absent_fields, *llm.absent_fields]))

    updates: dict[str, object] = {
        "recognition_signals": sorted(merged_signals),
        "extraction_fields": extraction,
        "required_fields": required,
        "absent_fields": absent,
        "proposal_source": "hybrid" if llm.confidence >= 0.7 else "heuristic",
        "reasoning": llm.reasoning or heuristic.reasoning,
    }
    if llm.confidence >= 0.7:
        updates.update(
            {
                "playbook_profile": llm.playbook_profile,
                "one_line": llm.one_line or heuristic.one_line,
                "classifier_layout": llm.classifier_layout,
                "purchase_bundle_role": llm.purchase_bundle_role or heuristic.purchase_bundle_role,
            }
        )
        if llm.suggested_title:
            updates["suggested_title"] = llm.suggested_title
    return heuristic.model_copy(update=updates)


def build_sample_proposal(
    parsed_samples: list[ParsedDocumentSample],
    *,
    catalogue: Sequence[DocumentTypeDefinition] | None = None,
    purchase_bundle_role: str = "",
    parse_notes: list[str] | None = None,
) -> DocumentTypeSampleProposal:
    heuristic = analyze_parsed_document_samples(
        parsed_samples,
        purchase_bundle_role=purchase_bundle_role,
        parse_notes=parse_notes,
    )
    catalogue_matches = match_catalogue_for_samples(
        parsed_samples,
        catalogue or [],
    )
    proposal = heuristic.model_copy(
        update={
            "catalogue_matches": catalogue_matches,
            "proposal_source": "heuristic",
        }
    )

    llm = _request_llm_proposal(parsed_samples, catalogue or [])
    if llm is None:
        return proposal

    merged = _merge_llm_into_proposal(proposal, llm, parsed_samples)
    notes = list(merged.notes)
    if llm.reasoning:
        notes.insert(0, f"AI suggestion: {llm.reasoning}")
    return merged.model_copy(update={"notes": notes})
