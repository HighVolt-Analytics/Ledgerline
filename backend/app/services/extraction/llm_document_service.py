"""Runtime LLM document classification and field extraction."""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Sequence

from pydantic import ValidationError

from app.config import get_settings
from app.schemas.document_type import DocumentTypeDefinition
from app.schemas.llm_document import LlmDocumentResult, LlmLineItem, LlmParty
from app.schemas.ocr_artifact import OcrArtifact
from app.services.extraction.azure_openai_client import chat_json_async
from app.services.invoice.invoice_data import InvoiceData, ParsedLineItem
from app.services.tenant.tenant_org_context import OrgContext
from app.services.classification.document_type_field_keys import CANONICAL_EXTRACTION_FIELD_KEYS
from app.services.extraction.line_item_skip_patterns import should_skip_line_row
from app.services.extraction.llm_catalogue_rows import build_llm_catalogue_rows
from app.services.extraction.extraction_field_values import (
    _BANK_DETAILS_LLM_KEYS,
    build_extraction_field_manifest,
    build_field_ocr_snippets,
    build_finance_field_manifest,
    build_scalar_fields_presentation_prompt,
    build_smart_ocr_excerpt,
    custom_extraction_field_descriptors,
    custom_extraction_field_keys,
    custom_extraction_fields_prompt_lines,
    effective_extraction_field_keys_for_dt,
    effective_extraction_field_keys_union,
    EXTRACTED_ONLY_ATTRS,
    expand_extraction_keys_for_llm,
    extraction_accuracy_prompt_lines,
    extraction_field_manifest_prompt_lines,
    finance_field_manifest_prompt_lines,
    filter_invoice_fields_for_keys,
    harvest_custom_fields_from_llm_raw,
    non_canonical_extraction_keys,
    normalize_di_party_fields_for_prompt,
    normalize_di_scalars_for_prompt,
    normalize_extracted_fields_map,
    PARTY_FIELD_KEYS,
    prebuilt_invoice_scalars_active,
    di_party_field_keys,
    di_party_fields_populated,
    di_scalar_fields_populated,
    di_trusted_party_fields,
    di_trusted_scalar_fields,
    field_di_authoritative,
)
from app.jurisdiction.packs import jurisdiction_pack_for_country
from app.services.extraction.party_field_service import (
    PARTY_LLM_RULES,
    apply_party_normalization_to_llm,
    party_llm_rules,
)
from app.services.shared.flexible_date import parse_flexible_date
from app.utils.logger import get_logger

logger = get_logger(__name__)

_LLM_METADATA_KEYS: tuple[str, ...] = (
    "suggested_dt",
    "confidence",
    "reasoning",
    "perspective",
    "seller",
    "buyer",
    "field_confidence",
)

_LLM_EXTRACT_SCALAR_KEYS: tuple[str, ...] = (
    "invoice_no",
    "invoice_date",
    "due_date",
    "po_reference",
    "so_reference",
    "cost_centre",
    "subtotal",
    "gst",
    "gst_rate",
    "total",
    "currency",
    "abn",
    "vendor",
    "document_heading",
    "bank_bsb",
    "bank_account",
    "bank_name",
)

_LLM_STRING_SCALAR_KEYS: frozenset[str] = frozenset(
    {
        "reasoning",
        "invoice_no",
        "invoice_date",
        "due_date",
        "po_reference",
        "so_reference",
        "cost_centre",
        "currency",
        "abn",
        "vendor",
        "document_heading",
        "bank_bsb",
        "bank_account",
        "bank_name",
    }
)

_LLM_MONEY_SCALAR_KEYS: frozenset[str] = frozenset({"subtotal", "gst", "gst_rate", "total"})


def build_llm_extract_json_keys(selected_keys: Sequence[str]) -> str:
    """Build comma-separated JSON key list for extract/classify+extract prompts."""
    from app.config import get_settings

    selected = {str(key or "").strip().lower() for key in selected_keys if str(key or "").strip()}
    llm_keys = expand_extraction_keys_for_llm(selected_keys)
    scalar_keys: list[str] = []
    for key in llm_keys:
        if key == "line_items":
            continue
        if key in ("attachment_name", "document_text", "bank_details"):
            continue
        if key in PARTY_FIELD_KEYS or key in EXTRACTED_ONLY_ATTRS:
            continue
        if key in scalar_keys:
            continue
        scalar_keys.append(key)

    metadata_keys = list(_LLM_METADATA_KEYS)
    if get_settings().use_citation_grounding and "field_citations" not in metadata_keys:
        metadata_keys.append("field_citations")
    parts = metadata_keys + scalar_keys
    if "line_items" in selected:
        parts.append("line_items")
    needs_extracted_bucket = bool(non_canonical_extraction_keys(selected_keys)) or bool(
        selected & EXTRACTED_ONLY_ATTRS
    )
    if needs_extracted_bucket:
        parts.append("extracted_fields")
    return ", ".join(parts)


def _bank_details_llm_keys() -> tuple[str, ...]:
    return _BANK_DETAILS_LLM_KEYS


