"""Human-readable catalogue of document-type recognition signals."""

from __future__ import annotations

from dataclasses import dataclass

RecognitionSignalId = str

WEAK_SIGNAL_IDS: frozenset[RecognitionSignalId] = frozenset(
    {"has_po_reference", "has_invoice_number", "has_total_amount"}
)


@dataclass(frozen=True)
class RecognitionSignalInfo:
    signal_id: RecognitionSignalId
    label: str
    hint: str
    channel: str
    strength: str
    example: str


RECOGNITION_SIGNAL_CATALOG: dict[RecognitionSignalId, RecognitionSignalInfo] = {
    "heading_invoice": RecognitionSignalInfo(
        "heading_invoice",
        "Page title is invoice / tax invoice",
        "Strongest invoice cue — OCR title region or document heading field",
        "heading",
        "strong",
        "TAX INVOICE, INVOICE, Commercial Invoice",
    ),
    "text_invoice": RecognitionSignalInfo(
        "text_invoice",
        "Body mentions invoice wording",
        "Searches full OCR text — tax/commercial invoice, billing summary, invoice no/number",
        "body",
        "strong",
        "Tax Invoice, Billing Summary, Invoice No EP-001",
    ),
    "filename_invoice": RecognitionSignalInfo(
        "filename_invoice",
        "Filename contains inv / invoice / tax-invoice",
        "Attachment name pattern",
        "filename",
        "strong",
        "INV-1001.pdf, tax_invoice_acme.pdf",
    ),
    "heading_po": RecognitionSignalInfo(
        "heading_po",
        "Page title is purchase order",
        "OCR title region",
        "heading",
        "strong",
        "PURCHASE ORDER",
    ),
    "text_po": RecognitionSignalInfo(
        "text_po",
        "Body contains “purchase order”",
        "Full document text",
        "body",
        "strong",
        "Purchase Order No PO-44871",
    ),
    "filename_po": RecognitionSignalInfo(
        "filename_po",
        "Filename contains PO / purchase order",
        "Attachment name",
        "filename",
        "strong",
        "PO-99.pdf, purchase_order.pdf",
    ),
    "heading_grn": RecognitionSignalInfo(
        "heading_grn",
        "Page title is GRN / delivery note",
        "OCR title region",
        "heading",
        "strong",
        "GOODS RECEIPT NOTE, DELIVERY DOCKET",
    ),
    "text_grn": RecognitionSignalInfo(
        "text_grn",
        "Body mentions goods receipt or GRN",
        "Full document text",
        "body",
        "strong",
        "Goods Receipt, GRN, Delivery Note",
    ),
    "filename_grn": RecognitionSignalInfo(
        "filename_grn",
        "Filename contains GRN / delivery note",
        "Attachment name",
        "filename",
        "strong",
        "GRN-PO-99.pdf",
    ),
    "heading_contract": RecognitionSignalInfo(
        "heading_contract",
        "Page title is contract / agreement",
        "OCR title region",
        "heading",
        "strong",
        "CONTRACT, Master Service Agreement",
    ),
    "text_contract": RecognitionSignalInfo(
        "text_contract",
        "Body mentions contract or DocuSign",
        "Full document text",
        "body",
        "strong",
        "Contract, DocuSign, MSA",
    ),
    "filename_contract": RecognitionSignalInfo(
        "filename_contract",
        "Filename contains contract / SOW / lease",
        "Attachment name",
        "filename",
        "strong",
        "contract-2026.pdf, sow.pdf",
    ),
    "text_terms": RecognitionSignalInfo(
        "text_terms",
        "Body contains “terms and conditions”",
        "Contract/supporting legal text",
        "body",
        "strong",
        "Terms and Conditions",
    ),
    "text_governing_law": RecognitionSignalInfo(
        "text_governing_law",
        "Body contains “governing law”",
        "Contract legal clause",
        "body",
        "strong",
        "Governing law of New South Wales",
    ),
    "text_signed_behalf": RecognitionSignalInfo(
        "text_signed_behalf",
        "Body contains signature block language",
        "Contract execution phrase",
        "body",
        "strong",
        "Signed for and on behalf of",
    ),
    "text_credit_note": RecognitionSignalInfo(
        "text_credit_note",
        "Body mentions credit note",
        "Full document text",
        "body",
        "strong",
        "CREDIT NOTE",
    ),
    "filename_credit_note": RecognitionSignalInfo(
        "filename_credit_note",
        "Filename contains credit note",
        "Attachment name",
        "filename",
        "strong",
        "credit-note-2026.pdf",
    ),
    "text_debit_note": RecognitionSignalInfo(
        "text_debit_note",
        "Body mentions debit note",
        "Full document text",
        "body",
        "strong",
        "DEBIT NOTE",
    ),
    "filename_debit_note": RecognitionSignalInfo(
        "filename_debit_note",
        "Filename contains debit note",
        "Attachment name",
        "filename",
        "strong",
        "debit_note.pdf",
    ),
    "text_proforma": RecognitionSignalInfo(
        "text_proforma",
        "Body mentions proforma or advance request",
        "Pre-invoice document",
        "body",
        "strong",
        "Pro-forma Invoice",
    ),
    "filename_proforma": RecognitionSignalInfo(
        "filename_proforma",
        "Filename contains proforma / advance",
        "Attachment name",
        "filename",
        "strong",
        "proforma.pdf",
    ),
    "text_claim": RecognitionSignalInfo(
        "text_claim",
        "Body mentions expense claim or reimbursement",
        "Employee claim documents",
        "body",
        "strong",
        "Expense Claim, Reimbursement",
    ),
    "filename_claim": RecognitionSignalInfo(
        "filename_claim",
        "Filename contains claim / expense / reimburse",
        "Attachment name",
        "filename",
        "strong",
        "expense-claim.pdf",
    ),
    "text_quote": RecognitionSignalInfo(
        "text_quote",
        "Body mentions quote, quotation, or estimate",
        "Pre-transactional quote",
        "body",
        "strong",
        "QUOTATION, Estimate",
    ),
    "filename_quote": RecognitionSignalInfo(
        "filename_quote",
        "Filename contains quote / proposal",
        "Attachment name",
        "filename",
        "strong",
        "quote-99.pdf",
    ),
    "text_tax_notice": RecognitionSignalInfo(
        "text_tax_notice",
        "Body mentions ATO or tax / compliance notice",
        "Government/compliance notices",
        "body",
        "strong",
        "ATO notice, Tax Office",
    ),
    "filename_tax_notice": RecognitionSignalInfo(
        "filename_tax_notice",
        "Filename contains ATO / tax notice",
        "Attachment name",
        "filename",
        "strong",
        "ato-notice.pdf",
    ),
    "text_bank_change": RecognitionSignalInfo(
        "text_bank_change",
        "Body mentions bank detail change",
        "Master-data / fraud-sensitive",
        "body",
        "strong",
        "Change of bank details",
    ),
    "filename_bank_change": RecognitionSignalInfo(
        "filename_bank_change",
        "Filename contains bank detail / change of bank",
        "Attachment name",
        "filename",
        "strong",
        "bank_details_change.pdf",
    ),
    "text_freight": RecognitionSignalInfo(
        "text_freight",
        "Body mentions freight, AWB, or customs broker",
        "Logistics / import dossier",
        "body",
        "strong",
        "AWB, Bill of Lading, freight",
    ),
    "filename_freight": RecognitionSignalInfo(
        "filename_freight",
        "Filename contains freight / AWB",
        "Attachment name",
        "filename",
        "strong",
        "awb-123.pdf",
    ),
    "text_import": RecognitionSignalInfo(
        "text_import",
        "Body mentions customs entry or import declaration",
        "Import dossier",
        "body",
        "strong",
        "Customs Entry, Import Declaration",
    ),
    "filename_import": RecognitionSignalInfo(
        "filename_import",
        "Filename contains customs / import",
        "Attachment name",
        "filename",
        "strong",
        "customs-entry.pdf",
    ),
    "text_intercompany": RecognitionSignalInfo(
        "text_intercompany",
        "Body mentions intercompany or transfer pricing",
        "IC billing",
        "body",
        "strong",
        "Intercompany invoice",
    ),
    "filename_intercompany": RecognitionSignalInfo(
        "filename_intercompany",
        "Filename contains intercompany / IC",
        "Attachment name",
        "filename",
        "strong",
        "ic-invoice.pdf",
    ),
    "has_po_reference": RecognitionSignalInfo(
        "has_po_reference",
        "PO number found on document",
        "Weak alone — pair with invoice identity signals",
        "field",
        "weak",
        "PO Reference PO-44871",
    ),
    "has_invoice_number": RecognitionSignalInfo(
        "has_invoice_number",
        "Invoice number present",
        "Weak alone — add heading_invoice or text_invoice",
        "field",
        "weak",
        "Invoice No EP-001",
    ),
    "has_total_amount": RecognitionSignalInfo(
        "has_total_amount",
        "Total amount present",
        "Weak alone — confirms transactional document",
        "field",
        "weak",
        "Total $110.00",
    ),
}


