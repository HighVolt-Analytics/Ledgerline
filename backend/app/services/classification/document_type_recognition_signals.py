"""Detect recognition signals from parsed samples (aligns with frontend RecognitionSignalId)."""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.models.invoice import Invoice
from app.schemas.document_layout import DocumentLayoutResult
from app.services.extraction.document_heading_utils import extract_document_heading_signals, infer_page_document_kind
from app.services.classification.heading_kind_recognition import (
    NON_INVOICE_NUMBER_KINDS,
    infer_heading_kind,
    playbook_for_heading_kind,
    signals_for_heading_kind,
)
from app.services.classification.document_type_rule_engine import (
    DocumentClassifierContext,
    build_document_classifier_context,
)
from app.services.invoice.invoice_data import InvoiceData
from app.services.extraction.layout_field_extractor import extract_document_heading_from_layout
from app.services.purchase.purchase_document_service import (
    _attachment_suggests_grn,
    _attachment_suggests_po,
)

from app.services.classification.recognition_signal_registry import (
    SIGNAL_PICK_GROUPS,
    WEAK_SIGNAL_IDS,
    filename_detection_patterns,
    text_detection_patterns,
)

RecognitionSignalId = str

WEAK_SIGNALS: frozenset[RecognitionSignalId] = WEAK_SIGNAL_IDS

NO_SHARED_IDENTITY_NOTE = (
    "No shared document identity signals across samples — upload files of the same type "
    "(e.g. all expense receipts, all GRNs) or analyze one file at a time."
)

PURCHASE_MATCH_PLAYBOOKS = frozenset(
    {
        "po_goods",
        "po_services",
        "import_dossier",
        "freight_logistics",
        "credit_adjustment",
        "debit_note",
        "standard_transactional",
    }
)

SUPPORTING_PO_SIGNALS = frozenset({"heading_po", "text_po", "filename_po"})
SUPPORTING_GRN_SIGNALS = frozenset({"heading_grn", "text_grn", "filename_grn"})
SUPPORTING_CONTRACT_SIGNALS = frozenset(
    {
        "heading_contract",
        "text_contract",
        "filename_contract",
        "text_terms",
        "text_governing_law",
        "text_signed_behalf",
    }
)

CONTRACT_IDENTITY_SIGNALS = frozenset(
    {"heading_contract", "text_contract", "filename_contract"}
)

# Group indices for conflict resolution (same order as SIGNAL_PICK_GROUPS).
_GRP_INVOICE = 0
_GRP_PO = 1
_GRP_GRN = 2
_GRP_CONTRACT = 3
_GRP_CREDIT = 4
_GRP_DEBIT = 5
_GRP_PROFORMA = 6
_GRP_CLAIM = 7
_GRP_QUOTE = 8
_GRP_TAX_NOTICE = 9
_GRP_BANK = 10
_GRP_FREIGHT = 11
_GRP_IMPORT = 12
_GRP_INTERCOMPANY = 13
_GRP_RECURRING = 14
_GRP_UTILITY = 15
_GRP_STATEMENT = 16
_GRP_TIMESHEET = 17
_GRP_REMITTANCE = 18
_GRP_RCTI = 19
_GRP_CONSIGNMENT = 20
_GRP_DUNNING = 21
_GRP_TERMS = 22

# Groups whose documents are normally matched to transactional playbooks (invoice-like).
TRANSACTIONAL_GROUP_INDICES: frozenset[int] = frozenset(
    {_GRP_INVOICE, _GRP_CREDIT, _GRP_DEBIT, _GRP_PROFORMA, _GRP_CLAIM, _GRP_RCTI}
)

# Groups whose documents are supporting / pre-transactional / compliance (not invoice-like).
SUPPORTING_GROUP_INDICES: frozenset[int] = frozenset(
    {
        _GRP_PO,
        _GRP_GRN,
        _GRP_CONTRACT,
        _GRP_QUOTE,
        _GRP_TAX_NOTICE,
        _GRP_BANK,
        _GRP_FREIGHT,
        _GRP_IMPORT,
        _GRP_INTERCOMPANY,
        _GRP_RECURRING,
        _GRP_UTILITY,
        _GRP_STATEMENT,
        _GRP_TIMESHEET,
        _GRP_REMITTANCE,
        _GRP_CONSIGNMENT,
        _GRP_DUNNING,
        _GRP_TERMS,
    }
)

