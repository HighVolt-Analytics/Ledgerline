"""Map OCR heading kinds to recognition signals and playbooks (all document families)."""

from __future__ import annotations

from app.services.extraction.document_heading_utils import HeadingKind, infer_page_document_kind

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
    "sales_order": frozenset({"heading_so"}),
    "grn": frozenset({"heading_grn"}),
    "credit_note": frozenset({"text_credit_note", "text_debit_note"}),
    "quote": frozenset({"text_quote"}),
    "proforma": frozenset({"text_proforma"}),
    "contract": frozenset({"heading_contract"}),
    "statement": frozenset({"text_statement"}),
    "remittance": frozenset({"text_remittance"}),
    "timesheet": frozenset({"text_timesheet"}),
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
    playbook = _infer_playbook_profile(signals)
    if playbook not in {"standard_transactional", "direct_expense"}:
        return playbook
    kind = infer_heading_kind(heading=heading, document_text=document_text)
    kind_playbook = playbook_for_heading_kind(kind)
    if kind_playbook:
        return kind_playbook
    return playbook


def _infer_playbook_profile(signals: frozenset[RecognitionSignalId]) -> str:
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