def build_llm_extract_rule_lines(
    selected_keys: Sequence[str],
    *,
    di_line_items_present: bool = False,
    ocr_table_present: bool = False,
    qty_only_table_present: bool = False,
    di_scalars_active: bool = False,
    di_populated_keys: set[str] | None = None,
    charge_lines_present: bool = False,
    country: str | None = None,
) -> str:
    pack = jurisdiction_pack_for_country(country)
    selected = {str(key or "").strip().lower() for key in selected_keys if str(key or "").strip()}
    lines: list[str] = []
    scalar_keys = {k for k in selected if k not in ("line_items",)} | {
        k for k in expand_extraction_keys_for_llm(selected_keys) if k != "line_items"
    }
    if scalar_keys - {"line_items"}:
        lines.extend(
            build_scalar_fields_presentation_prompt(
                di_active=di_scalars_active,
                di_populated_keys=di_populated_keys or set(),
            )
        )
    if "line_items" in selected:
        from app.services.extraction.line_items_parser import build_line_items_presentation_prompt

        lines.extend(
            build_line_items_presentation_prompt(
                di_rows_present=di_line_items_present,
                ocr_table_present=ocr_table_present,
                qty_only_table_present=qty_only_table_present,
                charge_lines_present=charge_lines_present,
            )
        )
    if not di_scalars_active:
        if "po_reference" in selected:
            lines.append("- po_reference: purchase order number when labeled PO / Purchase Order.")
        if "so_reference" in selected:
            lines.append(
                "- so_reference: sales order number when labeled SO / Sales Order "
                "(common on AR invoices and delivery notes)."
            )
        if "cost_centre" in selected:
            lines.append("- cost_centre: department or cost centre code when explicitly labeled.")
        if "currency" in selected or {"subtotal", "gst", "total"} & selected:
            lines.append(
                f"- currency: ISO 4217 code from the document (e.g. {pack.currency}, USD, EUR). "
                "Leave empty when no currency is shown."
            )
    if "bank_details" in selected or any(key in selected for key in _bank_details_llm_keys()):
        lines.append(
            "- bank_bsb, bank_account, bank_name: extract only when explicitly labeled "
            f"({pack.bank_routing_label}, Account No, IBAN, SWIFT, Bank Name). Leave empty if absent. "
            "Never use phone numbers, invoice numbers, or tax IDs as bank details."
        )
    lines.append("- field_confidence maps every key in finance_field_manifest to 0.0-1.0 (use 0.0 when empty).")
    from app.config import get_settings

    if get_settings().use_citation_grounding:
        lines.append(
            "- field_citations maps every manifest key to {{snippet, page}}; snippet must be verbatim OCR text "
            "for non-empty fields, empty snippet when field is empty."
        )
    if "gst_rate" in selected:
        rate_hint = (
            f"e.g. {pack.statutory_tax_rate} for {pack.statutory_tax_rate}%"
            if pack.statutory_tax_rate is not None
            else "e.g. 10 for 10%"
        )
        lines.append(
            f"- gst_rate is the {pack.tax_label} percentage as a number ({rate_hint}), not a fraction."
        )
    if non_canonical_extraction_keys(selected_keys) or (selected & EXTRACTED_ONLY_ATTRS):
        lines.append(
            "- extracted_fields is an optional object for keys listed in custom_extraction_fields "
            "and extracted-only manifest keys (account_code, seller_name, etc.); use string values only."
        )
        if selected & PARTY_FIELD_KEYS:
            lines.append(
                "- Party fields (seller_name, buyer_name, etc.): populate seller/buyer objects "
                "AND extracted_fields when configured."
            )
    return "\n".join(lines)