# Families that use supporting_doc layout (invoice-absence guards in classifier tree).
SUPPORTING_DOC_LAYOUT_GROUPS: frozenset[int] = frozenset(
    {_GRP_PO, _GRP_GRN, _GRP_CONTRACT, _GRP_TERMS}
)

INCOMPATIBLE_GROUP_SETS: tuple[frozenset[int], ...] = (
    frozenset({_GRP_INVOICE, _GRP_CONTRACT}),
    frozenset({_GRP_INVOICE, _GRP_PO}),
    frozenset({_GRP_INVOICE, _GRP_GRN}),
    frozenset({_GRP_PO, _GRP_GRN}),
    frozenset({_GRP_CONTRACT, _GRP_PO}),
    frozenset({_GRP_CONTRACT, _GRP_GRN}),
    frozenset({_GRP_CONTRACT, _GRP_INVOICE}),
    frozenset({_GRP_CONTRACT, _GRP_TAX_NOTICE}),
    frozenset({_GRP_CONTRACT, _GRP_PROFORMA}),
    frozenset({_GRP_CONTRACT, _GRP_QUOTE}),
    frozenset({_GRP_INVOICE, _GRP_TAX_NOTICE}),
)

_FILENAME_PATTERNS: list[tuple[RecognitionSignalId, re.Pattern[str]]] = filename_detection_patterns()
_TEXT_PATTERNS: list[tuple[RecognitionSignalId, re.Pattern[str]]] = text_detection_patterns()


@dataclass(frozen=True)
class SampleSignalProfile:
    filename: str
    signals: frozenset[RecognitionSignalId]
    extraction_fields: frozenset[str]
    document_heading: str | None


def _field_keys_from_sample(
    *,
    invoice: Invoice,
    parsed: InvoiceData,
    ctx: DocumentClassifierContext,
) -> set[str]:
    from app.services.classification.document_type_field_checks import field_is_present

    keys = (
        "vendor",
        "abn",
        "invoice_no",
        "invoice_date",
        "due_date",
        "po_reference",
        "subtotal",
        "gst",
        "total",
        "line_items",
        "bank_details",
        "cost_centre",
        "billing_address",
        "document_text",
        "document_heading",
        "attachment_name",
    )
    present: set[str] = set()
    for key in keys:
        if field_is_present(key, invoice=invoice, parsed=parsed, ctx=ctx):
            present.add(key)

    if (parsed.vendor or invoice.vendor or "").strip():
        present.add("vendor")
    if (parsed.abn or invoice.abn or "").strip():
        present.add("abn")
    if (parsed.invoice_no or invoice.invoice_no or "").strip():
        present.add("invoice_no")
    if parsed.invoice_date or invoice.invoice_date:
        present.add("invoice_date")
    if parsed.due_date or invoice.due_date:
        present.add("due_date")
    if (parsed.po_reference or invoice.po_reference or "").strip():
        present.add("po_reference")
    if parsed.subtotal is not None or invoice.subtotal is not None:
        present.add("subtotal")
    if parsed.gst is not None or invoice.gst is not None:
        present.add("gst")
    if parsed.total is not None or invoice.total is not None:
        present.add("total")
    if parsed.line_items:
        present.add("line_items")
    if (parsed.bank_bsb or invoice.bank_bsb or parsed.bank_account or invoice.bank_account):
        present.add("bank_details")
    if (parsed.cost_centre or invoice.cost_centre or "").strip():
        present.add("cost_centre")
    if (invoice.billing_address or "").strip():
        present.add("billing_address")
    if ctx.document_text.strip():
        present.add("document_text")
    if (parsed.document_heading or ctx.document_heading or "").strip():
        present.add("document_heading")
    if ctx.attachment_name.strip():
        present.add("attachment_name")
    return present


