"""Analyze uploaded sample files and propose document-type settings."""

from __future__ import annotations

import math
import tempfile
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from app.models.invoice import Invoice, InvoiceStatus
from app.schemas.document_layout import DocumentLayoutResult
from app.services.document_type_sample_types import ParsedDocumentSample
from app.services.invoice_data import InvoiceData
from app.schemas.document_type import DocumentTypeDefinition
from app.schemas.document_type_sample_analysis import (
    DocumentTypeSampleFileResult,
    DocumentTypeSampleProposal,
    RecognitionSignalDetail,
    ValidationRuleProposal,
)
from app.services.document_type_recognition_signals import (
    NO_SHARED_IDENTITY_NOTE,
    detect_mixed_family_note,
    detect_recognition_signals,
    default_required_field_candidates,
    infer_absent_fields,
    infer_document_family,
    infer_document_metadata,
    infer_playbook_profile,
    infer_purchase_bundle_role,
    merge_signals_for_classifier_profiles,
    suggest_bundle_members,
    suggest_one_line,
    suggest_title_from_heading,
)
from app.services.pdf_parser import parse_invoice_for_sample
from app.services.playbook_profile_catalog import preset_for_profile
from app.services.heading_kind_recognition import resolve_playbook_profile
from app.services.recognition_signal_catalog import (
    describe_signals,
    suggest_missing_identity_signals,
    weak_signal_warning,
)
from app.services.sample_cluster_service import select_primary_cluster_samples
from app.services.validation_rule_catalog import default_validation_rules_for_profile

_ALLOWED_SUFFIXES = {".pdf", ".jpg", ".jpeg", ".png", ".docx"}
_MAX_SAMPLES = 10
_PARSE_WORKERS = 4

_FIELD_ORDER = (
    "vendor",
    "abn",
    "invoice_no",
    "invoice_date",
    "due_date",
    "po_reference",
    "line_items",
    "subtotal",
    "gst",
    "total",
    "bank_details",
    "cost_centre",
    "billing_address",
    "document_heading",
    "attachment_name",
    "document_text",
)


def _union_strings(profiles: list, attr: str) -> list[str]:
    merged: set[str] = set()
    for profile in profiles:
        merged.update(getattr(profile, attr))
    order_index = {key: index for index, key in enumerate(_FIELD_ORDER)}
    if attr == "extraction_fields":
        return sorted(merged, key=lambda key: (order_index.get(key, 999), key))
    return sorted(merged)


def _parse_sample(
    filename: str, content: bytes
) -> tuple[Invoice, InvoiceData, str | None, DocumentLayoutResult | None, str | None]:
    suffix = Path(filename or "sample.pdf").suffix.lower() or ".pdf"
    if suffix not in _ALLOWED_SUFFIXES:
        raise ValueError(f"Unsupported file type: {suffix or 'unknown'}")

    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(content)
        tmp_path = Path(tmp.name)

    try:
        result = parse_invoice_for_sample(tmp_path)
        parsed = result.data
        confidence = str(result.confidence or "low")
        layout = result.layout
        layout_hint = result.layout_hint
    finally:
        tmp_path.unlink(missing_ok=True)

    invoice = Invoice(
        id=0,
        tenant_id=0,
        status=InvoiceStatus.PARSING,
        currency=parsed.currency or "AUD",
        email_attachment_name=filename,
        document_text=parsed.document_text,
        vendor=parsed.vendor,
        abn=parsed.abn,
        invoice_no=parsed.invoice_no,
        po_reference=parsed.po_reference,
        invoice_date=parsed.invoice_date,
        due_date=parsed.due_date,
        subtotal=parsed.subtotal,
        gst=parsed.gst,
        total=parsed.total,
        billing_address=parsed.billing_address,
        bank_bsb=parsed.bank_bsb,
        bank_account=parsed.bank_account,
        cost_centre=parsed.cost_centre,
    )
    return invoice, parsed, confidence, layout, layout_hint