def _build_llm_extract_system_text(json_keys: str, rule_lines: str, *, country: str | None = None) -> str:
    pack = jurisdiction_pack_for_country(country)
    return f"""You structure accounts-payable/receivable fields from the provided OCR payload into JSON.
Return JSON only with keys:
{json_keys}.

═══════════════════════════════════════════════
CORE RULES (non-negotiable)
═══════════════════════════════════════════════
1. Extract ONLY fields listed in extraction_fields / finance_field_manifest in the user payload.
   Do not add keys. Do not omit requested keys — use null if genuinely absent.
2. When ocr.scalar_fields_source is azure_di, canonical scalar values (totals, dates, tax)
   come ONLY from ocr.azure_di_scalar_fields. Never override a DI scalar with your own
   read of ocr.text_excerpt unless the DI field is explicitly null or flagged low-confidence.
3. Structure all other values strictly from ocr.text_excerpt and ocr.layout_kv.
   Never use tenant.legal_name, catalogue rows, or few_shot_examples as field VALUES —
   those are context for disambiguation only, never a source of truth for THIS document.
4. Copy values verbatim from the OCR payload. Do NOT round, calculate, infer, reformat,
   or normalize amounts, dates, or identifiers unless a specific rule below says otherwise.
5. If a field cannot be found with reasonable confidence in the OCR payload, return null.
   Never guess. Never fabricate a plausible-looking value to avoid returning null.

═══════════════════════════════════════════════
EDGE CASE RULES
═══════════════════════════════════════════════

## A. Identifier fields (invoice_no, po_no, grn_no, dn_no, so_no)
- Extract ONLY the identifier token itself. STOP at the first delimiter that is not
  part of the identifier: comma, "DATED", "OF", "/", newline, or a date pattern
  (DD.MM.YYYY, DD/MM/YYYY, YYYY-MM-DD).
  Example: "RC-SIPL-AUG-INL-20250826-001, DATED: 26.08.2025 OF THE BENEFICIARY"
           → invoice_no = "RC-SIPL-AUG-INL-20250826-001"  (NOT the trailing text)
- If multiple candidate numbers exist (e.g. "Invoice No" AND "Our Ref No" AND
  "Order No"), pick the one whose label matches the target field name most closely.
  Do not default to the first number seen top-to-bottom.
- When multiple labels could map to the same field, deprioritize any label containing
  qualifier words: PROFORMA, DRAFT, QUOTATION, ESTIMATE, PRO-FORMA (same rule for
  po_reference vs PROFORMA PO NO, etc.). Prefer the unqualified canonical label.
- If both "INVOICE NO" and "PROFORMA INVOICE NO" exist, use INVOICE NO for invoice_no.
- Do not include prefixes/suffixes like "No:", "#", "Ref:" in the value.

## B. Vendor / buyer / party names
- The party name must appear verbatim in ocr.text_excerpt or ocr.layout_kv.
  If a name only appears in tenant.legal_name, catalogue, or few_shot_examples and
  NOT in this document's OCR text, treat it as absent — return null, do not borrow it.
- For vendor/counterparty: follow document_type.counterparty_source in the user payload
  (letterhead | consignee | applicant | bill_to) — do not always default to letterhead.
- Distinguish seller vs buyer using layout position, letterhead, "Bill To" / "Ship To" /
  "From" / "Remit To" labels, and the perspective hint in the payload — not assumption.
- If the document has multiple entities with similar names (e.g. "ABC Pvt Ltd" vs
  "ABC Global Pvt Ltd" vs "ABC Distributors"), copy the FULL name exactly as printed
  next to the relevant role label. Do not truncate or merge similar-looking names.
- If a registered/legal name differs from a trading/brand name shown elsewhere in the
  document, prefer the name adjacent to the GSTIN/ABN/tax-ID block if present.
{{party_rules}}

## C. Amounts (total, subtotal, tax, freight, discount, line amounts)
- If a document has a lump-sum total with NO line-item table, set total from the
  clearly labeled total field and leave line_items as an empty array — do not
  fabricate line items to "fill" the schema.
- If freight, insurance, or other charges are listed SEPARATELY from the main total
  (e.g. "FREIGHT: USD 400.00" as a standalone line, not inside a table), still
  capture the grand total by reading the field explicitly labeled Total/Grand Total/
  Amount Due — do NOT self-sum unless no total field is present anywhere in the
  document, in which case sum only the explicitly labeled component amounts and note
  in the internal field_citations that it was derived, not read directly.
- If multiple totals appear (subtotal, tax, grand total, amount in words), map each
  to its correct field — never confuse subtotal with grand total, or paid-to-date
  with amount-due.
- Preserve the sign: credit notes / debit notes / refunds may show negative amounts
  or a "(-)" / parentheses convention — preserve that polarity in the value; do not
  silently make everything positive.
- Never convert currency. If the document states amounts in a foreign currency,
  extract the currency code/symbol as printed alongside the amount fields, and do
  not perform conversion math.
- Numeric formatting: strip thousands separators (commas/periods per locale) only
  when converting to a numeric type; preserve the original numeral characters
  otherwise. If unsure whether "1.234,56" is European (1234.56) or a typo, prefer
  the jurisdiction pack's decimal/thousands convention for {pack.country}.

## D. Dates
- Do not assume a date format. Check for explicit format hints in the document
  (e.g. "DD/MM/YYYY" printed near the field, or a month name spelling out the month
  unambiguously). If the format is genuinely ambiguous (e.g. "03/04/2025" with no
  other clues) and the jurisdiction pack specifies a default convention for
  {pack.country}, apply that convention; otherwise return the date exactly as
  printed in a date-like string rather than guessing day/month order.
- When the date format is unambiguous (month name, explicit DD/MM/YYYY hint, or
  jurisdiction-default convention for {pack.country}), output ISO YYYY-MM-DD.
- When genuinely ambiguous (e.g. "03/04/2025" with no label), return the date as
  printed — do not guess day/month order.
- Distinguish invoice_date, due_date, delivery_date, and PO date — these are often
  printed close together. Match by the adjacent label, not proximity alone.
- If a date appears embedded inside another field's text (as in the invoice_no
  example above), do not let it bleed into that field, and separately check whether
  it should populate a date field instead.

## E. Tax / registration identifiers (GSTIN, ABN, VAT number, TIN)
- Extract exactly as printed, including any embedded hyphens/spaces the document
  uses, unless the finance_field_manifest specifies a canonical format to normalize to.
- Do not confuse a tax ID with a bank account number, IBAN, SWIFT/BIC code, or an
  internal reference number — verify against the expected format/length for
  {pack.country} where the field manifest provides one.
- If both seller and buyer tax IDs are present, attribute each to the correct party
  using adjacent labels, not order of appearance.

## F. Line items
- Only extract rows that are genuinely part of the itemized table — skip subtotal
  rows, tax summary rows, "continued on next page" rows, and blank/decorative rows
  that DI or layout parsing may have picked up as table rows.
- If a table spans multiple pages, treat it as one continuous list; do not duplicate
  a repeated header row as a line item.
- If quantity, unit price, and line total are present but one is missing or
  illegible, leave that specific sub-field null rather than dropping the whole row
  or inventing the missing number from the other two (no back-calculation unless a
  rule elsewhere explicitly permits derived values).
- Merged/spanning cells: attribute merged description cells to each row they visually
  cover, not just the first row.

## G. Untrustworthy or conflicting signals
- If ocr.azure_di_scalar_fields and your own reading of ocr.text_excerpt disagree,
  DI scalars win per rule 2 above — but if a DI value looks structurally implausible
  for its field (e.g. a vendor name field containing only digits, a date field
  containing an amount), treat it as a DI extraction error, return null for that
  field, and do not attempt to silently correct it yourself.
- If a value appears ONLY in a few_shot_example or catalogue entry and nowhere in
  this document's OCR, it is contamination — never copy it into your output. Few-shot
  examples show correction PATTERNS, not values to reuse.
- If the OCR is sparse, garbled, or the document appears to be a low-quality scan,
  extract what is legible and confidently return null for the rest — do not pad
  in plausible-sounding values to make the JSON look complete.

## H. Document-type mismatches
- If confirmed_dt in the payload does not match what the document content actually
  looks like (e.g. confirmed_dt is INVOICE but the document is clearly a delivery
  note), still extract using the field manifest for confirmed_dt as instructed, but
  return null for any field that has no genuine counterpart in this document rather
  than force-mapping unrelated content into the wrong field.

## I. Duplicates / multi-document artifacts
- If the OCR text appears to contain more than one distinct document concatenated
  (e.g. a PO followed by an invoice in the same payload), extract fields belonging
  ONLY to the document type indicated by confirmed_dt, and ignore fields that belong
  to the other embedded document.

═══════════════════════════════════════════════
JURISDICTION-SPECIFIC RULES
═══════════════════════════════════════════════
{rule_lines}

═══════════════════════════════════════════════
OUTPUT DISCIPLINE
═══════════════════════════════════════════════
- Return a single JSON object. No markdown, no commentary, no trailing text.
- Every requested key must be present. Use null for genuinely unavailable values —
  never an empty string as a substitute for null, and never a placeholder like
  "N/A" or "Unknown".
- Do not wrap the JSON in a code fence.
- Metadata keys:
  - suggested_dt must match confirmed_dt from the user payload.
  - confidence is 0.0-1.0 for the document type choice.
  - perspective is purchase | sales | unknown.
  - field_confidence maps every manifest key to 0.0-1.0 (0.0 when absent).
"""


def _build_llm_combined_system_text(json_keys: str, rule_lines: str) -> str:
    return f"""You classify finance documents for accounts payable.
Return JSON only with keys:
{json_keys}.

Rules:
- suggested_dt is REQUIRED: pick exactly one DT-xx code from the catalogue codes provided.
- Use empty string only when the document is clearly not in the catalogue.
- confidence is 0.0-1.0 for the document type choice.
- Use document_heading and the first title lines of OCR as the primary classification signal.
- Certificate of Origin, Cargo Clearance Permit, Packing List, and Bill of Lading / AWB are supporting import documents — never classify them as DT-01 or DT-02.
- When the heading is unambiguous, suggested_dt must match the catalogue row whose short title best fits that heading.
- perspective is purchase | sales | unknown (tenant perspective is buyer/AP unless they are the seller).
{{party_rules}}
{rule_lines}
- Use OCR text faithfully; do not invent amounts or parties.
- few_shot_examples are prior reviewer corrections for this tenant. When document_heading or text_excerpt
  closely matches a few-shot example, strongly prefer that example's human_confirmed_dt over catalogue defaults.
- When llm_suggested_dt was wrong but human_confirmed_dt was chosen, learn from the note and excerpt."""