def _signals_from_stored_heading(heading: str) -> set[RecognitionSignalId]:
    """Map extracted document_heading field to identity signals (looser than body scan)."""
    cleaned = (heading or "").strip()
    if not cleaned:
        return set()
    found: set[RecognitionSignalId] = set()
    heading_signals = extract_document_heading_signals(cleaned)
    if heading_signals.has_heading_invoice:
        found.add("heading_invoice")
    if heading_signals.has_heading_po:
        found.add("heading_po")
    if heading_signals.has_heading_grn:
        found.add("heading_grn")
    if heading_signals.has_heading_contract:
        found.add("heading_contract")
    if heading_signals.has_heading_credit_note:
        found.add("text_credit_note")
    if heading_signals.has_heading_quote:
        found.add("text_quote")
    kind = heading_signals.primary_kind or infer_page_document_kind(cleaned)
    found |= set(signals_for_heading_kind(kind))
    if not found and re.search(r"(?i)\b(tax\s+invoice|commercial\s+invoice)\b", cleaned):
        found.add("heading_invoice")
    elif not found and re.search(r"(?i)\binvoice\b", cleaned):
        if not re.search(r"(?i)credit|debit|pro[\s-]?forma", cleaned):
            found.add("heading_invoice")
    return found


def detect_recognition_signals(
    *,
    filename: str,
    invoice: Invoice,
    parsed: InvoiceData,
    layout: DocumentLayoutResult | None = None,
) -> SampleSignalProfile:
    ctx = build_document_classifier_context(invoice=invoice, parsed=parsed)
    signals: set[RecognitionSignalId] = set()
    name = (filename or "").strip()
    layout_heading = extract_document_heading_from_layout(layout)

    if ctx.has_heading_po == "true":
        signals.add("heading_po")
    if ctx.has_heading_grn == "true":
        signals.add("heading_grn")
    if ctx.has_heading_contract == "true":
        signals.add("heading_contract")
    if ctx.has_heading_invoice == "true":
        signals.add("heading_invoice")
    if ctx.has_po_reference == "true":
        signals.add("has_po_reference")
    if ctx.has_invoice_no == "true":
        signals.add("has_invoice_number")
    if ctx.has_total == "true":
        signals.add("has_total_amount")

    body = ctx.document_text or ""
    has_contract_cue = (
        ctx.has_heading_contract == "true"
        or (body and re.search(r"(?i)(\bcontract\b|master service agreement|docusign)", body))
    )
    for signal_id, pattern in _FILENAME_PATTERNS:
        if name and pattern.search(name):
            signals.add(signal_id)
    for signal_id, pattern in _TEXT_PATTERNS:
        if not body or not pattern.search(body):
            continue
        if signal_id == "text_invoice" and has_contract_cue:
            if not re.search(r"(?i)\b(tax\s+invoice|commercial\s+invoice)\b", body):
                continue
        if signal_id == "text_tax_notice" and has_contract_cue:
            if not re.search(r"(?i)\b(ato|tax\s+office)\b", body):
                continue
        signals.add(signal_id)

    if name and _attachment_suggests_po(name):
        signals.add("filename_po")
    if name and _attachment_suggests_grn(name):
        signals.add("filename_grn")

    subject = (invoice.email_subject or "").strip()
    if subject and re.search(r"(?i)\binvoice\b", subject):
        signals.add("text_invoice")

    heading_label = (
        layout_heading or (parsed.document_heading or ctx.document_heading or "").strip()
    )
    if heading_label:
        heading_signals = extract_document_heading_signals(heading_label)
        if heading_signals.has_heading_invoice:
            signals.add("heading_invoice")
        if heading_signals.has_heading_po:
            signals.add("heading_po")
        if heading_signals.has_heading_grn:
            signals.add("heading_grn")
        if heading_signals.has_heading_contract:
            signals.add("heading_contract")
    signals |= _signals_from_stored_heading(heading_label)

    if parsed.line_items and (parsed.total is not None or invoice.total is not None):
        signals.add("has_total_amount")
    elif parsed.line_items and len(parsed.line_items) >= 1:
        signals.add("has_total_amount")

    layout_hint = (parsed.raw_fields.get("layout_hint") or "").strip().lower()
    if layout_hint == "po" and not signals & SUPPORTING_PO_SIGNALS:
        if heading_label and re.search(r"(?i)purchase\s+order", heading_label):
            signals.add("heading_po")
    if layout_hint == "grn" and not signals & SUPPORTING_GRN_SIGNALS:
        if heading_label and re.search(r"(?i)(goods\s+receipt|delivery)", heading_label):
            signals.add("heading_grn")

    body_kind = infer_heading_kind(heading=heading_label, document_text=body)
    signals |= set(signals_for_heading_kind(body_kind))
    if body_kind in NON_INVOICE_NUMBER_KINDS:
        signals.discard("has_invoice_number")

    signals = set(refine_recognition_signals(frozenset(signals), ctx=ctx))

    extraction = _field_keys_from_sample(invoice=invoice, parsed=parsed, ctx=ctx)
    if layout is not None and layout.has_tables and "line_items" not in extraction and parsed.line_items:
        extraction.add("line_items")
    heading = heading_label or None
    return SampleSignalProfile(
        filename=name,
        signals=frozenset(signals),
        extraction_fields=frozenset(extraction),
        document_heading=heading,
    )