def parse_document_samples(
    files: list[tuple[str, bytes]],
) -> tuple[list[ParsedDocumentSample], list[str]]:
    """Parse uploads once; returns successful samples and per-file warning notes."""
    if not files:
        raise ValueError("At least one sample file is required")
    if len(files) > _MAX_SAMPLES:
        raise ValueError(f"At most {_MAX_SAMPLES} sample files allowed")

    parsed_samples: list[ParsedDocumentSample] = []
    notes: list[str] = []
    workers = min(_PARSE_WORKERS, len(files))

    def _parse_one(filename: str, content: bytes) -> ParsedDocumentSample:
        if not content:
            raise ValueError(f"Empty file: {filename or 'upload'}")
        invoice, parsed, confidence, layout, layout_hint = _parse_sample(filename, content)
        return ParsedDocumentSample(
            filename=filename,
            invoice=invoice,
            parsed=parsed,
            confidence=confidence,
            layout=layout,
            layout_hint=layout_hint,
        )

    if workers <= 1:
        for filename, content in files:
            try:
                parsed_samples.append(_parse_one(filename, content))
            except ValueError:
                raise
            except Exception as exc:
                notes.append(f"Could not parse {filename}: {exc}")
    else:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            future_map = {
                pool.submit(_parse_one, filename, content): filename
                for filename, content in files
            }
            for future in as_completed(future_map):
                filename = future_map[future]
                try:
                    parsed_samples.append(future.result())
                except ValueError:
                    raise
                except Exception as exc:
                    notes.append(f"Could not parse {filename}: {exc}")

    parsed_samples.sort(key=lambda row: row.filename.lower())
    if not parsed_samples:
        raise ValueError("No sample files could be parsed")
    return parsed_samples, notes


def _required_fields_from_profiles(
    profiles: list,
    merged_signals: frozenset[str],
    playbook: str,
    *,
    min_ratio: float = 0.8,
) -> list[str]:
    _ = (merged_signals, playbook)
    if not profiles:
        return []
    threshold = max(1, math.ceil(len(profiles) * min_ratio))
    field_counts: Counter[str] = Counter()
    for profile in profiles:
        for field_key in profile.extraction_fields:
            field_counts[field_key] += 1
    majority = {key for key, count in field_counts.items() if count >= threshold}
    exclude = {"document_text", "attachment_name", "document_heading"}
    order_index = {key: index for index, key in enumerate(_FIELD_ORDER)}
    return sorted(majority - exclude, key=lambda key: (order_index.get(key, 999), key))


def compute_apply_ready(
    proposal: DocumentTypeSampleProposal,
    *,
    has_catalogue_preview: bool,
) -> tuple[bool, str | None]:
    effective_signals = effective_proposal_signal_ids(proposal)
    if not effective_signals:
        if any(NO_SHARED_IDENTITY_NOTE in note for note in proposal.notes):
            return False, (
                "Upload samples of the same document type — no shared identity signals."
            )
        return False, "No recognition signals detected — add clearer samples."

    if any(NO_SHARED_IDENTITY_NOTE in note for note in proposal.notes):
        return False, (
            "Samples do not share identity signals — use similar files or analyze one at a time."
        )

    if not has_catalogue_preview:
        return True, None

    for sample in proposal.samples:
        if sample.matches_expected is False:
            return False, (
                f"Proposed classifier does not match {sample.filename} — "
                "upload clearer samples or strengthen identity signals."
            )
        if sample.matches_expected is True:
            continue
        if sample.route_conflicts:
            return False, f"Signal conflicts in {sample.filename}."
        if sample.route_needs_review:
            return False, f"Catalogue preview needs review for {sample.filename}."
        top = sample.routed_confidence or 0.0
        routed = (sample.routed_code or "").strip()
        for alt in sample.route_alternatives or []:
            alt_code = str(alt.get("code", "")).strip()
            alt_conf = float(alt.get("confidence", 0) or 0)
            if alt_code and alt_code != routed and abs(alt_conf - top) <= 0.05:
                return False, (
                    f"Ambiguous routing for {sample.filename} — tighten classifier signals."
                )
    return True, None


def _validation_profile_for_playbook(playbook: str) -> str:
    if playbook in {"supporting", "non_actionable", "informational", "reconciliation"}:
        return "non_actionable"
    if playbook == "direct_expense":
        return "direct_expense"
    return ""


def _min_route_confidence(playbook: str) -> float:
    if playbook in {"master_data", "debit_note", "compliance_route"}:
        return 0.75
    if playbook in {"non_actionable", "supporting", "informational"}:
        return 0.55
    return 0.65


