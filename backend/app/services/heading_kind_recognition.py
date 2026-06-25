"""Map OCR heading kinds to recognition signals and playbooks (all document families)."""

from __future__ import annotations

from app.services.document_heading_utils import HeadingKind, infer_page_document_kind

RecognitionSignalId = str

# Heading kinds where a parsed "invoice_no" is usually a permit/AWB/ref — not AP invoice identity.
NON_INVOICE_NUMBER_KINDS: frozenset[HeadingKind] = frozenset(
    {
        "customs_permit",
        "transport_doc",
        "packing_list",
        "certificate_of_origin",
        "purchase_order",
        "grn",
        "quote",
        "contract",
        "timesheet",
        "statement",
        "remittance",
    }
)

HEADING_KIND_SIGNALS: dict[HeadingKind, frozenset[RecognitionSignalId]] = {
    "customs_permit": frozenset({"text_import"}),
    "certificate_of_origin": frozenset({"text_import"}),
    "packing_list": frozenset({"text_import"}),
    "transport_doc": frozenset({"text_freight"}),
    "tax_invoice": frozenset({"heading_invoice"}),
    "commercial_invoice": frozenset({"heading_invoice"}),
    "invoice": frozenset({"heading_invoice"}),
    "purchase_order": frozenset({"heading_po"}),
    "grn": frozenset({"heading_grn"}),
    "credit_note": frozenset({"text_credit_note"}),
    "quote": frozenset({"text_quote"}),
    "proforma": frozenset({"text_proforma"}),
    "contract": frozenset({"heading_contract"}),
}

HEADING_KIND_PLAYBOOK: dict[HeadingKind, str] = {
    "customs_permit": "import_dossier",
    "certificate_of_origin": "import_dossier",
    "packing_list": "import_dossier",
    "transport_doc": "freight_logistics",
    "purchase_order": "supporting",
    "grn": "supporting",
    "credit_note": "credit_adjustment",
    "quote": "non_actionable",
    "proforma": "pre_transactional",
    "contract": "supporting",
    "tax_invoice": "standard_transactional",
    "commercial_invoice": "standard_transactional",
    "invoice": "standard_transactional",
}


def infer_heading_kind(*, heading: str | None = None, document_text: str = "") -> HeadingKind | None:
    blob = "\n".join(part for part in [(heading or "").strip(), (document_text or "")[:4000]] if part)
    if not blob.strip():
        return None
    return infer_page_document_kind(blob)


def signals_for_heading_kind(kind: HeadingKind | None) -> frozenset[RecognitionSignalId]:
    if kind is None:
        return frozenset()
    return HEADING_KIND_SIGNALS.get(kind, frozenset())


def playbook_for_heading_kind(kind: HeadingKind | None) -> str | None:
    if kind is None:
        return None
    return HEADING_KIND_PLAYBOOK.get(kind)


def resolve_playbook_profile(
    signals: frozenset[RecognitionSignalId],
    *,
    heading: str | None = None,
    document_text: str = "",
) -> str:
    """Pick playbook from detected signals, else heading kind, else transactional default."""
    from app.services.document_type_recognition_signals import infer_playbook_profile

    playbook = infer_playbook_profile(signals)
    if playbook not in {"standard_transactional", "direct_expense"}:
        return playbook
    kind = infer_heading_kind(heading=heading, document_text=document_text)
    kind_playbook = playbook_for_heading_kind(kind)
    if kind_playbook:
        return kind_playbook
    return playbook