def identity_signals(signals: frozenset[RecognitionSignalId]) -> frozenset[RecognitionSignalId]:
    return frozenset(s for s in signals if s not in WEAK_SIGNALS)


def _signal_channel_rank(signal_id: RecognitionSignalId) -> int:
    """Higher = stronger identity cue (heading beats filename beats body text)."""
    if signal_id.startswith("heading_"):
        return 3
    if signal_id.startswith("filename_"):
        return 2
    if signal_id in WEAK_SIGNALS:
        return 0
    return 1


def _single_file_group_strength(group_index: int, signals: set[RecognitionSignalId]) -> int:
    group = set(SIGNAL_PICK_GROUPS[group_index])
    matched = signals & group
    if not matched:
        return 0
    return max(_signal_channel_rank(signal_id) for signal_id in matched)


def _compatible_weak_signals(
    refined: set[RecognitionSignalId],
    verified: set[RecognitionSignalId],
) -> set[RecognitionSignalId]:
    """Keep field-presence signals only when consistent with the winning document family."""
    weak = verified & WEAK_SIGNALS
    if not weak:
        return set()
    active = _active_group_indices(refined)
    if not active:
        return set(weak)
    if active & TRANSACTIONAL_GROUP_INDICES:
        return set(weak)
    kept = set(weak)
    kept.discard("has_invoice_number")
    if active & {_GRP_CONTRACT, _GRP_QUOTE, _GRP_TERMS, _GRP_PROFORMA, _GRP_FREIGHT, _GRP_IMPORT}:
        kept.discard("has_total_amount")
    return kept


def refine_recognition_signals(
    signals: frozenset[RecognitionSignalId] | set[RecognitionSignalId],
    *,
    ctx: DocumentClassifierContext,
) -> frozenset[RecognitionSignalId]:
    """
    Type-agnostic signal cleanup: verify cues, resolve cross-family conflicts, keep
    the strongest identity per channel group, and attach compatible weak signals.
    """
    from app.services.classification.document_classifier_builder import eval_recognition_signal

    verified = {signal_id for signal_id in signals if eval_recognition_signal(ctx, signal_id)}
    if not verified:
        return frozenset()

    kept_groups = _resolve_winning_groups([verified])
    if not kept_groups:
        return frozenset(_compatible_weak_signals(set(), verified))

    refined: set[RecognitionSignalId] = set()
    for group_index in kept_groups:
        refined |= verified & set(SIGNAL_PICK_GROUPS[group_index])
    refined |= _compatible_weak_signals(refined, verified)
    return frozenset(refined)


