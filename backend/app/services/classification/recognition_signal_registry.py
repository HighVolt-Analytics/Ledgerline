"""Single source of truth for document-type recognition signals."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

RecognitionSignalId = str

WEAK_SIGNAL_IDS: frozenset[RecognitionSignalId] = frozenset(
    {"has_po_reference", "has_invoice_number", "has_total_amount"}
)

# OR within each channel; AND across channels and weak field checks.
SIGNAL_PICK_GROUPS: tuple[tuple[RecognitionSignalId, ...], ...] = (
    ("heading_invoice", "text_invoice", "filename_invoice"),
    ("heading_po", "text_po", "filename_po"),
    ("heading_so", "text_so", "filename_so"),
    ("heading_grn", "text_grn", "filename_grn"),
    ("heading_contract", "text_contract", "filename_contract"),
    ("text_credit_note", "filename_credit_note"),
    ("text_debit_note", "filename_debit_note"),
    ("text_proforma", "filename_proforma"),
    ("text_claim", "filename_claim"),
    ("text_quote", "filename_quote"),
    ("text_tax_notice", "filename_tax_notice"),
    ("text_bank_change", "filename_bank_change"),
    ("text_freight", "filename_freight"),
    ("text_import", "filename_import"),
    ("text_intercompany", "filename_intercompany"),
    ("text_recurring", "filename_recurring"),
    ("text_utility", "filename_utility"),
    ("text_statement", "filename_statement"),
    ("text_timesheet", "filename_timesheet"),
    ("text_remittance", "filename_remittance"),
    ("text_rcti", "filename_rcti"),
    ("text_consignment", "filename_consignment"),
    ("text_dunning", "filename_dunning"),
    ("text_terms", "text_governing_law", "text_signed_behalf"),
)

SUPPORTING_GUARDS: list[dict[str, Any]] = [
    {"type": "condition", "field": "has_invoice_no", "operator": "equals", "value": "false"},
    {"type": "condition", "field": "is_commercial_invoice", "operator": "equals", "value": "false"},
]

SIGNAL_CONDITIONS: dict[RecognitionSignalId, dict[str, Any]] = {
    "heading_po": {"field": "has_heading_po", "operator": "equals", "value": "true"},
    "text_po": {"field": "document_text", "operator": "regex", "value": "(?i)purchase order"},
    "filename_po": {
        "field": "attachment_name",
        "operator": "regex",
        "value": "(?i)purchase[_-]?order|(^|[-_/])po([-_.]|$)",
    },
    "heading_so": {"field": "has_heading_so", "operator": "equals", "value": "true"},
    "text_so": {
        "field": "document_text",
        "operator": "regex",
        "value": "(?i)(\\bsales\\s+order\\b|\\bSO[-\\s#][A-Z0-9][A-Z0-9\\-/_]{2,})",
    },
    "filename_so": {
        "field": "attachment_name",
        "operator": "regex",
        "value": "(?i)sales[_\\s-]?order|(^|[-_/])so([-_.]|$)",
    },
    "heading_grn": {"field": "has_heading_grn", "operator": "equals", "value": "true"},
    "text_grn": {
        "field": "document_text",
        "operator": "regex",
        "value": "(?i)(goods\\s+receipt|delivery\\s+(note|docket)|\\bGRN\\b)",
    },
    "filename_grn": {
        "field": "attachment_name",
        "operator": "regex",
        "value": "(?i)grn|goods[_-]?receipt|delivery[_-]?note",
    },
    "heading_contract": {"field": "has_heading_contract", "operator": "equals", "value": "true"},
    "text_contract": {
        "field": "document_text",
        "operator": "regex",
        "value": "(?i)(\\bcontract\\b|docusign|master service agreement|terms and conditions)",
    },
    "filename_contract": {
        "field": "attachment_name",
        "operator": "regex",
        "value": "(?i)(contract|lease|sow|statement[_-]?of[_-]?work|rate[_-]?card)",
    },
    "text_terms": {"field": "document_text", "operator": "contains", "value": "terms and conditions"},
    "text_governing_law": {"field": "document_text", "operator": "contains", "value": "governing law"},
    "text_signed_behalf": {
        "field": "document_text",
        "operator": "contains",
        "value": "signed for and on behalf",
    },
    "heading_invoice": {"field": "has_heading_invoice", "operator": "equals", "value": "true"},
    "text_invoice": {
        "field": "document_text",
        "operator": "regex",
        "value": "(?i)\\b(tax\\s+invoice|commercial\\s+invoice|billing\\s+summary|invoice\\s+no|invoice\\s+number)\\b",
    },
    "filename_invoice": {
        "field": "attachment_name",
        "operator": "regex",
        "value": "(?i)(?:^|[-_/])(?:inv|invoice|tax[_-]?inv)(?:[-_.]|$)",
    },
    "text_credit_note": {
        "field": "document_text",
        "operator": "regex",
        "value": "(?i)(credit\\s+note|creditmemo|credit_memo)",
    },
    "filename_credit_note": {
        "field": "attachment_name",
        "operator": "regex",
        "value": "(?i)(credit[_-]?note|creditmemo|credit_memo)",
    },
    "text_debit_note": {
        "field": "document_text",
        "operator": "regex",
        "value": "(?i)(debit\\s+note|debitmemo|debit_memo)",
    },
    "filename_debit_note": {
        "field": "attachment_name",
        "operator": "regex",
        "value": "(?i)(debit[_-]?note|debitmemo|debit_memo)",
    },
    "text_proforma": {
        "field": "document_text",
        "operator": "regex",
        "value": "(?i)(pro[\\s_-]?forma|advance[\\s_-]?request)",
    },
    "filename_proforma": {
        "field": "attachment_name",
        "operator": "regex",
        "value": "(?i)(pro[\\s_-]?forma|advance[\\s_-]?request)",
    },
    "text_claim": {
        "field": "document_text",
        "operator": "regex",
        "value": "(?i)(expense[_\\s-]?claim|reimburse(?:ment)?|claim[_\\s-]?form|team[_\\s-]?expense)",
    },
    "filename_claim": {
        "field": "attachment_name",
        "operator": "regex",
        "value": "(?i)(expense[_\\s-]?claim|claim[_\\s-]?receipt|claim[_\\s-]?form|team[_\\s-]?meal|team[_\\s-]?expense|reimburse)",
    },
    "text_quote": {
        "field": "document_text",
        "operator": "regex",
        "value": "(?i)\\b(quote|quotation|estimate|proposal)\\b",
    },
    "filename_quote": {
        "field": "attachment_name",
        "operator": "regex",
        "value": "(?i)(quote|quotation|estimate|proposal)",
    },
    "text_tax_notice": {
        "field": "document_text",
        "operator": "regex",
        "value": "(?i)\\b(ato|tax[_-]?office|tax[_-]?notice|compliance[_-]?notice)\\b",
    },
    "filename_tax_notice": {
        "field": "attachment_name",
        "operator": "regex",
        "value": "(?i)(ato|tax[_-]?office|tax[_-]?notice|compliance[_-]?notice)",
    },
    "text_bank_change": {
        "field": "document_text",
        "operator": "regex",
        "value": "(?i)(bank[_-]?detail|change[_-]?of[_-]?bank)",
    },
    "filename_bank_change": {
        "field": "attachment_name",
        "operator": "regex",
        "value": "(?i)(bank[_-]?detail|change[_-]?of[_-]?bank)",
    },
    "text_freight": {
        "field": "document_text",
        "operator": "regex",
        "value": "(?i)(\\bawb\\b|bill\\s+of\\s+lading|\\bfreight\\b|customs\\s+broker|demurrage)",
    },
    "filename_freight": {
        "field": "attachment_name",
        "operator": "regex",
        "value": "(?i)(awb|bill[_-]?of[_-]?lading|freight|customs[_-]?broker|demurrage)",
    },
    "text_import": {
        "field": "document_text",
        "operator": "regex",
        "value": (
            "(?i)(customs\\s+entry|import\\s+declaration|bill\\s+of\\s+entry|"
            "cargo\\s+clearance\\s+permit|clearance\\s+permit|certificate\\s+of\\s+origin|packing\\s+list)"
        ),
    },
    "filename_import": {
        "field": "attachment_name",
        "operator": "regex",
        "value": (
            "(?i)(customs[_-]?entry|import[_-]?declaration|bill[_-]?of[_-]?entry|"
            "clearance[_-]?permit|certificate[_-]?of[_-]?origin|packing[_-]?list)"
        ),
    },
    "text_intercompany": {
        "field": "document_text",
        "operator": "regex",
        "value": "(?i)(intercompany|inter-company|\\bIC\\s+invoice\\b|transfer\\s+pricing)",
    },
    "filename_intercompany": {
        "field": "attachment_name",
        "operator": "regex",
        "value": "(?i)(intercompany|inter[_-]?company|ic[_-]?invoice)",
    },
    "text_recurring": {
        "field": "document_text",
        "operator": "regex",
        "value": "(?i)(\\brent\\b|\\blease\\b|subscription|retainer|recurring)",
    },
    "filename_recurring": {
        "field": "attachment_name",
        "operator": "regex",
        "value": "(?i)(rent|lease|subscription|retainer|recurring)",
    },
    "text_utility": {
        "field": "document_text",
        "operator": "regex",
        "value": "(?i)(utility|electricity|water\\s+bill|gas\\s+bill|telecom|telco)",
    },
    "filename_utility": {
        "field": "attachment_name",
        "operator": "regex",
        "value": "(?i)(utility|electric|water|gas|telco|telecom)",
    },
    "text_statement": {
        "field": "document_text",
        "operator": "regex",
        "value": "(?i)(vendor statement|account summary)",
    },
    "filename_statement": {
        "field": "attachment_name",
        "operator": "regex",
        "value": "(?i)(statement|acct[_-]?summary|account[_-]?summary)",
    },
    "text_timesheet": {
        "field": "document_text",
        "operator": "regex",
        "value": "(?i)(timesheet|time[_-]?sheet|service[_-]?entry)",
    },
    "filename_timesheet": {
        "field": "attachment_name",
        "operator": "regex",
        "value": "(?i)(timesheet|time[_-]?sheet|service[_-]?entry|ses[_-])",
    },
    "text_remittance": {
        "field": "document_text",
        "operator": "regex",
        "value": "(?i)(remittance|payment[_-]?advice)",
    },
    "filename_remittance": {
        "field": "attachment_name",
        "operator": "regex",
        "value": "(?i)(remittance|payment[_-]?advice)",
    },
    "text_rcti": {
        "field": "document_text",
        "operator": "regex",
        "value": "(?i)(\\bRCTI\\b|recipient[- ]created|self[- ]bill)",
    },
    "filename_rcti": {
        "field": "attachment_name",
        "operator": "regex",
        "value": "(?i)(rcti|self[_-]?bill|recipient[_-]?created)",
    },
    "text_consignment": {
        "field": "document_text",
        "operator": "regex",
        "value": "(?i)(consignment|evaluated\\s+receipt|\\bERS\\b)",
    },
    "filename_consignment": {
        "field": "attachment_name",
        "operator": "regex",
        "value": "(?i)(consignment|evaluated[_-]?receipt|ers[_-])",
    },
    "text_dunning": {
        "field": "document_text",
        "operator": "regex",
        "value": "(?i)(dunning|overdue|final[_-]?demand)",
    },
    "filename_dunning": {
        "field": "attachment_name",
        "operator": "regex",
        "value": "(?i)(dunning|overdue|final[_-]?demand)",
    },
    "channel_whatsapp": {"field": "capture_channel", "operator": "equals", "value": "whatsapp"},
    "has_po_reference": {"field": "has_po_reference", "operator": "equals", "value": "true"},
    "has_invoice_number": {"field": "has_invoice_no", "operator": "equals", "value": "true"},
    "has_total_amount": {"field": "has_total", "operator": "equals", "value": "true"},
}


@dataclass(frozen=True)
class RecognitionSignalInfo:
    signal_id: RecognitionSignalId
    label: str
    hint: str
    channel: str
    strength: str
    example: str


_SIGNAL_META: dict[RecognitionSignalId, tuple[str, str, str, str, str]] = {
    "heading_invoice": (
        "Page title is invoice / tax invoice",
        "Strongest invoice cue — OCR title region or document heading field",
        "heading",
        "strong",
        "TAX INVOICE, INVOICE, Commercial Invoice",
    ),
    "text_invoice": (
        "Body mentions invoice wording",
        "Searches full OCR text — tax/commercial invoice, billing summary, invoice no/number",
        "body",
        "strong",
        "Tax Invoice, Billing Summary, Invoice No EP-001",
    ),
    "filename_invoice": (
        "Filename contains inv / invoice / tax-invoice",
        "Attachment name pattern",
        "filename",
        "strong",
        "INV-1001.pdf, tax_invoice_acme.pdf",
    ),
    "heading_po": (
        "Page title is purchase order",
        "OCR title region",
        "heading",
        "strong",
        "PURCHASE ORDER",
    ),
    "text_po": (
        "Body contains “purchase order”",
        "Full document text",
        "body",
        "strong",
        "Purchase Order No PO-44871",
    ),
    "filename_po": (
        "Filename contains PO / purchase order",
        "Attachment name",
        "filename",
        "strong",
        "PO-99.pdf, purchase_order.pdf",
    ),
    "heading_so": (
        "Page title is sales order",
        "OCR title region",
        "heading",
        "strong",
        "SALES ORDER",
    ),
    "text_so": (
        "Body contains sales order or SO reference",
        "Full document text",
        "body",
        "strong",
        "Sales Order No SO-DEMO-100",
    ),
    "filename_so": (
        "Filename contains sales order / SO",
        "Attachment name",
        "filename",
        "strong",
        "sales_order_SO-100.pdf, SO-DEMO-100.pdf",
    ),
    "heading_grn": (
        "Page title is GRN / delivery note",
        "OCR title region",
        "heading",
        "strong",
        "GOODS RECEIPT NOTE, DELIVERY DOCKET",
    ),
    "text_grn": (
        "Body mentions goods receipt or GRN",
        "Full document text",
        "body",
        "strong",
        "Goods Receipt, GRN, Delivery Note",
    ),
    "filename_grn": (
        "Filename contains GRN / delivery note",
        "Attachment name",
        "filename",
        "strong",
        "GRN-PO-99.pdf",
    ),
    "heading_contract": (
        "Page title is contract / agreement",
        "OCR title region",
        "heading",
        "strong",
        "CONTRACT, Master Service Agreement",
    ),
    "text_contract": (
        "Body mentions contract or DocuSign",
        "Full document text",
        "body",
        "strong",
        "Contract, DocuSign, MSA",
    ),
    "filename_contract": (
        "Filename contains contract / SOW / lease",
        "Attachment name",
        "filename",
        "strong",
        "contract-2026.pdf, sow.pdf",
    ),
    "text_terms": (
        "Body contains “terms and conditions”",
        "Contract/supporting legal text",
        "body",
        "strong",
        "Terms and Conditions",
    ),
    "text_governing_law": (
        "Body contains “governing law”",
        "Contract legal clause",
        "body",
        "strong",
        "Governing law of New South Wales",
    ),
    "text_signed_behalf": (
        "Body contains signature block language",
        "Contract execution phrase",
        "body",
        "strong",
        "Signed for and on behalf of",
    ),
    "text_credit_note": (
        "Body mentions credit note",
        "Full document text",
        "body",
        "strong",
        "CREDIT NOTE",
    ),
    "filename_credit_note": (
        "Filename contains credit note",
        "Attachment name",
        "filename",
        "strong",
        "credit-note-2026.pdf",
    ),
    "text_debit_note": (
        "Body mentions debit note",
        "Full document text",
        "body",
        "strong",
        "DEBIT NOTE",
    ),
    "filename_debit_note": (
        "Filename contains debit note",
        "Attachment name",
        "filename",
        "strong",
        "debit_note.pdf",
    ),
    "text_proforma": (
        "Body mentions proforma or advance request",
        "Pre-invoice document",
        "body",
        "strong",
        "Pro-forma Invoice",
    ),
    "filename_proforma": (
        "Filename contains proforma / advance",
        "Attachment name",
        "filename",
        "strong",
        "proforma.pdf",
    ),
    "text_claim": (
        "Body mentions expense claim or reimbursement",
        "Employee claim documents",
        "body",
        "strong",
        "Expense Claim, Reimbursement",
    ),
    "filename_claim": (
        "Filename contains claim / expense / reimburse",
        "Attachment name",
        "filename",
        "strong",
        "expense-claim.pdf",
    ),
    "text_quote": (
        "Body mentions quote, quotation, or estimate",
        "Pre-transactional quote",
        "body",
        "strong",
        "QUOTATION, Estimate",
    ),
    "filename_quote": (
        "Filename contains quote / proposal",
        "Attachment name",
        "filename",
        "strong",
        "quote-99.pdf",
    ),
    "text_tax_notice": (
        "Body mentions ATO or tax / compliance notice",
        "Government/compliance notices",
        "body",
        "strong",
        "ATO notice, Tax Office",
    ),
    "filename_tax_notice": (
        "Filename contains ATO / tax notice",
        "Attachment name",
        "filename",
        "strong",
        "ato-notice.pdf",
    ),
    "text_bank_change": (
        "Body mentions bank detail change",
        "Master-data / fraud-sensitive",
        "body",
        "strong",
        "Change of bank details",
    ),
    "filename_bank_change": (
        "Filename contains bank detail / change of bank",
        "Attachment name",
        "filename",
        "strong",
        "bank_details_change.pdf",
    ),
    "text_freight": (
        "Body mentions freight, AWB, or customs broker",
        "Logistics / import dossier",
        "body",
        "strong",
        "AWB, Bill of Lading, freight",
    ),
    "filename_freight": (
        "Filename contains freight / AWB",
        "Attachment name",
        "filename",
        "strong",
        "awb-123.pdf",
    ),
    "text_import": (
        "Body mentions customs, import, or clearance permit",
        "Import dossier — customs entry, cargo clearance permit, certificate of origin, packing list",
        "body",
        "strong",
        "Cargo Clearance Permit, Customs Entry, Certificate of Origin",
    ),
    "filename_import": (
        "Filename contains customs / import",
        "Attachment name",
        "filename",
        "strong",
        "customs-entry.pdf",
    ),
    "text_intercompany": (
        "Body mentions intercompany or transfer pricing",
        "IC billing",
        "body",
        "strong",
        "Intercompany invoice",
    ),
    "filename_intercompany": (
        "Filename contains intercompany / IC",
        "Attachment name",
        "filename",
        "strong",
        "ic-invoice.pdf",
    ),
    "text_recurring": (
        "Body mentions rent, lease, or subscription",
        "Recurring / lease billing",
        "body",
        "strong",
        "Monthly rent, SaaS subscription",
    ),
    "filename_recurring": (
        "Filename contains rent / lease / subscription",
        "Attachment name",
        "filename",
        "strong",
        "office-lease.pdf",
    ),
    "text_utility": (
        "Body mentions utility or telecom bill",
        "Utility billing",
        "body",
        "strong",
        "Electricity bill, Telco invoice",
    ),
    "filename_utility": (
        "Filename contains utility / electric / telco",
        "Attachment name",
        "filename",
        "strong",
        "electric-bill.pdf",
    ),
    "text_statement": (
        "Body mentions vendor statement or account summary",
        "Reconciliation documents",
        "body",
        "strong",
        "Vendor statement of account",
    ),
    "filename_statement": (
        "Filename contains statement / account summary",
        "Attachment name",
        "filename",
        "strong",
        "vendor-statement.pdf",
    ),
    "text_timesheet": (
        "Body mentions timesheet or service entry",
        "Services / SES evidence",
        "body",
        "strong",
        "Timesheet for March",
    ),
    "filename_timesheet": (
        "Filename contains timesheet / SES",
        "Attachment name",
        "filename",
        "strong",
        "timesheet-march.pdf",
    ),
    "text_remittance": (
        "Body mentions remittance or payment advice",
        "Payment advice documents",
        "body",
        "strong",
        "Remittance advice",
    ),
    "filename_remittance": (
        "Filename contains remittance / payment advice",
        "Attachment name",
        "filename",
        "strong",
        "remittance.pdf",
    ),
    "text_rcti": (
        "Body mentions RCTI or self-bill",
        "Recipient-created tax invoice",
        "body",
        "strong",
        "RCTI, Recipient Created Tax Invoice",
    ),
    "filename_rcti": (
        "Filename contains RCTI / self-bill",
        "Attachment name",
        "filename",
        "strong",
        "rcti-vendor.pdf",
    ),
    "text_consignment": (
        "Body mentions consignment or ERS",
        "Consignment stock documents",
        "body",
        "strong",
        "Consignment stock, ERS",
    ),
    "filename_consignment": (
        "Filename contains consignment / ERS",
        "Attachment name",
        "filename",
        "strong",
        "consignment.pdf",
    ),
    "text_dunning": (
        "Body mentions dunning or overdue notice",
        "Collection / dunning letters",
        "body",
        "strong",
        "Final demand, overdue notice",
    ),
    "filename_dunning": (
        "Filename contains dunning / overdue",
        "Attachment name",
        "filename",
        "strong",
        "dunning-letter.pdf",
    ),
    "channel_whatsapp": (
        "Submitted via WhatsApp",
        "Capture channel only",
        "channel",
        "strong",
        "WhatsApp capture",
    ),
    "has_po_reference": (
        "PO number found on document",
        "Weak alone — pair with invoice identity signals",
        "field",
        "weak",
        "PO Reference PO-44871",
    ),
    "has_invoice_number": (
        "Invoice number present",
        "Weak alone — add heading_invoice or text_invoice",
        "field",
        "weak",
        "Invoice No EP-001",
    ),
    "has_total_amount": (
        "Total amount present",
        "Weak alone — confirms transactional document",
        "field",
        "weak",
        "Total $110.00",
    ),
}


def _build_catalog() -> dict[RecognitionSignalId, RecognitionSignalInfo]:
    catalog: dict[RecognitionSignalId, RecognitionSignalInfo] = {}
    for signal_id, condition in SIGNAL_CONDITIONS.items():
        label, hint, channel, strength, example = _SIGNAL_META.get(
            signal_id,
            (
                signal_id.replace("_", " ").title(),
                "",
                "unknown",
                "weak" if signal_id in WEAK_SIGNAL_IDS else "strong",
                "",
            ),
        )
        catalog[signal_id] = RecognitionSignalInfo(
            signal_id=signal_id,
            label=label,
            hint=hint,
            channel=channel,
            strength=strength,
            example=example,
        )
    return catalog


RECOGNITION_SIGNAL_CATALOG: dict[RecognitionSignalId, RecognitionSignalInfo] = _build_catalog()

PLAYBOOK_RECOMMENDED_IDENTITY: dict[str, list[RecognitionSignalId]] = {
    "po_goods": ["heading_invoice", "text_invoice", "filename_invoice", "has_po_reference"],
    "po_services": ["heading_invoice", "text_invoice", "has_po_reference"],
    "direct_expense": ["heading_invoice", "text_invoice", "filename_invoice"],
    "standard_transactional": ["heading_invoice", "text_invoice", "has_invoice_number"],
    "credit_adjustment": ["text_credit_note", "filename_credit_note"],
    "debit_note": ["text_debit_note", "filename_debit_note"],
    "employee_claim": ["text_claim", "filename_claim"],
    "supporting": ["heading_po", "text_po", "heading_so", "text_so", "heading_grn", "text_grn"],
    "non_actionable": ["text_quote", "filename_quote"],
    "compliance_route": ["text_tax_notice", "filename_tax_notice"],
    "master_data": ["text_bank_change", "filename_bank_change"],
    "freight_logistics": ["text_freight", "filename_freight", "text_import"],
    "import_dossier": ["text_import", "filename_import", "text_freight"],
}


def signal_condition(signal_id: RecognitionSignalId) -> dict[str, Any] | None:
    return SIGNAL_CONDITIONS.get(signal_id)


def detection_patterns_for_field(field: str) -> list[tuple[RecognitionSignalId, re.Pattern[str]]]:
    """Regex detection patterns aligned with classifier conditions."""
    patterns: list[tuple[RecognitionSignalId, re.Pattern[str]]] = []
    for signal_id, spec in SIGNAL_CONDITIONS.items():
        if spec.get("field") != field or spec.get("operator") != "regex":
            continue
        patterns.append((signal_id, re.compile(str(spec["value"]))))
    return patterns


def filename_detection_patterns() -> list[tuple[RecognitionSignalId, re.Pattern[str]]]:
    return detection_patterns_for_field("attachment_name")


def text_detection_patterns() -> list[tuple[RecognitionSignalId, re.Pattern[str]]]:
    return detection_patterns_for_field("document_text")


def catalog_payload() -> dict[str, Any]:
    """Serialize registry for API consumers."""
    signals = []
    for signal_id in SIGNAL_CONDITIONS:
        info = RECOGNITION_SIGNAL_CATALOG[signal_id]
        condition = SIGNAL_CONDITIONS[signal_id]
        signals.append(
            {
                "id": signal_id,
                "label": info.label,
                "hint": info.hint,
                "channel": info.channel,
                "strength": info.strength,
                "example": info.example,
                "condition": condition,
            }
        )
    return {
        "weak_signal_ids": sorted(WEAK_SIGNAL_IDS),
        "pick_groups": [list(group) for group in SIGNAL_PICK_GROUPS],
        "supporting_guards": SUPPORTING_GUARDS,
        "signals": signals,
        "playbook_recommended_identity": PLAYBOOK_RECOMMENDED_IDENTITY,
    }