_SPARSE_IMAGE_EXTRACT_HINT = """
Sparse OCR: document images may be attached. Prefer ocr.text_excerpt and layout_kv.
Use images only to fill fields still missing from OCR — do not override OCR with invented values."""


def _org_role_lines(org: OrgContext) -> list[str]:
    pack = jurisdiction_pack_for_country(org.country)
    tax_id_label = pack.tax_id_label
    perspective = (org.default_perspective or "buyer").strip().lower()
    if perspective == "seller":
        return [
            "Tenant acts as accounts receivable (seller). Default perspective is sales unless the tenant appears as buyer.",
        ]
    if perspective == "mixed":
        return [
            "Tenant may act as buyer (accounts payable) or seller (accounts receivable).",
            f"Determine perspective from party names and {tax_id_label} against tenant legal_name, abn, and aliases.",
        ]
    return [
        "Tenant acts as accounts payable (buyer). Default perspective is purchase unless the tenant appears as seller.",
    ]


_LLM_CLASSIFY_SYSTEM_TEMPLATE = """You classify finance documents for accounts payable.
Return JSON only with keys:
suggested_dt, confidence, reasoning, perspective, seller, buyer, document_heading.

Rules:
- suggested_dt is REQUIRED: pick exactly one DT-xx code from the catalogue codes provided.
- Use empty string only when the document is clearly not in the catalogue.
- confidence is 0.0-1.0 for the document type choice.
- Use document_heading and the first title lines of OCR as the primary classification signal.
- Certificate of Origin, Cargo Clearance Permit, Packing List, and Bill of Lading / AWB are supporting import documents — never classify them as DT-01 or DT-02.
- When the heading is unambiguous, suggested_dt must match the catalogue row whose short title best fits that heading.
- perspective is purchase | sales | unknown (tenant perspective is buyer/AP unless they are the seller).
{party_rules}
- Do not extract invoice amounts, line items, or dates — classification only.
- few_shot_examples are prior reviewer corrections for this tenant. When document_heading or text_excerpt
  closely matches a few-shot example, strongly prefer that example's human_confirmed_dt over catalogue defaults.
- Examples with vendor_key match the sender/vendor — prefer those when the layout matches that supplier.
- Each catalogue row has recognition_mode signals or prompt.
- When recognition_mode is signals, treat recognition_rules as deterministic match hints for that code.
- When recognition_mode is prompt, treat llm_prompt as the authoritative description for that code."""


def build_classify_system_prompt(org: OrgContext) -> str:
    rules = party_llm_rules(jurisdiction_pack_for_country(org.country))
    classify = _LLM_CLASSIFY_SYSTEM_TEMPLATE.format(party_rules=rules)
    parts = [classify.strip(), "", "Tenant context:"]
    parts.extend(f"- {line}" for line in _org_role_lines(org))
    if org.intake_summary.strip():
        parts.extend(["", f"Typical intake: {org.intake_summary.strip()}"])
    if org.classification_hints.strip():
        parts.extend(["", f"Tenant guidance: {org.classification_hints.strip()}"])
    return "\n".join(parts)


def build_extract_system_prompt(
    org: OrgContext,
    *,
    playbook_profile: str | None = None,
    selected_keys: Sequence[str] | None = None,
    ocr: OcrArtifact | None = None,
) -> str:
    keys = list(selected_keys or ())
    di_line_items_present = False
    ocr_table_present = False
    di_scalars_active = False
    di_populated_keys: set[str] = set()
    qty_only_table_present = False
    charge_lines_present = False
    if ocr is not None:
        from app.services.extraction.line_items_parser import (
            document_has_charge_lines,
            document_has_product_table,
            document_has_qty_only_table,
            line_items_source_from_payload,
        )

        payload = ocr.payload_json or {}
        di_line_items_present = line_items_source_from_payload(payload) == "azure_di"
        qty_only_table_present = document_has_qty_only_table(ocr.text, payload) and not di_line_items_present
        ocr_table_present = (
            document_has_product_table(ocr.text, payload)
            and not di_line_items_present
            and not qty_only_table_present
        )
        charge_lines_present = (
            document_has_charge_lines(ocr.text)
            and not di_line_items_present
            and not qty_only_table_present
        )
        di_scalars_active = prebuilt_invoice_scalars_active(payload)
        di_populated_keys = (
            di_trusted_scalar_fields(payload, ocr.text, keys)
            if di_scalars_active and ocr.text
            else set()
        )
    json_keys = build_llm_extract_json_keys(keys)
    rule_lines = build_llm_extract_rule_lines(
        keys,
        di_line_items_present=di_line_items_present,
        ocr_table_present=ocr_table_present,
        qty_only_table_present=qty_only_table_present,
        di_scalars_active=di_scalars_active,
        di_populated_keys=di_populated_keys,
        charge_lines_present=charge_lines_present,
        country=org.country,
    )
    party_rules = party_llm_rules(jurisdiction_pack_for_country(org.country))
    base = _build_llm_extract_system_text(
        json_keys, rule_lines, country=org.country
    ).format(party_rules=party_rules)
    parts = [base, "", "Tenant context:"]
    parts.extend(f"- {line}" for line in _org_role_lines(org))
    finance_manifest = build_finance_field_manifest(keys)
    if finance_manifest:
        parts.extend(finance_field_manifest_prompt_lines(finance_manifest))
    custom_keys = non_canonical_extraction_keys(keys)
    extracted_only_keys = [key for key in keys if key in EXTRACTED_ONLY_ATTRS]
    manifest_keys = list(dict.fromkeys([*custom_keys, *extracted_only_keys]))
    if manifest_keys:
        parts.extend(custom_extraction_fields_prompt_lines(custom_extraction_field_descriptors(manifest_keys)))
    profile = (playbook_profile or "").strip().lower()
    selected = {str(key or "").strip().lower() for key in keys}
    if profile == "supporting":
        parts.extend(
            [
                "",
                "Document profile: supporting/permit — extract permit_no, consignment_ref, document_heading; "
                "do not invent invoice_no, due_date, or totals.",
            ]
        )
    elif profile == "direct_expense":
        parts.extend(
            [
                "",
                "Document profile: direct expense — prioritize vendor, total, due_date; po_reference is usually absent.",
            ]
        )
    elif profile in {"po_goods", "ar_goods"}:
        hint_keys = [key for key in ("po_reference", "vendor", "line_items", "invoice_date", "due_date") if key in selected]
        if hint_keys:
            parts.extend(
                [
                    "",
                    f"Document profile: goods invoice — extract {', '.join(hint_keys)}.",
                ]
            )
    elif profile == "credit_adjustment":
        parts.extend(
            [
                "",
                "Document profile: credit note — extract credit reference and amounts (may be negative).",
            ]
        )
    parts.extend(extraction_accuracy_prompt_lines())
    if ocr is not None and (ocr.text or "").strip():
        parts.extend(
            [
                "",
                "When ocr.field_snippets is present, use it for fields missing from ocr.text_excerpt "
                "(common on long multi-page documents).",
            ]
        )
    return "\n".join(parts)