def _grouped_signal_ids() -> frozenset[RecognitionSignalId]:
    grouped: set[RecognitionSignalId] = set()
    for group in SIGNAL_PICK_GROUPS:
        grouped.update(group)
    return frozenset(grouped)


def _active_group_indices(signals: set[RecognitionSignalId]) -> set[int]:
    active: set[int] = set()
    for index, group in enumerate(SIGNAL_PICK_GROUPS):
        if signals & set(group):
            active.add(index)
    return active


def _group_score(group_index: int, per_file: list[set[RecognitionSignalId]]) -> int:
    group = set(SIGNAL_PICK_GROUPS[group_index])
    return sum(len(file_signals & group) for file_signals in per_file)


def _resolve_winning_groups(per_file: list[set[RecognitionSignalId]]) -> set[int]:
    if not per_file:
        return set()
    if len(per_file) == 1:
        winners = _active_group_indices(per_file[0])
    else:
        common = set.intersection(
            *[_active_group_indices(file_signals) for file_signals in per_file]
        )
        winners = common if common else set.union(
            *[_active_group_indices(s) for s in per_file]
        )
    if not winners:
        return set()

    for pair in INCOMPATIBLE_GROUP_SETS:
        present = pair & winners
        if len(present) < 2:
            continue
        if len(per_file) == 1:
            scores = {
                index: _single_file_group_strength(index, per_file[0]) for index in present
            }
        else:
            scores = {index: _group_score(index, per_file) for index in present}
        best = max(scores, key=lambda index: (scores[index], -index))
        winners -= present - {best}
    return winners


def _profiles_compatible(per_file: list[set[RecognitionSignalId]]) -> bool:
    if len(per_file) <= 1:
        return True
    common_identity = set.intersection(
        *(set(identity_signals(frozenset(s))) for s in per_file)
    )
    if common_identity:
        return True
    common_groups = set.intersection(*[_active_group_indices(s) for s in per_file])
    return bool(common_groups)


def _collect_merged_signals(
    per_file: list[set[RecognitionSignalId]],
    kept_groups: set[int],
) -> frozenset[RecognitionSignalId]:
    if not per_file:
        return frozenset()
    if not kept_groups:
        if len(per_file) == 1:
            only = per_file[0]
            weak = only & WEAK_SIGNALS
            if weak:
                return frozenset(weak)
        return frozenset()

    merged: set[RecognitionSignalId] = set()
    file_union = set().union(*per_file)

    for group_index, group in enumerate(SIGNAL_PICK_GROUPS):
        if group_index not in kept_groups:
            continue
        group_set = set(group)
        if len(per_file) == 1 or all(file_signals & group_set for file_signals in per_file):
            merged |= file_union & group_set

    if all(file_signals & WEAK_SIGNALS for file_signals in per_file):
        merged |= set().union(*(file_signals & WEAK_SIGNALS for file_signals in per_file))

    grouped = _grouped_signal_ids()
    ungrouped_on_all = set.intersection(
        *(file_signals - grouped - WEAK_SIGNALS for file_signals in per_file)
    )
    merged |= ungrouped_on_all
    return frozenset(merged)


def _merge_detected_signals(profiles: list[SampleSignalProfile]) -> frozenset[RecognitionSignalId]:
    per_file = [set(profile.signals) for profile in profiles]
    if not per_file:
        return frozenset()
    if len(per_file) > 1 and not _profiles_compatible(per_file):
        return frozenset()
    kept_groups = _resolve_winning_groups(per_file)
    return _collect_merged_signals(per_file, kept_groups)


def _uses_supporting_guards(signals: frozenset[RecognitionSignalId]) -> bool:
    available = set(signals)
    if available & (SUPPORTING_PO_SIGNALS | SUPPORTING_GRN_SIGNALS):
        if not WEAK_SIGNALS.issubset(available):
            return True
    if available & CONTRACT_IDENTITY_SIGNALS:
        if "has_invoice_number" not in available or "has_total_amount" not in available:
            return True
    return False