def _absent_fields_from_profiles(
    profiles: list,
    merged_signals: frozenset[str],
    playbook: str,
) -> list[str]:
    from_playbook = infer_absent_fields(merged_signals, playbook=playbook)
    if not profiles:
        return from_playbook
    absent: list[str] = []
    for field_key in from_playbook:
        count = sum(1 for profile in profiles if field_key in profile.extraction_fields)
        if count == 0:
            absent.append(field_key)
    return list(dict.fromkeys(absent))


def analyze_parsed_document_samples(
    parsed_samples: list[ParsedDocumentSample],
    *,
    purchase_bundle_role: str = "",
    parse_notes: list[str] | None = None,
) -> DocumentTypeSampleProposal:
    """
    Merge recognition / field settings from already-parsed samples.

    Uses deterministic OCR + heuristics (no external AI).
    Fields and signals use union across all samples so nothing is dropped.
    """
    if not parsed_samples:
        raise ValueError("No sample files could be parsed")

    working_samples, cluster_notes = select_primary_cluster_samples(parsed_samples)
    notes: list[str] = list(parse_notes or []) + cluster_notes

    profiles = []
    sample_rows: list[DocumentTypeSampleFileResult] = []
    headings: list[str] = []
    sample_bodies: list[str] = []

    for sample in working_samples:
        profile = detect_recognition_signals(
            filename=sample.filename,
            invoice=sample.invoice,
            parsed=sample.parsed,
            layout=sample.layout,
        )
        profiles.append(profile)
        if profile.document_heading:
            headings.append(profile.document_heading)
        body = (sample.parsed.document_text or "").strip()
        if body:
            sample_bodies.append(body)
        sample_rows.append(
            DocumentTypeSampleFileResult(
                filename=profile.filename,
                recognition_signals=sorted(profile.signals),
                extraction_fields=sorted(profile.extraction_fields),
                document_heading=profile.document_heading,
                parse_confidence=sample.confidence,
                signal_details=[
                    RecognitionSignalDetail.model_validate(row)
                    for row in describe_signals(sorted(profile.signals))
                ],
            )
        )

    merged_signals, layout = merge_signals_for_classifier_profiles(
        profiles,
        purchase_bundle_role=(purchase_bundle_role or "").strip().lower()
        or infer_purchase_bundle_role(frozenset(_union_strings(profiles, "signals"))),
    )
    merged_fields = _union_strings(profiles, "extraction_fields")
    bundle_role = (purchase_bundle_role or "").strip().lower() or infer_purchase_bundle_role(
        merged_signals
    )
    primary_body = sample_bodies[0] if sample_bodies else ""
    playbook = resolve_playbook_profile(
        frozenset(merged_signals),
        heading=headings[0] if headings else None,
        document_text=primary_body,
    )
    absent = _absent_fields_from_profiles(profiles, merged_signals, playbook)
    suggested = suggest_missing_identity_signals(
        frozenset(merged_signals),
        playbook=playbook,
        document_heading=headings[0] if headings else None,
        document_text=primary_body,
    )
    klass, posting, route_target = infer_document_metadata(playbook, bundle_role=bundle_role)
    preset = preset_for_profile(playbook)
    validation_profile = _validation_profile_for_playbook(playbook)
    validation_rules = default_validation_rules_for_profile(validation_profile or "standard")
    bundle_mandatory, bundle_conditional = suggest_bundle_members(playbook)

    required = _required_fields_from_profiles(profiles, merged_signals, playbook)
    primary_heading = headings[0] if headings else None
    suggested_title, suggested_short_title = suggest_title_from_heading(primary_heading)

    if len(profiles) > 1:
        notes.insert(
            0,
            f"Combined {len(profiles)} samples — classifier built from signals detected across your files (AND/OR by channel).",
        )
    mixed_note = detect_mixed_family_note(profiles)
    if mixed_note:
        notes.append(mixed_note)
    if not merged_signals:
        if len(profiles) > 1:
            notes.append(NO_SHARED_IDENTITY_NOTE)
        else:
            notes.append("No recognition signals detected — check OCR quality or add clearer samples.")
    elif not merged_fields:
        notes.append("No extraction fields detected — document text may be empty or unreadable.")
    if suggested:
        warning = weak_signal_warning(frozenset(merged_signals))
        if warning:
            notes.append(warning)

    apply_ready, apply_block_reason = compute_apply_ready(
        DocumentTypeSampleProposal(
            recognition_signals=sorted(merged_signals),
            samples=sample_rows,
            notes=notes,
        ),
        has_catalogue_preview=False,
    )

    return DocumentTypeSampleProposal(
        recognition_signals=sorted(merged_signals),
        classifier_layout=layout,
        extraction_fields=merged_fields,
        required_fields=required,
        absent_fields=absent,
        one_line=suggest_one_line(merged_signals, headings=headings),
        suggested_title=suggested_title,
        suggested_short_title=suggested_short_title,
        klass=klass,
        posting=posting,
        route_target=route_target,
        playbook_profile=playbook,
        purchase_bundle_role=bundle_role,
        match_mode=preset.match_mode,
        approval_mode=preset.approval_mode,
        validation_profile=validation_profile,
        validation_rules=[
            ValidationRuleProposal(
                code=row.code,
                enabled=row.enabled,
                severity=row.severity,
            )
            for row in validation_rules
        ],
        bundle_mandatory=bundle_mandatory,
        bundle_conditional=bundle_conditional,
        min_route_confidence=_min_route_confidence(playbook),
        samples=sample_rows,
        notes=notes,
        recognition_signal_details=[
            RecognitionSignalDetail.model_validate(row)
            for row in describe_signals(sorted(merged_signals))
        ],
        suggested_signals=[
            RecognitionSignalDetail.model_validate(row) for row in suggested
        ],
        apply_ready=apply_ready,
        apply_block_reason=apply_block_reason,
    )