def build_combined_system_prompt(
    org: OrgContext,
    *,
    selected_keys: Sequence[str] | None = None,
) -> str:
    keys = list(selected_keys or ())
    json_keys = build_llm_extract_json_keys(keys)
    rule_lines = build_llm_extract_rule_lines(keys, country=org.country)
    party_rules = party_llm_rules(jurisdiction_pack_for_country(org.country))
    base = _build_llm_combined_system_text(json_keys, rule_lines).format(party_rules=party_rules)
    parts = [base, "", "Tenant context:"]
    parts.extend(f"- {line}" for line in _org_role_lines(org))
    if org.intake_summary.strip():
        parts.extend(["", f"Typical intake: {org.intake_summary.strip()}"])
    if org.classification_hints.strip():
        parts.extend(["", f"Tenant classification guidance: {org.classification_hints.strip()}"])
    custom_keys = non_canonical_extraction_keys(keys)
    if custom_keys:
        parts.extend(custom_extraction_fields_prompt_lines(custom_extraction_field_descriptors(custom_keys)))
    return "\n".join(parts)


def _catalogue_rows(document_types: Sequence[DocumentTypeDefinition]) -> list[dict[str, Any]]:
    return build_llm_catalogue_rows(document_types)


def _few_shot_rows(examples: Sequence[dict[str, str]]) -> list[dict[str, str]]:
    return list(examples)[:5]


def build_llm_user_payload(
    *,
    ocr: OcrArtifact,
    org: OrgContext,
    document_types: Sequence[DocumentTypeDefinition],
    few_shots: Sequence[dict[str, str]] | None = None,
    selected_keys: Sequence[str] | None = None,
    confirmed_dt: str | None = None,
) -> str:
    excerpt = build_smart_ocr_excerpt(ocr.text)
    keys = (
        list(selected_keys)
        if selected_keys is not None
        else effective_extraction_field_keys_union(document_types)
    )
    custom_keys = non_canonical_extraction_keys(keys)
    descriptors = custom_extraction_field_descriptors(custom_keys)
    finance_manifest = build_finance_field_manifest(keys)
    payload_json = ocr.payload_json or {}
    di_scalars_active = prebuilt_invoice_scalars_active(payload_json)
    ocr_block: dict[str, Any] = {
        "text_excerpt": excerpt,
        "layout_kv": ocr.layout_kv,
        "text_length": ocr.text_length,
        "document_heading": payload_json.get("document_heading"),
    }
    field_snippets = build_field_ocr_snippets(ocr.text, keys)
    if field_snippets:
        ocr_block["field_snippets"] = field_snippets
    if di_scalars_active:
        ocr_block["scalar_fields_source"] = "azure_di"
        scalar_fields = normalize_di_scalars_for_prompt(payload_json, keys)
        if scalar_fields:
            ocr_block["azure_di_scalar_fields"] = scalar_fields
        party_fields = normalize_di_party_fields_for_prompt(payload_json, keys)
        if party_fields:
            ocr_block["azure_di_party_fields"] = party_fields
    if "line_items" in {str(k).strip().lower() for k in keys}:
        from app.services.extraction.line_items_parser import (
            deserialize_line_items,
            document_has_line_item_table,
            line_items_source_from_payload,
            normalize_di_line_items_for_prompt,
        )

        di_rows = deserialize_line_items(payload_json.get("di_line_items"))
        ocr_block["line_items_source"] = line_items_source_from_payload(payload_json)
        if di_rows:
            ocr_block["azure_di_line_items"] = normalize_di_line_items_for_prompt(di_rows)
            ocr_block["line_items_row_count"] = len(di_rows)
        elif document_has_line_item_table(ocr.text, payload_json) and payload_json.get("table_line_items"):
            ocr_block["table_line_items"] = payload_json.get("table_line_items")
    payload: dict[str, Any] = {
        "tenant": {
            "legal_name": org.legal_name,
            "abn": org.abn,
            "aliases": org.aliases,
            "default_perspective": org.default_perspective,
            "intake_summary": org.intake_summary,
            "classification_hints": org.classification_hints,
        },
        "catalogue": _catalogue_rows(document_types),
        "few_shot_examples": _few_shot_rows(few_shots or ()),
        "extraction_fields": keys,
        "extraction_field_manifest": build_extraction_field_manifest(keys),
        "finance_field_manifest": finance_manifest,
        "custom_extraction_fields": custom_keys,
        "custom_extraction_field_descriptors": descriptors,
        "canonical_extraction_fields": sorted(CANONICAL_EXTRACTION_FIELD_KEYS),
        "ocr": ocr_block,
    }
    # Attach required_fields + compact custom source hints from contracts
    if confirmed_dt:
        dt_token_early = confirmed_dt.strip().upper()
        for defn in document_types:
            if (defn.code or "").strip().upper() != dt_token_early:
                continue
            try:
                from app.services.extraction.field_contract_resolver import (
                    resolve_extraction_field_contracts_for_dt,
                )
                from app.services.extraction.field_contracts import (
                    required_keys_from_contracts,
                )

                route_hint = None
                if isinstance(payload_json, dict):
                    route_hint = payload_json.get("extraction_route")
                contracts = resolve_extraction_field_contracts_for_dt(
                    document_types,
                    dt_token_early,
                    dt_definition=defn,
                    route=route_hint,
                )
                required_keys = required_keys_from_contracts(contracts)
                if required_keys:
                    payload["required_fields"] = required_keys
                custom_hints = []
                custom_set = set(custom_keys)
                for contract in contracts:
                    if contract.key not in custom_set and contract.field_type.value != "custom":
                        continue
                    if not contract.custom_label_aliases:
                        continue
                    custom_hints.append(
                        {
                            "key": contract.key,
                            "aliases": list(contract.custom_label_aliases),
                            "preferred_sources": list(contract.authoritative_source_order)[:3],
                        }
                    )
                if custom_hints:
                    payload["field_source_hints"] = custom_hints
            except Exception:  # noqa: BLE001
                req = [
                    str(k).strip().lower()
                    for k in (defn.required_fields or [])
                    if str(k or "").strip()
                ]
                if req:
                    payload["required_fields"] = req
            break
    if not di_scalars_active:
        invoice_fields = filter_invoice_fields_for_keys(
            payload_json.get("invoice_fields") if isinstance(payload_json.get("invoice_fields"), dict) else None,
            keys,
        )
        if invoice_fields:
            payload["invoice_fields"] = invoice_fields
    if confirmed_dt:
        payload["confirmed_dt"] = confirmed_dt.strip().upper()
        dt_token = confirmed_dt.strip().upper()
        for defn in document_types:
            if (defn.code or "").strip().upper() == dt_token:
                from app.services.classification.playbook_profile_catalog import (
                    effective_counterparty_source,
                )

                payload["document_type"] = {
                    "code": defn.code,
                    "counterparty_source": effective_counterparty_source(defn),
                    "route_target": defn.route_target,
                }
                break
    return json.dumps(payload, default=str)