def _is_contract_signal_set(signals: frozenset[RecognitionSignalId]) -> bool:
    return bool(signals & SUPPORTING_CONTRACT_SIGNALS)


def infer_document_family(playbook: str) -> str:
    pb = (playbook or "").strip().lower()
    if pb in PURCHASE_MATCH_PLAYBOOKS:
        return "purchase_match"
    if pb == "direct_expense":
        return "direct_expense"
    if pb == "employee_claim":
        return "employee_claim"
    if pb in {"supporting", "informational", "reconciliation"}:
        return "supporting"
    if pb in {"pre_transactional", "non_actionable"}:
        return "pre_transactional"
    if pb in {"compliance_route", "master_data"}:
        return "compliance_master"
    return "purchase_match"


def infer_classifier_layout_for_samples(
    signals: frozenset[RecognitionSignalId],
    *,
    purchase_bundle_role: str = "",
) -> str:
    """Infer AND/OR layout from detected signal shape (works for any document family)."""
    role = (purchase_bundle_role or "").strip().lower()
    if role in {"po", "grn"}:
        return "supporting_doc"
    if _uses_supporting_guards(signals):
        return "supporting_doc"
    identity = identity_signals(signals)
    if not identity:
        return "any_signal"
    active = _active_group_indices(set(signals))
    if active & SUPPORTING_DOC_LAYOUT_GROUPS:
        return "supporting_doc"
    return "grouped"


def infer_classifier_layout(
    signals: frozenset[RecognitionSignalId],
    *,
    purchase_bundle_role: str = "",
    playbook: str = "",
    for_sample_analysis: bool = False,
) -> str:
    role = (purchase_bundle_role or "").strip().lower()
    if role in {"po", "grn"}:
        return "supporting_doc"
    if for_sample_analysis:
        return infer_classifier_layout_for_samples(signals, purchase_bundle_role=role)
    profile = (playbook or "").strip().lower() or infer_playbook_profile(signals)
    family = infer_document_family(profile)
    if family == "supporting":
        return "supporting_doc"
    if family == "purchase_match" and WEAK_SIGNALS.issubset(signals):
        return "all_signals"
    return "any_signal"


def _union_detected_signals(profiles: list[SampleSignalProfile]) -> frozenset[RecognitionSignalId]:
    return frozenset().union(*(profile.signals for profile in profiles))


def merge_signals_for_classifier_profiles(
    profiles: list[SampleSignalProfile],
    *,
    purchase_bundle_role: str = "",
) -> tuple[frozenset[RecognitionSignalId], str]:
    """
    Build classifier signals purely from what was detected in the uploaded samples.

    Uses per-file agreement and OR-channel grouping — no playbook palette or template defaults.
    """
    role = (purchase_bundle_role or "").strip().lower()
    if not profiles:
        return frozenset(), "any_signal"

    if role == "po":
        kept = {_GRP_PO}
        merged = _collect_merged_signals([set(p.signals) for p in profiles], kept)
        return merged, "supporting_doc"
    if role == "grn":
        kept = {_GRP_GRN}
        merged = _collect_merged_signals([set(p.signals) for p in profiles], kept)
        return merged, "supporting_doc"

    merged = _merge_detected_signals(profiles)
    if not merged:
        return frozenset(), "any_signal"

    layout = infer_classifier_layout_for_samples(merged, purchase_bundle_role=role)
    return merged, layout