def effective_proposal_signal_ids(proposal: DocumentTypeSampleProposal) -> list[str]:
    """Detected signals, plus suggested strong identity when none were detected."""
    from app.services.document_type_recognition_signals import identity_signals
    from app.services.recognition_signal_catalog import WEAK_SIGNAL_IDS

    detected = list(proposal.recognition_signals or [])
    if identity_signals(frozenset(detected)):
        return detected
    suggested = [
        row.signal_id
        for row in proposal.suggested_signals or []
        if row.strength != "weak" and row.signal_id not in WEAK_SIGNAL_IDS
    ]
    return list(dict.fromkeys([*detected, *suggested]))


def apply_sample_proposal_to_draft(
    draft: DocumentTypeDefinition,
    proposal: DocumentTypeSampleProposal,
    *,
    for_preview: bool = False,
) -> DocumentTypeDefinition:
    """Merge analyzed sample proposal into a draft type (for catalogue preview / apply)."""
    from app.services.document_classifier_builder import build_classifier_from_signals

    signals = effective_proposal_signal_ids(proposal)
    layout = proposal.classifier_layout or "grouped"
    if for_preview:
        priority = 1
    else:
        priority = draft.classifier.priority if draft.classifier.priority > 0 else 100
    classifier = build_classifier_from_signals(
        signals,
        layout,
        priority=priority,
        confidence=0.85,
        enabled=bool(signals),
    )
    updates: dict[str, object] = {
        "classifier": classifier,
        "classifier_customized": False,
        "extraction_fields": proposal.extraction_fields,
        "required_fields": proposal.required_fields,
        "absent_fields": proposal.absent_fields,
        "min_route_confidence": proposal.min_route_confidence,
        "playbook_profile": proposal.playbook_profile or draft.playbook_profile,
        "purchase_bundle_role": proposal.purchase_bundle_role or draft.purchase_bundle_role,
    }
    if proposal.one_line and draft.one_line.strip().lower() in {
        "",
        "describe how this document type is identified and processed.",
    }:
        updates["one_line"] = proposal.one_line
    if proposal.suggested_title and draft.title.strip().lower() in {
        "new document type",
        "new type",
        "custom type",
    }:
        updates["title"] = proposal.suggested_title
    if proposal.suggested_short_title and draft.short_title.strip().lower() in {
        "new document type",
        "new type",
        "custom type",
    }:
        updates["short_title"] = proposal.suggested_short_title
    return draft.model_copy(update=updates)


def analyze_document_type_samples(
    files: list[tuple[str, bytes]],
    *,
    purchase_bundle_role: str = "",
) -> DocumentTypeSampleProposal:
    parsed_samples, parse_notes = parse_document_samples(files)
    return analyze_parsed_document_samples(
        parsed_samples,
        purchase_bundle_role=purchase_bundle_role,
        parse_notes=parse_notes,
    )