PLAYBOOK_RECOMMENDED_IDENTITY: dict[str, list[RecognitionSignalId]] = {
    "po_goods": ["heading_invoice", "text_invoice", "filename_invoice", "has_po_reference"],
    "po_services": ["heading_invoice", "text_invoice", "has_po_reference"],
    "direct_expense": ["heading_invoice", "text_invoice", "filename_invoice"],
    "standard_transactional": ["heading_invoice", "text_invoice", "has_invoice_number"],
    "credit_adjustment": ["text_credit_note", "filename_credit_note"],
    "debit_note": ["text_debit_note", "filename_debit_note"],
    "employee_claim": ["text_claim", "filename_claim"],
    "supporting": ["heading_po", "text_po", "heading_grn", "text_grn"],
    "non_actionable": ["text_quote", "filename_quote"],
    "compliance_route": ["text_tax_notice", "filename_tax_notice"],
    "master_data": ["text_bank_change", "filename_bank_change"],
}


def describe_signal(signal_id: RecognitionSignalId, *, detected: bool = True) -> dict[str, str]:
    info = RECOGNITION_SIGNAL_CATALOG.get(signal_id)
    if info is None:
        return {
            "signal_id": signal_id,
            "label": signal_id.replace("_", " ").title(),
            "hint": "",
            "channel": "unknown",
            "strength": "strong" if signal_id not in WEAK_SIGNAL_IDS else "weak",
            "example": "",
            "detected": detected,
        }
    return {
        "signal_id": info.signal_id,
        "label": info.label,
        "hint": info.hint,
        "channel": info.channel,
        "strength": info.strength,
        "example": info.example,
        "detected": detected,
    }


def describe_signals(signal_ids: list[RecognitionSignalId]) -> list[dict[str, str]]:
    return [describe_signal(signal_id, detected=True) for signal_id in signal_ids]


def suggest_missing_identity_signals(
    detected: frozenset[RecognitionSignalId],
    *,
    playbook: str,
    document_heading: str | None = None,
) -> list[dict[str, str]]:
    """Recommend strong identity signals not yet detected."""
    from app.services.document_type_recognition_signals import identity_signals

    if identity_signals(detected):
        return []

    recommended = PLAYBOOK_RECOMMENDED_IDENTITY.get(
        (playbook or "").strip().lower(),
        PLAYBOOK_RECOMMENDED_IDENTITY["direct_expense"],
    )
    missing: list[dict[str, str]] = []
    heading = (document_heading or "").strip()
    for signal_id in recommended:
        if signal_id in detected:
            continue
        row = describe_signal(signal_id, detected=False)
        if signal_id == "heading_invoice" and heading:
            row["hint"] = f'{row["hint"]} — your heading is "{heading}"; ensure it says Tax Invoice or rename file'
        elif signal_id == "filename_invoice":
            row["hint"] = f'{row["hint"]} — try renaming upload to include invoice or inv'
        missing.append(row)
    return missing[:4]