def infer_playbook_profile(signals: frozenset[RecognitionSignalId]) -> str:
    """Onboarding-only: propose playbook from detected signals (sample analyzer)."""
    if signals & {"heading_grn", "text_grn", "filename_grn"}:
        return "supporting"
    if signals & {"heading_po", "text_po", "filename_po"}:
        if "has_invoice_number" not in signals:
            return "supporting"
    if signals & {"text_credit_note", "filename_credit_note"}:
        return "credit_adjustment"
    if signals & {"text_debit_note", "filename_debit_note"}:
        return "debit_note"
    if signals & {"text_proforma", "filename_proforma"}:
        return "pre_transactional"
    if signals & {"text_claim", "filename_claim"}:
        return "employee_claim"
    if signals & {"text_bank_change", "filename_bank_change"}:
        return "master_data"
    if signals & {"heading_contract", "text_contract", "text_governing_law", "filename_contract"}:
        return "supporting"
    if signals & {"text_quote", "filename_quote"}:
        return "non_actionable"
    if signals & {"text_freight", "filename_freight"}:
        return "freight_logistics"
    if signals & {"text_import", "filename_import"}:
        return "import_dossier"
    if signals & {"heading_invoice", "text_invoice", "filename_invoice"}:
        if "has_po_reference" in signals:
            return "po_goods"
        if "has_invoice_number" in signals and "has_po_reference" not in signals:
            return "direct_expense"
        return "standard_transactional"
    if signals & {"text_tax_notice", "filename_tax_notice"}:
        return "compliance_route"
    if {"has_po_reference", "has_invoice_number", "has_total_amount"}.issubset(signals):
        return "po_goods"
    if "has_invoice_number" in signals and "has_po_reference" not in signals:
        return "direct_expense"
    return "standard_transactional"


def infer_purchase_bundle_role(signals: frozenset[RecognitionSignalId]) -> str:
    if signals & {"heading_grn", "text_grn", "filename_grn"}:
        return "grn"
    if signals & {"heading_po", "text_po", "filename_po"}:
        if "has_invoice_number" not in signals:
            return "po"
    return ""


def infer_absent_fields(
    signals: frozenset[RecognitionSignalId],
    *,
    playbook: str = "",
) -> list[str]:
    absent: list[str] = []
    profile = (playbook or "").strip().lower() or infer_playbook_profile(signals)
    family = infer_document_family(profile)

    if signals & {"heading_po", "text_po", "filename_po", "heading_grn", "text_grn", "filename_grn"}:
        absent.append("invoice_no")
    if signals & {"text_quote", "filename_quote", "text_proforma", "filename_proforma"}:
        absent.extend(["invoice_no", "total"])
    if family == "direct_expense" and "has_po_reference" not in signals:
        absent.append("po_reference")
    if profile == "credit_adjustment" and "has_po_reference" not in signals:
        absent.append("po_reference")
    if family == "supporting" and signals & {
        "heading_contract",
        "text_contract",
        "text_governing_law",
        "filename_contract",
    }:
        absent.extend(["invoice_no", "total"])

    return list(dict.fromkeys(absent))


def default_required_field_candidates(
    family: str,
    signals: frozenset[RecognitionSignalId],
) -> frozenset[str]:
    """Legacy hook — required fields now come from extraction majority in sample analyzer."""
    _ = (family, signals)
    return frozenset()


def detect_mixed_family_note(profiles: list[SampleSignalProfile]) -> str | None:
    if len(profiles) < 2:
        return None
    per_file = [set(profile.signals) for profile in profiles]
    if not _profiles_compatible(per_file):
        return (
            "Mixed document cues across samples — use files of the same type for a reliable classifier."
        )
    return None


