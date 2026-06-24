"""Analyze uploaded sample files and propose document-type settings."""

from __future__ import annotations

import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

from app.models.invoice import Invoice, InvoiceStatus
from app.services.invoice_data import InvoiceData
from app.schemas.document_type_sample_analysis import (
    DocumentTypeSampleFileResult,
    DocumentTypeSampleProposal,
    ValidationRuleProposal,
)
from app.services.document_type_recognition_signals import (
    detect_recognition_signals,
    infer_absent_fields,
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


@dataclass(frozen=True)
class ParsedDocumentSample:
    filename: str
    invoice: Invoice
    parsed: InvoiceData
    confidence: str | None


def _parse_sample(filename: str, content: bytes) -> tuple[Invoice, InvoiceData, str | None]:
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
    return invoice, parsed, confidence


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
        invoice, parsed, confidence = _parse_sample(filename, content)
        return ParsedDocumentSample(
            filename=filename,
            invoice=invoice,
            parsed=parsed,
            confidence=confidence,
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

    profiles = []
    sample_rows: list[DocumentTypeSampleFileResult] = []
    notes: list[str] = list(parse_notes or [])
    headings: list[str] = []

    for sample in parsed_samples:
        profile = detect_recognition_signals(
            filename=sample.filename,
            invoice=sample.invoice,
            parsed=sample.parsed,
        )
        profiles.append(profile)
        if profile.document_heading:
            headings.append(profile.document_heading)
        sample_rows.append(
            DocumentTypeSampleFileResult(
                filename=profile.filename,
                recognition_signals=sorted(profile.signals),
                extraction_fields=sorted(profile.extraction_fields),
                document_heading=profile.document_heading,
                parse_confidence=sample.confidence,
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
    playbook = infer_playbook_profile(merged_signals)
    absent = infer_absent_fields(merged_signals)
    klass, posting, route_target = infer_document_metadata(playbook, bundle_role=bundle_role)
    preset = preset_for_profile(playbook)
    validation_profile = _validation_profile_for_playbook(playbook)
    validation_rules = default_validation_rules_for_profile(validation_profile or "standard")
    bundle_mandatory, bundle_conditional = suggest_bundle_members(playbook)

    required = [
        key
        for key in merged_fields
        if key not in {"document_text", "attachment_name", "document_heading"}
    ]
    primary_heading = headings[0] if headings else None
    suggested_title, suggested_short_title = suggest_title_from_heading(primary_heading)

    if len(profiles) > 1:
        notes.insert(
            0,
            f"Combined {len(profiles)} samples — classifier uses signals shared by all files when possible, otherwise any matching signal.",
        )
    if not merged_signals:
        notes.append("No recognition signals detected — check OCR quality or add clearer samples.")
    if not merged_fields:
        notes.append("No extraction fields detected — document text may be empty or unreadable.")

    per_file_signals = {row.filename: set(row.recognition_signals) for row in sample_rows}
    if len(per_file_signals) > 1:
        all_sets = list(per_file_signals.values())
        common = set.intersection(*all_sets) if all_sets else set()
        if common and common != merged_signals:
            notes.append(
                "Signals on every sample: "
                + ", ".join(sorted(common))
                + ". Others appear on some files only.",
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
    )


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