def _playbook_profile_for_dt(
    document_types: Sequence[DocumentTypeDefinition],
    dt_token: str,
) -> str | None:
    from app.services.classification.document_type_catalog import playbook_profile_for_dt

    for defn in document_types:
        if (defn.code or "").strip().upper() == dt_token:
            profile = playbook_profile_for_dt(defn)
            return profile or defn.playbook_profile
    return None


def _selected_keys_for_dt(
    document_types: Sequence[DocumentTypeDefinition],
    dt_token: str,
) -> list[str]:
    return effective_extraction_field_keys_for_dt(document_types, dt_token)


def build_structure_extract_prompts(
    *,
    ocr: OcrArtifact,
    org: OrgContext,
    document_types: Sequence[DocumentTypeDefinition],
    confirmed_dt: str,
    few_shots: Sequence[dict[str, str]] | None = None,
    playbook_profile: str | None = None,
    selected_keys: Sequence[str] | None = None,
    sparse: bool = False,
) -> tuple[str, str]:
    """Shared system + user prompts for OCR-first field structuring (all providers)."""
    dt_token = confirmed_dt.strip().upper()
    keys = (
        list(selected_keys)
        if selected_keys is not None
        else _selected_keys_for_dt(document_types, dt_token)
    )
    profile = playbook_profile if playbook_profile is not None else _playbook_profile_for_dt(
        document_types, dt_token
    )
    system = build_extract_system_prompt(
        org,
        playbook_profile=profile,
        selected_keys=keys,
        ocr=ocr,
    )
    if sparse:
        system = f"{system}{_SPARSE_IMAGE_EXTRACT_HINT}"
    user = build_llm_user_payload(
        ocr=ocr,
        org=org,
        document_types=document_types,
        few_shots=few_shots,
        selected_keys=keys,
        confirmed_dt=dt_token,
    )
    return system, user


def _coerce_field_confidence_map(value: Any) -> dict[str, float]:
    """LLMs sometimes emit field_confidence as a scalar (e.g. 0.0) instead of a per-field map."""
    if value is None or isinstance(value, (int, float)):
        return {}
    if not isinstance(value, dict):
        return {}
    out: dict[str, float] = {}
    for key, score in value.items():
        token = str(key or "").strip().lower()
        if not token:
            continue
        try:
            out[token] = float(score)
        except (TypeError, ValueError):
            continue
    return out


def _normalize_llm_raw(
    raw: dict[str, Any],
    *,
    selected_keys: Sequence[str] | None = None,
    custom_keys: Sequence[str] | None = None,
    trace: object | None = None,
) -> dict[str, Any]:
    """Best-effort cleanup before Pydantic validation (LLMs often emit '' or nested vendor)."""
    out = dict(raw)
    out["field_confidence"] = _coerce_field_confidence_map(out.get("field_confidence"))
    vendor = out.get("vendor")
    if isinstance(vendor, dict):
        out["vendor"] = vendor.get("name") or vendor.get("vendor") or ""

    llm_keys = expand_extraction_keys_for_llm(selected_keys or ())
    requested_strings = {key for key in llm_keys if key in _LLM_STRING_SCALAR_KEYS}
    requested_strings.add("reasoning")
    for key in requested_strings:
        if out.get(key) is None:
            out[key] = ""
    for money in _LLM_MONEY_SCALAR_KEYS:
        if money in llm_keys and out.get(money) == "":
            out[money] = None
    if "line_items" in {str(k).strip().lower() for k in (selected_keys or ())}:
        items = out.get("line_items")
        if isinstance(items, list):
            cleaned: list[dict[str, Any]] = []
            for index, row in enumerate(items):
                if not isinstance(row, dict):
                    continue
                desc = str(row.get("description") or "").strip()
                row_key = desc.lower()[:80] if desc else f"row_{index}"
                if not desc:
                    if trace is not None:
                        trace.record(row_key, "llm_normalize", "dropped", "empty_description")
                    continue
                if should_skip_line_row(desc, trace=trace, row_key=row_key):
                    continue
                item = dict(row)
                for key in ("amount", "qty", "unit_price", "tax_amount"):
                    if item.get(key) == "":
                        item[key] = None
                cleaned.append(item)
            out["line_items"] = cleaned
    harvest_keys = list(custom_keys) if custom_keys is not None else non_canonical_extraction_keys(
        selected_keys or ()
    )
    harvested = harvest_custom_fields_from_llm_raw(
        out,
        custom_keys=harvest_keys,
        selected_keys=selected_keys,
    )
    if harvested:
        out["extracted_fields"] = harvested
    else:
        extracted = out.get("extracted_fields")
        if isinstance(extracted, dict):
            out["extracted_fields"] = normalize_extracted_fields_map(extracted)
        elif extracted is not None:
            out["extracted_fields"] = {}
    return out