def infer_document_metadata(playbook: str, *, bundle_role: str = "") -> tuple[str, str, str]:
    """Return (klass, posting, route_target) from playbook profile."""
    from app.services.classification.document_type_catalog import (
        ROUTE_EXPENSES,
        ROUTE_PURCHASE,
        ROUTE_SALES,
        ROUTE_TEAM,
        ROUTE_VAULT,
    )
    from app.services.classification.document_type_klass import (
        KLASS_NON_TRANSACTIONAL,
        KLASS_TRANSACTIONAL,
    )

    role = (bundle_role or "").strip().lower()
    if role in {"po", "grn"}:
        return KLASS_NON_TRANSACTIONAL, "No", ROUTE_PURCHASE

    mapping: dict[str, tuple[str, str, str]] = {
        "po_goods": (KLASS_TRANSACTIONAL, "Yes", ROUTE_PURCHASE),
        "po_services": (KLASS_TRANSACTIONAL, "Yes", ROUTE_PURCHASE),
        "direct_expense": (KLASS_TRANSACTIONAL, "Yes", ROUTE_EXPENSES),
        "credit_adjustment": (KLASS_TRANSACTIONAL, "Yes", ROUTE_PURCHASE),
        "debit_note": (KLASS_TRANSACTIONAL, "Yes", ROUTE_PURCHASE),
        "pre_transactional": (KLASS_TRANSACTIONAL, "Down-payment", ROUTE_VAULT),
        "employee_claim": (KLASS_TRANSACTIONAL, "Yes", ROUTE_TEAM),
        "freight_logistics": (KLASS_TRANSACTIONAL, "Yes", ROUTE_PURCHASE),
        "intercompany": (KLASS_TRANSACTIONAL, "Yes", ROUTE_PURCHASE),
        "import_dossier": (KLASS_TRANSACTIONAL, "Yes", ROUTE_PURCHASE),
        "reconciliation": (KLASS_NON_TRANSACTIONAL, "No", ROUTE_VAULT),
        "supporting": (KLASS_NON_TRANSACTIONAL, "No", ROUTE_VAULT),
        "informational": (KLASS_NON_TRANSACTIONAL, "No", ROUTE_VAULT),
        "master_data": (KLASS_NON_TRANSACTIONAL, "No", ROUTE_VAULT),
        "non_actionable": (KLASS_NON_TRANSACTIONAL, "No", ROUTE_VAULT),
        "compliance_route": (KLASS_NON_TRANSACTIONAL, "No", ROUTE_VAULT),
        "standard_transactional": (KLASS_TRANSACTIONAL, "Yes", ROUTE_PURCHASE),
        "ar_goods": (KLASS_TRANSACTIONAL, "Yes", ROUTE_SALES),
        "ar_goods_2way": (KLASS_TRANSACTIONAL, "Yes", ROUTE_SALES),
    }
    return mapping.get(playbook, (KLASS_TRANSACTIONAL, "Yes", ROUTE_VAULT))


def suggest_bundle_members(playbook: str) -> tuple[list[str], list[str]]:
    if playbook == "po_goods":
        return ["DT-02", "DT-03"], ["Packing list", "Quality certificate"]
    if playbook == "po_services":
        return ["DT-02"], ["Service entry sheet / timesheet"]
    if playbook == "import_dossier":
        return ["DT-27", "DT-30"], ["Commercial invoice", "Bill of lading"]
    return [], []


def suggest_title_from_heading(heading: str | None) -> tuple[str | None, str | None]:
    if not heading:
        return None, None
    cleaned = heading.strip()
    if not cleaned:
        return None, None
    title = cleaned.title() if cleaned.isupper() else cleaned
    short = title if len(title) <= 48 else title[:45].rstrip() + "..."
    return title, short


def suggest_one_line(
    signals: frozenset[RecognitionSignalId],
    *,
    headings: list[str],
) -> str:
    if signals & {"heading_grn", "text_grn", "filename_grn"}:
        return "Goods receipt or delivery note linked to a purchase order."
    if signals & {"text_import", "filename_import"}:
        return "Import or customs document (permit, entry, certificate, or packing list)."
    if signals & {"text_freight", "filename_freight"}:
        return "Freight or transport document (AWB, bill of lading, or broker paperwork)."
    if signals & {"heading_po", "text_po", "filename_po"} and "has_invoice_number" not in signals:
        return "Purchase order copy used as a supporting bundle document."
    if signals & {"text_credit_note", "filename_credit_note"}:
        return "Credit or adjustment note referencing an original invoice."
    if signals & {"heading_contract", "text_contract", "text_governing_law"}:
        return "Contract or agreement with legal terms and party obligations."
    if {"has_po_reference", "has_invoice_number", "has_total_amount"}.issubset(signals):
        return "Commercial invoice with PO reference for purchase matching."
    if "has_invoice_number" in signals:
        return "Vendor invoice captured for accounts payable processing."
    label = headings[0] if headings else ""
    if label:
        return f"Document type identified from sample heading: {label}."
    return "Document type inferred from uploaded sample files."