def _resolved_currency(llm: LlmDocumentResult) -> str:
    """Use LLM currency when present; never default when absent."""
    token = (llm.currency or "").strip().upper()
    return token


def _bank_extracted_fields(llm: LlmDocumentResult) -> dict[str, str]:
    bank_name = (llm.bank_name or "").strip()
    bank_bsb = (llm.bank_bsb or "").strip()
    bank_account = (llm.bank_account or "").strip()
    out: dict[str, str] = {}
    if bank_name:
        out["bank_name"] = bank_name
    parts = [part for part in (bank_name, bank_bsb, bank_account) if part]
    if parts:
        out["bank_details"] = " / ".join(parts)
    return out


def _canonical_scalar_extracted_fields(llm: LlmDocumentResult) -> dict[str, str]:
    out: dict[str, str] = {}
    so_ref = (llm.so_reference or "").strip()
    if so_ref:
        out["so_reference"] = so_ref
    return out


def _parsed_line_items_from_llm(
    llm: LlmDocumentResult,
    *,
    vendor: str | None,
    invoice_no: str | None,
    po_reference: str | None,
    so_reference: str | None,
    cost_centre: str | None,
    extracted_fields: dict[str, str],
    ocr_text: str | None = None,
    ocr_payload: dict[str, object] | None = None,
) -> list[ParsedLineItem]:
    from app.services.extraction.line_items_parser import (
        document_has_qty_only_table,
        enrich_parsed_line_items,
    )
    from app.services.extraction.line_items_sanitizer import sanitize_line_items

    allow_qty_only = document_has_qty_only_table(ocr_text, ocr_payload or {})
    line_items_confidence = llm.field_confidence.get("line_items")
    items = [
        ParsedLineItem(
            description=row.description or None,
            qty=row.qty,
            unit_price=row.unit_price,
            amount=row.amount,
            tax_amount=row.tax_amount,
            source="llm",
            source_confidence=line_items_confidence,
        )
        for row in llm.line_items
    ]
    cleaned = sanitize_line_items(
        items,
        extracted_fields=extracted_fields,
        vendor=vendor,
        invoice_no=invoice_no,
        po_reference=po_reference,
        so_reference=so_reference,
        cost_centre=cost_centre,
        allow_qty_only=allow_qty_only,
    )
    return enrich_parsed_line_items(cleaned)


async def classify_document_only(
    ocr: OcrArtifact,
    *,
    org: OrgContext,
    document_types: Sequence[DocumentTypeDefinition],
    few_shots: Sequence[dict[str, str]] | None = None,
) -> LlmDocumentResult | None:
    settings = get_settings()
    user = build_llm_user_payload(
        ocr=ocr,
        org=org,
        document_types=document_types,
        few_shots=few_shots,
    )
    raw = await chat_json_async(
        system=build_classify_system_prompt(org),
        user=user,
        timeout_seconds=settings.runtime_llm_timeout_seconds,
        require_runtime=True,
    )
    if raw is None:
        return None
    try:
        result = LlmDocumentResult.model_validate(_normalize_llm_raw(raw))
        result.raw = raw
        return result
    except ValidationError as exc:
        logger.warning("llm_classify_invalid", error=str(exc))
        return None


async def extract_document_fields(
    ocr: OcrArtifact,
    *,
    org: OrgContext,
    document_types: Sequence[DocumentTypeDefinition],
    confirmed_dt: str,
    few_shots: Sequence[dict[str, str]] | None = None,
) -> LlmDocumentResult | None:
    settings = get_settings()
    dt_token = confirmed_dt.strip().upper()
    selected_keys = _selected_keys_for_dt(document_types, dt_token)
    custom_keys = non_canonical_extraction_keys(selected_keys)
    system, user = build_structure_extract_prompts(
        ocr=ocr,
        org=org,
        document_types=document_types,
        confirmed_dt=dt_token,
        few_shots=few_shots,
        selected_keys=selected_keys,
    )
    raw = await chat_json_async(
        system=system,
        user=user,
        timeout_seconds=settings.runtime_llm_timeout_seconds,
        require_runtime=True,
    )
    if raw is None:
        return None
    try:
        normalized = _normalize_llm_raw(
            raw,
            selected_keys=selected_keys,
            custom_keys=custom_keys,
        )
        normalized["suggested_dt"] = dt_token
        result = LlmDocumentResult.model_validate(normalized)
        result.raw = raw
        return result
    except ValidationError as exc:
        logger.warning("llm_extract_invalid", error=str(exc))
        return None


async def classify_and_extract(
    ocr: OcrArtifact,
    *,
    org: OrgContext,
    document_types: Sequence[DocumentTypeDefinition],
    few_shots: Sequence[dict[str, str]] | None = None,
) -> LlmDocumentResult | None:
    settings = get_settings()
    selected_keys = effective_extraction_field_keys_union(document_types)
    custom_keys = non_canonical_extraction_keys(selected_keys)
    user = build_llm_user_payload(
        ocr=ocr,
        org=org,
        document_types=document_types,
        few_shots=few_shots,
        selected_keys=selected_keys,
    )
    raw = await chat_json_async(
        system=build_combined_system_prompt(org, selected_keys=selected_keys),
        user=user,
        timeout_seconds=settings.runtime_llm_timeout_seconds,
        require_runtime=True,
    )
    if raw is None:
        return None
    try:
        result = LlmDocumentResult.model_validate(
            _normalize_llm_raw(
                raw,
                selected_keys=selected_keys,
                custom_keys=custom_keys,
            )
        )
        result.raw = raw
        return result
    except ValidationError as exc:
        logger.warning("llm_document_invalid", error=str(exc))
        return None


def _parse_date(raw: str) -> date | None:
    return parse_flexible_date(raw)


def _parse_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def llm_result_to_invoice_data(
    llm: LlmDocumentResult,
    *,
    ocr: OcrArtifact,
    custom_keys: Sequence[str] | None = None,
    selected_keys: Sequence[str] | None = None,
    org: OrgContext | None = None,
    counterparty_source: str = "letterhead",
    route_target: str | None = None,
) -> InvoiceData:
    org_ctx = org or OrgContext()
    ocr_text = ocr.text or None
    _parties, perspective, finance, party_fields = apply_party_normalization_to_llm(
        llm,
        ocr_text=ocr_text,
        org=org_ctx,
        counterparty_source=counterparty_source,
        route_target=route_target,
    )

    extracted = harvest_custom_fields_from_llm_raw(
        llm.raw,
        custom_keys=custom_keys,
        selected_keys=selected_keys,
    )
    from app.services.extraction.extraction_field_values import merge_extracted_fields_with_authority

    payload = ocr.payload_json or {}
    keys_list = list(selected_keys or ())
    extracted = merge_extracted_fields_with_authority(
        base={
            **party_fields,
            **_canonical_scalar_extracted_fields(llm),
            **_bank_extracted_fields(llm),
            **extracted,
        },
        llm_extracted=llm.extracted_fields,
        payload=payload,
        selected_keys=keys_list,
        ocr_text=ocr_text,
    )
    from app.services.extraction.line_items_parser import resolve_line_items_from_ocr_payload

    di_scalars_active = prebuilt_invoice_scalars_active(payload)
    party_keys = (
        di_trusted_party_fields(payload, ocr_text, keys_list)
        if di_scalars_active and ocr_text
        else set()
    )
    if party_keys:
        for key in di_party_field_keys():
            if key in party_keys:
                extracted.pop(key, None)

    def _di_authoritative(field_key: str) -> bool:
        return field_di_authoritative(
            payload,
            field_key,
            ocr_text=ocr_text,
            selected_keys=keys_list,
        )

    if resolve_line_items_from_ocr_payload(payload):
        line_items = []
    else:
        line_items = _parsed_line_items_from_llm(
            llm,
            vendor=finance.get("vendor") if not _di_authoritative("vendor") else None,
            invoice_no=(llm.invoice_no or "").strip() or None
            if not _di_authoritative("invoice_no")
            else None,
            po_reference=(llm.po_reference or "").strip() or None
            if not _di_authoritative("po_reference")
            else None,
            so_reference=(llm.so_reference or "").strip() or extracted.get("so_reference"),
            cost_centre=(llm.cost_centre or "").strip() or None
            if not _di_authoritative("cost_centre")
            else None,
            extracted_fields=extracted,
            ocr_text=ocr_text,
            ocr_payload=payload,
        )
    from app.services.extraction.gst_rate import parse_gst_rate_percent, resolve_gst_rate_percent

    vendor = finance.get("vendor") if not _di_authoritative("vendor") else None
    abn = finance.get("abn") if not _di_authoritative("abn") else None
    billing_address = (
        finance.get("billing_address") if not _di_authoritative("billing_address") else None
    )
    invoice_no = (
        (llm.invoice_no or "").strip() or None
        if not _di_authoritative("invoice_no")
        else None
    )
    secondary_no = None
    if invoice_no:
        from app.services.extraction.invoice_no_sanitizer import (
            apply_invoice_no_secondary,
            sanitize_invoice_no_parts,
        )

        invoice_no, secondary_no = sanitize_invoice_no_parts(invoice_no)
        extracted = apply_invoice_no_secondary(extracted, secondary_no)
    invoice_date = (
        _parse_date(llm.invoice_date) if not _di_authoritative("invoice_date") else None
    )
    due_date = _parse_date(llm.due_date) if not _di_authoritative("due_date") else None
    currency = _resolved_currency(llm) if not _di_authoritative("currency") else ""
    subtotal = llm.subtotal if not _di_authoritative("subtotal") else None
    gst = llm.gst if not _di_authoritative("gst") else None
    total = llm.total if not _di_authoritative("total") else None
    po_reference = (
        (llm.po_reference or "").strip() or None
        if not _di_authoritative("po_reference")
        else None
    )
    cost_centre = (
        (llm.cost_centre or "").strip() or None
        if not _di_authoritative("cost_centre")
        else None
    )

    parsed = InvoiceData(
        vendor=vendor,
        abn=abn,
        billing_address=billing_address,
        invoice_no=invoice_no,
        invoice_date=invoice_date,
        due_date=due_date,
        currency=currency,
        subtotal=subtotal,
        gst=gst,
        gst_rate=parse_gst_rate_percent(llm.gst_rate),
        total=total,
        po_reference=po_reference,
        cost_centre=cost_centre,
        bank_bsb=(llm.bank_bsb or "").strip() or None,
        bank_account=(llm.bank_account or "").strip() or None,
        line_items=line_items,
        document_text=ocr_text,
        document_heading=(llm.document_heading or "").strip() or None,
        extracted_fields=extracted,
        raw_fields={
            "llm_suggested_dt": llm.suggested_dt,
            "llm_confidence": llm.confidence,
            "llm_perspective": llm.perspective,
            "perspective": perspective,
            "seller": llm.seller.model_dump(),
            "buyer": llm.buyer.model_dump(),
            "layout_kv": ocr.layout_kv,
            "extracted_fields": extracted,
            "_line_items_confidence": (llm.field_confidence or {}).get("line_items"),
        },
    )
    parsed.gst_rate = resolve_gst_rate_percent(parsed, ocr_text=ocr_text, allow_inference=False)
    if parsed.gst_rate is None:
        parsed.gst_rate = resolve_gst_rate_percent(parsed, allow_inference=True)
    if prebuilt_invoice_scalars_active(payload) and keys_list:
        from app.services.extraction.extraction_field_values import (
            apply_di_scalars_authoritative,
            sync_extracted_fields_with_di_authority,
        )

        parsed = apply_di_scalars_authoritative(
            parsed, payload, keys_list, ocr_text=ocr_text
        )
        parsed = sync_extracted_fields_with_di_authority(
            parsed, payload, keys_list, ocr_text=ocr_text
        )
    return parsed


def apply_document_type_to_invoice(
    invoice: object,
    *,
    code: str,
    confidence: float,
    llm_suggested_dt: str | None = None,
    llm_confidence: float | None = None,
) -> None:
    token = (code or "").strip().upper()
    setattr(invoice, "document_type_code", token or None)
    setattr(invoice, "document_type_confidence", round(confidence, 4))
    if llm_suggested_dt is not None:
        setattr(invoice, "llm_suggested_dt", (llm_suggested_dt or "").strip().upper() or None)
    if llm_confidence is not None:
        setattr(invoice, "llm_confidence", round(llm_confidence, 4))
