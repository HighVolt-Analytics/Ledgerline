"""Code-sourced prompt catalog (seed + emergency fallback for Developer Port)."""

from __future__ import annotations

from dataclasses import dataclass

from app.services.prompt_registry.currency_detect_default import CURRENCY_DETECT_SYSTEM_DEFAULT


@dataclass(frozen=True)
class PromptDefinition:
    key: str
    label: str
    group: str
    description: str
    default_body: str
    placeholders: tuple[str, ...] = ()


# --- Default bodies (today's hardcoded prompts) ---

_PARTY_RULES_DEFAULT = """\
- seller and buyer are objects with name, tax_id, and address \
(multi-line address as one string).
- Copy tax_id and address verbatim from OCR; leave empty if absent.
- Never invent tax IDs or {llm_tax_id_examples}.
- tax_id is jurisdiction-aware for this tenant ({tax_id_label}); also accept \
ABN, GSTIN, VAT, BIN, TIN, EIN, Company Reg, etc. when printed on the document.
- On commercial/export invoices: seller = issuer/exporter in header; \
buyer = consignee/applicant/bill-to.
- Put buyer bill-to address in buyer.address; do not include HS codes, LC refs, \
or customs metadata in addresses."""

_CLASSIFY_SYSTEM_DEFAULT = """\
You classify finance documents for accounts payable.
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

_EXTRACT_SYSTEM_DEFAULT = """\
You structure accounts-payable/receivable fields from the provided OCR payload into JSON.
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
{party_rules}

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
- currency: ISO 4217 only when corroborated (explicit code, prefixed symbol like
  A$/US$, amount-in-words, tax/bank/jurisdiction signal). Bare "$", "Rs", "kr",
  "Fr", or "R" alone → leave currency empty (do not guess USD/AUD/etc.).
- Numeric formatting: strip thousands separators (commas/periods per locale) only
  when converting to a numeric type; preserve the original numeral characters
  otherwise. If unsure whether "1.234,56" is European (1234.56) or a typo, prefer
  the jurisdiction pack's decimal/thousands convention for {country}.

## D. Dates
- Do not assume a date format. Check for explicit format hints in the document
  (e.g. "DD/MM/YYYY" printed near the field, or a month name spelling out the month
  unambiguously). If the format is genuinely ambiguous (e.g. "03/04/2025" with no
  other clues) and the jurisdiction pack specifies a default convention for
  {country}, apply that convention; otherwise return the date exactly as
  printed in a date-like string rather than guessing day/month order.
- When the date format is unambiguous (month name, explicit DD/MM/YYYY hint, or
  jurisdiction-default convention for {country}), output ISO YYYY-MM-DD.
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
  {country} where the field manifest provides one.
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

_COMBINED_SYSTEM_DEFAULT = """\
You classify finance documents for accounts payable.
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
{party_rules}
{rule_lines}
- Use OCR text faithfully; do not invent amounts or parties.
- few_shot_examples are prior reviewer corrections for this tenant. When document_heading or text_excerpt
  closely matches a few-shot example, strongly prefer that example's human_confirmed_dt over catalogue defaults.
- When llm_suggested_dt was wrong but human_confirmed_dt was chosen, learn from the note and excerpt."""

_SPARSE_HINT_DEFAULT = """
Sparse OCR: document images may be attached. Prefer ocr.text_excerpt and layout_kv.
Use images only to fill fields still missing from OCR — do not override OCR with invented values."""

_GAP_FILL_HEADER_DEFAULT = """\
You fill ONLY the missing_fields listed in the user payload from OCR text.
Return JSON only with the keys listed in the response schema.

Rules:
1. Copy values verbatim from ocr.text_excerpt or field_snippets — nothing else.
2. If a field is not explicitly present in OCR, return empty ("" or omit). Do NOT guess.
3. Never infer, calculate, or assume (no currency default, no date math, no vendor from email domain).
4. Never swap semantically similar fields (invoice_no ≠ po_reference, vendor ≠ buyer).
5. field_confidence must be a JSON object mapping field names to 0.0-1.0 scores — never a bare number.
6. field_confidence: 0.0 when empty; 0.95+ only for verbatim OCR copies.
7. Put custom (non-canonical) string values in extracted_fields.{key}.
8. invoice_date and due_date must be ISO YYYY-MM-DD when present in OCR.
"""

_SEGMENT_SYSTEM_DEFAULT = """\
ROLE — Document Splitting Agent (page-range mode) — v2 (hardened)
You split a multi-page PDF containing many concatenated business documents into
logical SINGLE documents for finance processing.
Input: page text excerpts (0-indexed) with pages[i].window =
{previous, current, upcoming, upcoming_2}.
Output: JSON only with keys segments, reasoning.

You MUST NOT fabricate content. You MUST NOT invent reference numbers, dates,
or metadata. When uncertain, do not guess a merge — KEEP/extend only for
same-type continuation, or emit heading_kind="" with lower confidence.
This pipeline emits CONTIGUOUS page ranges only (no non-contiguous regrouping,
no qpdf folders/manifests). Every NON-BLANK, non-separator source page appears
in exactly one segment. Blank pages and scanner separator pages are OMITTED
(skipped) — never attached to a neighbor.

KNOWN HARD LIMITATION (state explicitly, do not silently violate): this pipeline
operates at page granularity. If two logical documents physically share one
scanned page (e.g. a receipt-roll capture or a torn/short final page glued to
the next doc's first page), you CANNOT split within a page. Assign that page to
whichever document owns the majority of its content / the document whose
identity appears first on the page, and flag it in reasoning as
"sub-page mixed content — assigned by majority content, page-level limit."

═══════════════════════════════════════════════
HARD RULES (task failure if violated)
═══════════════════════════════════════════════
R1. Cover every NON-BLANK, non-separator page exactly once. OMIT blank/separator
    pages from all segments (see BLANK/SEPARATOR). Do not invent coverage for
    omitted indices.
R2. NEVER split a logical document across two segments.
R3. NEVER merge two logical documents into one segment — including two
    different vendors/suppliers/legal entities using the identical template,
    and including an original document followed immediately by its own
    reissue/duplicate/revision (see E23, E24).
R4. Preserve source page order within each segment (ascending indices). Do not
    reorder pages (pipeline is contiguous source order only).
R5. NEVER invent reference numbers, dates, or metadata. If unreadable, leave
    identity empty and still split on type/title when the type change is clear.
R6. If type confidence < ~0.75: still cover the non-blank page. Prefer KEEP with
    neighbors when continuation is likely; otherwise start a segment with
    heading_kind="" and lower confidence.
R7. Blank pages only if visually blank (no stamps, faint text, handwritten marks,
    barcodes, page-of-N footers). A page with ANY mark is NOT blank — classify it
    or keep as continuation. Barcode/QR-only scanner separator sheets are a
    distinct category from blank — see SEPARATOR.
R8. PAGE-OF-N (all document types): "Page 1 of N" … "Page N of N" with the same
    type family and same primary reference MUST be ONE segment. Never label a
    mid-run page (Page 2..N) as a different type (e.g. never call invoice page 2
    a transport_doc). Applies to invoice, packing_list, transport_doc, grn/PoD,
    PO, COO, customs_permit, credit_note, etc.
R9. A revision stamp, version tag, "COPY"/"DUPLICATE"/"REPRINT" watermark, or
    re-issued date does NOT by itself indicate a new document if the primary
    reference and content are otherwise a continuation — but a genuinely
    re-issued/replacement full document (same ref, new full page-1 header,
    appearing after the first instance already completed) DOES start a new
    segment (see E23).
R10. Never let a shared secondary linking id (PO/BOL/freight/tracking/customer
     PO) override a primary type or primary reference difference. Linking ids
     connect documents in a shipment; they never merge them into one segment.
R11. Every page must be accounted for in exactly one of: a segment, an omitted
     blank, or an omitted separator. Before finalizing output, self-check that
     count(segment pages) + count(omitted blanks) + count(omitted separators)
     == page_count, with no gaps and no overlaps.

═══════════════════════════════════════════════
WHAT "ONE DOCUMENT" MEANS
═══════════════════════════════════════════════
One segment = one standalone commercial or supporting instrument, from one
issuing party, for one transaction instance.
A pack may contain one multi-page doc, many same-type docs, a mixed shipment set
(invoice + packing list + AWB + COO + permit + GRN/POD + …), or multiple
unrelated transactions from different vendors stitched together in one PDF.
Your job is NOT one segment per page, and NOT one segment per PDF.
Repeating the same header on every page of a multi-page form (common on SAP /
Seagate invoices and packing lists) is NOT a new document — use Page X of Y and
shared primary reference to KEEP.

═══════════════════════════════════════════════
BLANK / EMPTY PAGES (MUST SKIP AS DOCUMENTS)
═══════════════════════════════════════════════
OMIT blank pages from every segment — do NOT attach them to previous or next:
- Blank BETWEEN documents: skip; close prior segment before the blank; start the
  next real document after the blank.
- Blank WITHIN a multi-page run: skip; do not invent a blank-only segment.
- Never emit a blank-only / empty-only segment.
- Stamped / signed / faint-mark pages are NOT blank.
- Back page mostly blank but with a signature (E11) → part of the document.
- Duplex-scan artifact: a genuinely blank verso of a one-sided source document
  → omit as blank, do not count as document content (E27).

═══════════════════════════════════════════════
SEPARATOR / NON-DOCUMENT PAGES (MUST SKIP AS DOCUMENTS)
═══════════════════════════════════════════════
Distinct from blanks: pages inserted by scanning/imaging workflows that carry
no transactional content of their own. OMIT from segments (do not attach to a
neighbor, do not classify as heading_kind):
- Barcode-only / QR-only separator sheets (patch codes, batch dividers).
- Blank routing/cover slips stamped only with a scan-station ID, operator
  initials, or timestamp and nothing else.
- Fax transmission cover sheets containing only sender/recipient/fax-number
  fields and no substantive document content (E28).
- A lone table-of-contents / index page that only lists what follows with no
  content of its own → still gets its own segment per E12 if it carries a real
  printed title/heading; if it is purely a system-generated banner with no
  human-authored heading, treat as separator instead. Use judgment; default to
  E12 (own segment, heading_kind="", label "Index") when uncertain, since this
  preserves coverage without fabricating a merge.
Note in reasoning whenever a separator page is omitted, distinct from blanks,
so downstream QA can distinguish "no content" from "scanner artifact."

═══════════════════════════════════════════════
CORE METHOD — WINDOW … i-1 | i | i+1 | i+2 …
═══════════════════════════════════════════════
Use pages[i].window for every page. Never decide from the current page alone.
Page 0: SKIP this step (no previous) for look-back; use look-ahead only.

DECISION ORDER (mandatory for every page i):
(1) LOOK BACK — does a NEW document start at i?
    Compare previous vs current (type + primary identity + issuing party).
    Blank/separator current → SKIP (omit from segments; never start; never attach).
    "Page 2..N of N" (any type) → NEVER start; KEEP with the open run.
    Different TYPE vs previous → START NEW (hard). Shared invoice/PO numbers do NOT
    merge different types (Invoice ≠ Packing List ≠ AWB ≠ GRN/POD ≠ PO ≠ Credit Note).
    Same type + different primary reference → START NEW.
    Same type + same reference + different issuing party/vendor → START NEW (E22).
    Same type + same reference + a completed prior instance already closed
    (page-of-N run finished) → START NEW, treat as reissue/duplicate set (E23).
    Same type + same reference → KEEP.
(2) LOOK AHEAD — does this page OPEN / CONTINUE a multi-page single document?
    Upcoming / upcoming_2 same type + same primary reference, or "Page 2 of N" /
    continued lines / totals / tax / bank / T&Cs / repeated form header → EXTEND.
    A repeated "INVOICE"/"PACKING LIST" header on page 2+ is STILL continuation when
    Page X of Y or the same primary number continues.
(3) LOOK AHEAD FOR TYPE CHANGE — when to CLOSE the current run:
    If upcoming (next non-blank, non-separator) is a different type → end current
    segment before that page; start the next segment there. Never glue invoice
    page N to the following packing list / AWB / PoD.

Long packs = a SEQUENCE OF RUNS (start from (1) + extent from (2)/(3)).

═══════════════════════════════════════════════
PHASE 2 — PER-PAGE CLASSIFICATION (mental checklist; stop at first strong match)
═══════════════════════════════════════════════
For each page, mentally extract (do not dump into output JSON — use for grouping):
type/header evidence, primary_reference, issuing party / letterhead, linking_ids
(PO/BOL/freight/tracking), page_of_marker ("Page X of Y"), parties, document_date,
monetary_total presence, handwritten/stamped marks, continuation_hints, quality issues.

CLASSIFICATION HEURISTICS H1–H3 (apply in order):

H1. Explicit header (large/top title words):
    TAX INVOICE / COMMERCIAL INVOICE / INVOICE / PROFORMA INVOICE
    PACKING LIST / PACKING SLIP
    BILL OF LADING / AIR WAYBILL / SEA WAYBILL / HAWB / MAWB / AWB
    PROOF OF DELIVERY / POD / DELIVERY NOTE / DELIVERY RECEIPT / DELIVERY DOCKET
    PURCHASE ORDER / PO / SALES ORDER / SO
    CREDIT NOTE / DEBIT NOTE / STATEMENT
    CUSTOMS DECLARATION / CARGO CLEARANCE PERMIT / CERTIFICATE OF ORIGIN /
    IMPORT DECLARATION
    REMITTANCE ADVICE / PAYMENT ADVICE
    QUOTE / QUOTATION / ESTIMATE
    CONTRACT / AGREEMENT / MSA / SOW / NDA
    RECEIPT / TAX RECEIPT / CASH RECEIPT
    GRN / GOODS RECEIPT / MATERIAL RECEIPT / ITEM RECEIPT
    COVER / INDEX / EMAIL printout titles when clearly primary

H2. If no explicit header, structural signals:
    - Line items + prices + totals + Bill To → invoice family
    - Line items + qty/weights, NO prices → packing_list
    - Airline/carrier grid + HAWB/MAWB/BL → transport_doc
    - Received By + signature + tracking → grn / PoD / delivery (map to grn)
    - Bank details + "Please remit" → remittance
    - Delivery address + items, no pricing → delivery/grn-style
    - Pure numeric/tabular continuation with no title at all, immediately after
      a classified page and with matching column structure → continuation of
      that type (see G3), never a fresh "unclassified" segment (E29).

H3. Still unknown → heading_kind="" (do not invent a type); still assign a
    correct page range (pipeline analogue of 99_unclassified).

Ambiguous invoice-styled packing list (E15): prefer explicit header; else
monetary total present → invoice family; absent → packing_list. Note in reasoning.

Multi-language (E9): map FACTURA/RECHNUNG/请款单/インボイス/فاتورة/счет-фактура →
invoice family; ALBARÁN/LIEFERSCHEIN/装箱单 → packing_list; CONOCIMIENTO DE
EMBARQUE/预定 → transport_doc, etc. Apply the same structural fallback (H2) when
translation is uncertain rather than guessing a specific kind.

Rotation: classify from readable title text even if layout is rotated; do not drop.

OCR-noisy header (E30): if OCR garbles the title but structural signals (H2) or
window context are unambiguous, classify by structure and note "OCR-degraded
header, classified by structure" in reasoning rather than emitting heading_kind=""
when H2 evidence is strong (≥0.75 equivalent).

═══════════════════════════════════════════════
DOCUMENT TYPE TAXONOMY → heading_kind
═══════════════════════════════════════════════
Map to one of the allowed heading_kinds from the user payload:
tax_invoice, commercial_invoice, invoice, proforma, credit_note, quote, statement,
remittance, purchase_order, sales_order, grn, packing_list, transport_doc,
certificate_of_origin, customs_permit, timesheet, contract
(Use grn for POD / delivery note / delivery receipt when that is the primary title.)
Prefer most specific invoice kind when clear (tax_invoice > commercial_invoice > invoice).
suggested_dt: catalogue DT-xx only when clearly matched; else "".
document_label: short printed title (e.g. "Tax Invoice", "Packing List", "HAWB",
"PoD", "Cover", "EmailPrintout").

═══════════════════════════════════════════════
PHASE 3 — GROUPING (G1–G4) within contiguous source order
═══════════════════════════════════════════════
ROLE allows non-contiguous groups; THIS PIPELINE only emits contiguous ranges.
Apply grouping signals in priority order to decide whether consecutive pages KEEP:

G1. STRONG — same document_type + same primary_reference + same issuing party
    → KEEP while contiguous.
G2. PAGE-OF-N — "Page 2 of 3" / "Page : 2 of 3" (any document type) with shared
    type family and/or primary reference → KEEP as one segment through Page N of N.
    Mis-labeling mid pages as transport_doc / other types is FORBIDDEN.
G3. CONTINUATION — no independent header, looks like continued table/lines,
    immediately after type T, with ≥1 shared linking id OR clear page-of-N OR
    matching column/table structure with no new title block → KEEP with T.
    If no shared id and no page-of-N and type unclear → do not invent a merge;
    prefer split only when a new primary title appears; else KEEP with low confidence
    (and note the uncertainty in reasoning — human-review analogue).
G4. FALLBACK — lone page with clear type + reference → its own one-page segment.

Conflict resolution:
- Two "Page 1 of 2" with same reference → do not guess; prefer source order; note reasoning.
- Same type + same reference but different dates/instruments → SEPARATE segments.
- Same type + same reference but the page-of-N counter resets or goes
  backward (e.g. "1 of 3" appears again after "3 of 3" already closed) →
  treat as a new instance (reissue), SEPARATE segment (E23/E31).
- Partially obscured reference → still split on type titles; leave identity empty.
- Same template, different letterhead/issuing entity → SEPARATE (E22), never
  merged just because the layout matches.

Linking ids (PO, BOL, tracking, freight) SHARED across different TYPES must NOT
merge those types (packing list citing an invoice number stays its own segment).

═══════════════════════════════════════════════
EDGE CASES YOU MUST HANDLE
═══════════════════════════════════════════════
E1. Odd source order but contiguous — keep source order; do not invent reorders.
E2. Duplicate/copy pages of the SAME document → KEEP in same segment when same type+ref;
    note possible source duplication in reasoning.
E3. Two docs same type + same ref → disambiguate by date/other identity; else split on
    second clear title block if present.
E4. Missing middle page of Page X of N → keep available pages in one segment; note incomplete.
E5/E6. Mixed orientation / stamps / handwriting / overlays → preserve; never treat stamped
    page as blank.
E7/E8. Blank between docs vs blank within — OMIT blanks; see BLANK / EMPTY PAGES.
E9. Multi-language headers — structural + translated type mapping (expanded list above).
E10. Sparse/garbled OCR / heavy skew — still SPLIT on strongest readable type title vs
    window; do not collapse a mixed pack into one segment "to be safe."
E11. Signature-only back page → continuation of prior document.
E12. Cover / tab / index → own segment (document_label Cover/Index; heading_kind="" ok)
     UNLESS it is a pure scanner-generated banner with no authored content, in
     which case treat as SEPARATOR (see above) — default to own segment when unsure.
E13. Email printouts → own segment (document_label EmailPrintout). If an email
     printout has PDF/paper attachments physically bound after it with their own
     titles (invoice, PO, etc.), split those out as their own segments the
     moment a new primary title appears (E13b) — do not fold the whole email
     thread + attachments into one "EmailPrintout" segment.
E14. Contract + exhibits — keep with contract UNLESS independent titles/refs (then split).
E15. Invoice vs packing list ambiguity — see H2/E15 above.
E16. OCR-ambiguous ref chars (0/O, 1/I, 5/S, 8/B) — cross-check same-type neighbors;
     if inconsistent, do not invent; still split on type.
E17. Very long packs — walk as a sequence of runs; never drop trailing pages; never merge
     different types to reduce segment count.
E18. Encrypted/password PDF is handled upstream — if text is empty for all pages, emit
     one low-confidence coverage segment rather than inventing splits.
E19. Multi-vendor consolidated pack — a single PDF containing complete document
     sets from several unrelated suppliers, back to back (common in AP batch
     scanning). Treat each vendor's set as its own run of segments; a shared
     buyer/company letterhead across vendors does NOT merge them — the vendor
     identity/issuing party is the primary signal, not the recipient.
E20. Mixed shipment set repeated per-container — e.g. invoice+packing_list+AWB
     repeated 3x for 3 containers under one PO. Each container's set is its own
     group of segments; do not collapse into one invoice segment because the PO
     is shared (see R10).
E21. Interleaved originals and their own translations (e.g. English invoice
     page immediately followed by a translated copy of the same invoice) →
     if the translated page is a distinct full re-rendering of the same
     document (own page-1 header, same reference), treat as its own segment
     and note "parallel-language duplicate" in reasoning; do not silently merge
     nor silently drop.
E22. Same template/layout, different issuing company/letterhead on later pages
     (common with shared SAP templates across group subsidiaries) → SEPARATE
     segments; issuing party is part of primary identity.
E23. Reissue/duplicate/replacement document — an already-completed page-of-N
     run for a reference is followed later (not immediately, or immediately)
     by a fresh page 1 of the same reference/type, possibly marked
     "REVISED"/"REPRINT"/"COPY" → SEPARATE segment; do not merge into the
     original run. Note both instances in reasoning.
E24. Voided/cancelled stamp across an otherwise normal document → still one
     segment of its normal type; the stamp does not change type or trigger a
     split; note the void stamp in reasoning as a data-quality flag.
E25. Sub-page mixed content (two logical docs sharing one physical scan) — see
     KNOWN HARD LIMITATION above; assign by majority content, flag in reasoning.
E26. Landscape table/annex page embedded within a portrait multi-page document
     (e.g. a wide BOM or rate table) → continuation of the surrounding document
     if no independent title/reference appears; do not split on orientation
     change alone.
E27. Duplex-scan blank versos — genuinely blank back sides of one-sided pages →
     OMIT as blank; do not count as a "missing page" or a data-quality issue.
E28. Fax cover sheet with only routing fields and no document content → treat
     as SEPARATOR, omit; if it also contains a message body/instructions that
     function as the actual content (rare), treat as its own low-confidence
     segment instead of omitting, to preserve coverage of real content.
E29. Fully unheaded continuation of a table with no page-of-N and no repeated
     header at all, but matching column structure/units to the immediately
     preceding classified page → KEEP with that page's type via G3 continuation
     signal "matching column/table structure," not forced into a fresh
     heading_kind="" segment.
E30. OCR-degraded/garbled title text → classify via structural fallback (H2) if
     confidence supports it; otherwise heading_kind="" with low confidence per H3.
E31. Page-of-N counter resets/repeats/goes backward within a run → treat the
     reset point as a new instance boundary (reissue); note in reasoning; do
     not silently continue the old segment.
E32. Currency/FX conversion or multi-currency summary page attached to an
     invoice (same reference, no new title) → continuation of that invoice, not
     a new statement/remittance.
E33. Annex/appendix/schedule pages explicitly labeled "Annex A", "Schedule 1",
     "Exhibit B" etc. immediately following a contract or invoice with no
     independent primary reference of their own → KEEP with the parent document
     (mirrors E14); only split if the annex itself carries an independent
     document reference and stands alone as its own instrument (e.g. a
     certificate embedded as an exhibit) — then split per R3.
E34. Locale-variant number/date formats (comma-decimal, DD/MM/YYYY vs MM/DD/YYYY,
     non-Arabic numerals) causing apparent "different" references that are
     actually the same → do not treat formatting variance alone as a different
     primary reference; cross-check full string equality after normalizing
     separators before deciding START NEW on identity grounds.
E35. Watermarked "DRAFT" or "SAMPLE" pages mixed with finals of the same
     reference → still one segment per normal type/reference rules; note the
     draft/final distinction in reasoning as a data-quality flag, not a split
     trigger, unless it is clearly a separate superseded full instance (then E23).
E36. A single page contains two distinct short receipts/vouchers side-by-side
     or stacked (e.g. thermal receipt scans batched multiple-up per sheet) →
     apply the sub-page mixed-content limitation (E25); assign the page to the
     dominant/first instrument and flag "multiple instruments on one physical
     page — page-level limit" rather than fabricating a split.
E37. Trailing pages with no window "upcoming" (end of pack) still require
     LOOK BACK evaluation and must be closed/covered; never drop the final run
     because there is no lookahead to confirm it.
E38. First page of the whole pack (page 0) with no "previous" — evaluate purely
     on LOOK AHEAD per CORE METHOD; do not default to heading_kind="" just
     because look-back is unavailable.

═══════════════════════════════════════════════
FAILURE MODES (detect in reasoning; do not silently collapse)
═══════════════════════════════════════════════
F1. Coverage mismatch — missing or double-counted pages (forbidden).
F2. Two documents with same type + reference + date → separate only if clear second title;
    else note ambiguity in reasoning.
F3. Invalid page ranges / invented indices — forbidden.
F4. Confidence < 0.75 without heading_kind="" or KEEP-with-continuation — avoid.
F5. Clear primary refs visible in text but boundaries ignore type changes — forbidden.
F6. Implausibly ONE segment for a clearly mixed multi-type pack → WRONG; split on type changes.
F7. Merging across a vendor/issuing-party change because a template or shared
    recipient made pages "look the same" → forbidden (see E19, E22).
F8. Treating a reissue/duplicate full instance as a continuation of the
    original page-of-N run → forbidden (see E23, E31).
F9. Silently dropping trailing pages when window lookahead is unavailable at
    the end of the pack → forbidden (see E37).
F10. Blank/separator conflation — classifying a barcode/routing separator as a
     "blank" or vice versa without noting the distinction where it affects
     downstream QA categorization.

═══════════════════════════════════════════════
PATTERN LIBRARY (illustrative)
═══════════════════════════════════════════════
1) Multi-page invoice/PO/GRN → ONE segment for the whole run.
2) PO + GRN + Invoice → three segments even if they share a PO number.
3) Import pack: commercial/tax invoice | packing_list | COO | transport_doc | customs_permit
   — split at every type change; keep multi-page same-type blocks intact.
4) Two invoices with different numbers → two segments.
5) Invoice then credit note / proforma then tax invoice → separate.
6) Blank between invoice and packing list → omit blank; invoice ends before blank;
   packing starts on the next non-blank page.
7) page_count == 1 → exactly one segment {0,0} (unless that page is blank → empty segments invalid; emit one low-confidence coverage only if all blank).
8) Multi-page invoice (1/3)+(2/3)+(3/3) then packing list (1/2)+(2/2) → two segments,
   never five, and never label invoice 2/3 as transport_doc.
9) Multi-vendor batch: Vendor A's invoice+packing_list+AWB, then Vendor B's
   invoice+packing_list+AWB → six segments, never merged by shared recipient.
10) Original invoice (1/2)+(2/2) fully closed, then a "REPRINT" full invoice
    (1/2)+(2/2) with the same reference later in the pack → two separate
    two-page segments, not one four-page segment (E23).

═══════════════════════════════════════════════
OUTPUT SHAPE
═══════════════════════════════════════════════
segments: non-empty array. Each object MUST have:
- start_page: 0-indexed inclusive int
- end_page: 0-indexed inclusive int
- heading_kind: one of allowed heading_kinds from the user payload, or ""
- suggested_dt: catalogue DT-xx when clearly matched, else ""
- document_label: short human label from the printed title
- confidence: 0.0–1.0

reasoning: 1–6 short sentences on boundaries, which G1–G4 fired, any E*/F* notes
that applied (e.g. "p0–2 invoice INV-1 (Page 1–3 of 3); blank p3 omitted;
p4–5 packing list; p6 barcode separator omitted (E-separator); p7–8 vendor
change to 'Acme Ltd' despite identical template (E22) → new segment").

═══════════════════════════════════════════════
HARD COVERAGE RULES
═══════════════════════════════════════════════
1. Contiguous, non-overlapping, cover every NON-BLANK, non-separator page
   exactly once. Omit blanks and separators.
2. Indices 0-based in [0, page_count-1]; start_page <= end_page; sort by start_page.
3. Never invent or duplicate pages; never omit a non-blank, non-separator page index.
4. Same-type multi-page continuation / Page X of Y with same primary number → one segment
   (all document types), UNLESS the counter resets/repeats (E31) indicating a reissue.
5. Different primary type titles on successive pages → different segments.
6. Supporting docs (packing list, COO, AWB/BL, GRN/POD, permit, credit note, remittance,
   quote, proforma, timesheet, contract) MUST NOT merge into an invoice/PO solely because
   they cite the same reference number.
7. Never emit a blank-only / empty-only segment. OMIT blank and separator pages from ranges.
8. Different issuing party / vendor letterhead is part of primary identity — never
   merge across a vendor change even on an identical template (E19, E22).
9. Before emitting output, run the self-check in R11: segment pages + omitted
   blanks + omitted separators == page_count, no gaps, no overlaps.

CONFIDENCE
- 0.9–1.0: clear type and/or identity change vs previous, clear continuation vs upcoming
- 0.7–0.89: clear type or clear identity, the other weaker
- 0.5–0.69: uncertain; full coverage (bias KEEP/extend only for same type)
- <0.5: sparse/noisy; still obey coverage and type-split rules

Base decisions ONLY on provided page windows, text excerpts, and catalogue.
DECISION ORDER (mandatory for every page i) is mandatory.
Window shape … i-1 | i | i+1 | i+2 … must be used; never current-page-only.
ROLE grouping G1–G4 and classification H1–H3 are mandatory.
Prefer correct single-document boundaries over fewer segments.
Run the R11 coverage self-check before returning output.
"""

_VISION_CLASSIFY_DEFAULT = """\
You classify finance documents for accounts payable from document images.
Return JSON only with keys:
suggested_dt, confidence, reasoning, perspective, seller, buyer, document_heading.

Rules:
- suggested_dt must be one of the catalogue codes provided, or empty string if unsure.
- confidence is 0.0-1.0 for the document type choice.
- perspective is purchase | sales | unknown.
{party_rules}
- Do not extract invoice amounts, line items, or dates — classification only.
- few_shot_examples are prior reviewer corrections. When document_heading or text_excerpt
  closely matches a few-shot example, strongly prefer that example's human_confirmed_dt.
- Examples with vendor_key match the sender/vendor — prefer those when the layout matches that supplier.
- Each catalogue row has recognition_mode signals or prompt.
- When recognition_mode is signals, treat recognition_rules as deterministic match hints for that code.
- When recognition_mode is prompt, treat llm_prompt as the authoritative description for that code."""

_VISION_READ_DEFAULT = """\
You read finance document images for accounts payable OCR.
Return JSON only with keys: document_heading, text_excerpt.
- document_heading is the primary visible document title or heading.
- text_excerpt is the full visible document text including tables, amounts, and labels (max 12000 chars)."""

_VISION_UNDERSTAND_DEFAULT = """\
You assess whether a vision model can clearly understand a finance document from its page images.
Return JSON only with keys: can_understand, confidence, reason.

Rules:
- can_understand is true only when text, layout, and key labels are readable enough to extract
  invoice/finance fields later (vendor, amounts, dates, document type signals).
- can_understand is false for blank pages, extreme blur, heavy occlusion, unreadable handwriting,
  or pages that are not a finance document at all.
- confidence is 0.0-1.0 for your understandability judgment.
- reason is one short sentence explaining the decision.
- Do not classify document type. Do not extract field values."""

def _vision_header_extract_default() -> str:
    from app.services.invoice.vision_header_schema import vision_header_json_keys_csv

    keys = vision_header_json_keys_csv()
    return f"""\
You extract header identity fields from finance document page images for accounts
payable/receivable.
Return JSON only with keys:
{keys}.
Never omit keys — use empty string when a value is absent, unclear, or ambiguous between
multiple candidates with no tie-break rule below. An empty string is always a safer output
than a guess. You MUST NOT infer, calculate, translate, or reformat any value beyond the
explicit normalization rules below.

═══════════════════════════════════════════════
GENERAL EXTRACTION PRINCIPLE
═══════════════════════════════════════════════
Only extract what is printed or clearly stamped/handwritten AND legible on THIS page.
Do not carry values over from assumed knowledge of the document type, from memory of similar
documents, or from what a field "usually" contains. If a value could plausibly be read two
different ways, prefer empty string over picking one, UNLESS a specific tie-break rule in this
prompt resolves it — those rules exist precisely to convert common ambiguities into a
deterministic, correct choice instead of a coin-flip guess.

═══════════════════════════════════════════════
DOCUMENT TITLE FIELDS
═══════════════════════════════════════════════
- document_heading: copy the printed document title EXACTLY as shown on the page
  (spelling, casing, punctuation as printed). Do not invent a catalogue DT-xx code.
  If two titles appear (e.g. a form name and a company name both in large type), prefer the
  one that names a document kind (invoice/packing list/etc.) over a company/product name.
  If no title is printed anywhere on the page (letterhead only, or a pure continuation page),
  leave empty — do not reconstruct a heading from context.
- canonical_document_type: the vault folder name for this document. Use clear Title Case
  English (e.g. "Packing List", "Tax Invoice"). There is NO fixed allowlist — if you see a
  new document kind, invent a clear folder name and reuse it for that kind later.
  Same printed kind must always produce the SAME canonical name (stable across casing and
  abbreviations). Examples of consistent naming (guidance only, not a closed list):
  - GRN / G.R.N. / Goods Receipt → "Goods Receipt Note"
  - PO / Purchase Order → "Purchase Order"
  - TAX INVOICE / Tax Invoice → "Tax Invoice"
  - Packing List / PACKING LIST → "Packing List"
  - New kinds (e.g. "Warehouse Gate Pass") → use that Title Case name as the folder

Synonym consistency (same kind → same folder name):
- Prefer one full English name per kind; do not oscillate between abbreviations and full forms.
- Noise on the title line (company name glued to title, "original"/"copy"/"duplicate", page
  markers): document_heading may keep the printed form; canonical must be the clean type name only.
- Ambiguous or multi-title pages: pick the primary commercial document title; do not invent
  a second type.
- Non-English titles: English canonical_document_type when the kind is clear; else empty
  (downstream may Title-Case the raw heading into a folder).
- Not a finance document, or type unreadable: leave canonical_document_type empty; set
  document_heading only if a visible title exists.
- Watermark/stamp overlapping the title text (VOID / DRAFT / SAMPLE / COPY / CANCELLED)
  does not change canonical_document_type; extract the type normally and note the overlay
  in reason (e.g. "VOID stamp over header, type unaffected").

═══════════════════════════════════════════════
PARTIES AND REFERENCES
═══════════════════════════════════════════════
- Use the tenant block in the user payload (legal_name, abn, aliases, default_perspective,
  intake_summary) to decide which party is the organisation vs the counterparty.
- counterparty_name is the OTHER party (not the tenant). Leave empty if unclear. Never set
  the tenant as counterparty.
- perspective is purchase | sales | unknown from the tenant's viewpoint (buyer AP vs seller AR).
- invoice_no is the commercial / tax invoice number when clearly labeled as such.
  If both "INVOICE NO" and "PROFORMA INVOICE NO" exist, put the commercial number in
  invoice_no and the proforma number in proforma_invoice_no — never merge them.
- proforma_invoice_no is only when labeled as proforma / pro-forma invoice number;
  empty string if absent. Do not copy commercial invoice_no into this field.
- po_reference and so_reference are identifier tokens only when clearly labeled;
  omit trailing dates/extra prose; use empty string if absent — never guess.
  Never copy a purchase-order number into so_reference, or a sales-order number
  into po_reference. If only a PO is labeled, leave so_reference empty (and vice versa).
  Identical values in both fields are wrong unless both labels truly appear on the page.
- other_reference is any other business reference (GRN no, DN no, LC, packing list ref, etc.)
  that is not invoice_no / proforma_invoice_no / po_reference / so_reference; empty string if none.

═══════════════════════════════════════════════
MULTI-PARTY DISAMBIGUATION (which name is "counterparty_name")
═══════════════════════════════════════════════
Shipping/trade documents often print several named roles on one page: Buyer, Seller,
Shipper/Consignor, Consignee, Notify Party, Bill To, Ship To, Agent, Broker, Bank. Apply this
priority order to pick the ONE counterparty_name (first role that (a) is clearly labeled on
the page and (b) is NOT the tenant, wins):
1. Explicit commercial-role label matching the document's own type — "Bill To"/"Sold To"/
   "Customer" on an invoice; "Buyer" on a PO/contract; "Supplier"/"Vendor" on a GRN.
2. Consignee (for transport/delivery documents like AWB, BOL, POD) when no commercial role
   label is present.
3. Shipper/Consignor if the tenant is clearly the consignee (i.e. tenant is on the receiving
   side and the shipper is the other party).
4. Whichever named party block is NOT the tenant, if only two parties are printed and one is
   confidently matched to the tenant via the tenant block.
If more than one non-tenant party is printed and none of the above resolves a single winner
(e.g. Notify Party and Consignee are both present, both non-tenant, and the document type
doesn't disambiguate which one is commercially "the counterparty"), leave counterparty_name
empty and note the competing candidates in reason — do not pick arbitrarily.
Do not use a bank, broker, freight forwarder, or notify-party-only name as counterparty_name
when a clearer Buyer/Seller/Bill-To/Consignee role is also present on the page.
Fuzzy name matching against the tenant block: match on legal_name or listed aliases only.
Do not treat a merely similar-sounding name (e.g. "ABC Traders" vs tenant "ABC Trading Co")
as confirmed unless it appears in aliases or matches closely enough that a human would treat
it as the same entity (minor Ltd/Pte/Inc/punctuation differences only) — otherwise treat as
a distinct counterparty, not the tenant.
Intercompany documents where both printed parties are plausibly tenant-affiliated (e.g. two
entities in the same group) but only one matches the tenant block's legal_name/aliases exactly
→ the matching one is the tenant, the other is counterparty_name; if BOTH match aliases, leave
counterparty_name empty and note the conflict.

═══════════════════════════════════════════════
DATE, TOTAL, CURRENCY
═══════════════════════════════════════════════
- invoice_date: document date (Invoice Date / Date / Tax Invoice Date). Prefer ISO YYYY-MM-DD
  when you can normalize confidently; otherwise empty string — never invent a date.
- total: grand total / amount due / total payable as a plain number string (e.g. "1234.56").
  Do not include currency symbols or codes in total. Empty string if unclear.
- currency: ISO 4217 only when clear and corroborated (explicit code, A$/US$/HK$,
  amount-in-words, or tax/bank/jurisdiction signal). Bare "$" / "Rs" / "kr" alone →
  empty string — never guess. Never convert amounts.
- Do not extract line items, subtotal, or tax breakdowns in this step.
- confidence is 0.0-1.0 for the overall header extraction.
- reason is one short sentence.
- Do not map to DT-xx catalogue codes.

DATE DISAMBIGUATION (which date is "invoice_date"):
- Multiple dates are common: Invoice Date, Due Date, Delivery Date, PO Date, Order Date,
  Value Date, Ship Date. Only the label matching the document's own issuance
  (Invoice Date / Tax Invoice Date / "Date" directly beside the document number, or the
  equivalent issuance-date label for the document's own type — PO Date for a PO, Order Date
  for a sales order, GRN Date for a GRN) qualifies for invoice_date.
- Never use Due Date, Delivery Date, Payment Date, or Expected Ship Date as invoice_date.
- If two dates are both plausibly the issuance date and neither is clearly labeled, leave
  invoice_date empty rather than guessing which.
- Ambiguous numeric date format (e.g. 03/04/2025 could be 3 Apr or 4 Mar): if the document's
  locale/currency/address context strongly indicates one convention (e.g. a UK/AU/IN address
  uses DD/MM/YYYY; a US address uses MM/DD/YYYY) and the day value ≤12 makes it genuinely
  ambiguous, normalize using that locale signal and note the assumption in reason. If no
  locale signal exists AND the value is ambiguous (both day and month ≤12), leave invoice_date
  empty rather than silently picking a convention.
- Unambiguous numeric dates (day value >12, or a spelled-out month) normalize confidently
  regardless of locale.

TOTAL DISAMBIGUATION (which number is "total"):
Apply this priority order; take the first label that appears on the page:
1. "Grand Total" / "Total Amount Due" / "Amount Payable" / "Net Payable" / "Total Due"
2. "Total" (unqualified, when only one such field exists on the page)
3. "Invoice Total" / "Total Invoice Value" / "Total (Incl. Tax)" — only if #1 and #2 absent
Never use as total: "Subtotal", "Taxable Value", "Total Before Tax", "Tax Amount",
"Previous Balance", "Amount Paid", "Balance Brought Forward", line-item amounts, or a
freight/insurance sub-line — these are components, not the header total.
CRITICAL: when the page shows Subtotal / Taxable Value AND a separate Total / Amount Due
(after VAT/GST/tax), you MUST return the after-tax Total — never the Subtotal. Example:
  Subtotal $33.70 · Value-Added Tax $3.38 · Total $37.08 → total must be "37.08", not "33.70".
If the document shows both a "Total Due" (net of a previous balance/partial payment) and an
"Invoice Total" (this invoice's own value), prefer the invoice's own total (this document's
value), not a running/net balance — a running balance is a different concept and should not
be reported as this document's total. Note which was chosen in reason if both are present.
If a printed total is corrected by a clear handwritten annotation next to it (e.g. printed
total struck through, new total written beside it) and the handwritten figure is legible,
use the handwritten corrected value and note "handwritten correction to printed total" in
reason. If the handwritten mark is illegible or ambiguous, use the printed value and note
the presence of an unreadable annotation.
Negative/credit amounts (credit notes, debit adjustments): preserve the sign — output a
leading "-" if the document shows the amount as negative, in parentheses, or explicitly
labeled as a credit/refund amount; do not silently convert to positive.
Multiple totals in different currencies on the same page (e.g. local currency + USD
equivalent shown side by side): choose the total that matches the document's PRIMARY stated
currency (the one used throughout the line items / the one the invoice_no block is under),
not a secondary FX-equivalent reference figure; note the secondary figure existed in reason
if space allows, but do not extract it as total or blend the two.
Amount-in-words present but does not match the printed numeric total: use the numeric total
(the words are a secondary corroboration signal for currency/format only, not the source of
truth for the value); note the mismatch in reason as a data-quality flag.

CURRENCY DISAMBIGUATION:
- Corroborate against: explicit ISO code, prefixed symbol combos (A$, US$, HK$, S$, NZ$,
  RM, ₹ with GST/IGST context, €, £), amount-in-words currency name, or strong jurisdiction
  signal (bank account country, tax registration format, registered address) that is
  consistent with the symbol used.
- The Indian Rupee glyph ₹ (or "INR" / "Rs" with Indian GSTIN / IGST/CGST) → currency "INR".
  Never invent AUD/USD when ₹ is printed on the amounts.
- A bare "$" or "Rs" or "kr" with NO corroborating signal anywhere on the page → empty string.
  Do not default to a "most likely" currency based on tenant's home country alone; the
  document's own printed content must corroborate it.
- If the page shows two currencies for two different amounts (e.g. a bank remittance section
  in local currency below a USD-denominated invoice total), currency must match whichever
  figure was selected as total (see TOTAL DISAMBIGUATION), not the other one.

═══════════════════════════════════════════════
NUMBER & FORMAT NORMALIZATION
═══════════════════════════════════════════════
- Strip thousands separators (comma, period, space, or apostrophe used as a grouping
  separator depending on locale) from total; keep exactly one decimal separator normalized
  to ".". If the locale is genuinely ambiguous (e.g. "1.234" could be one-thousand-two-
  hundred-thirty-four in EU format or 1.234 in US format) and no other page content
  disambiguates it (currency, tax rate context, line-item math), leave total empty rather
  than guess the wrong magnitude — a wrong-magnitude total is worse than a missing one.
- Do not round, do not add/subtract tax, do not recompute from line items — extract the
  printed grand total figure only, normalized in format only, never recalculated in value.
- Reference numbers (invoice_no, po_reference, etc.): copy the printed token as-is, including
  leading zeros, hyphens, and slashes; do not reformat, do not strip leading zeros, do not
  guess an OCR-ambiguous character (0/O, 1/I/l, 5/S, 8/B) — if a character is genuinely
  unclear, either leave the field empty or, if the rest of the token is unambiguous and only
  one character is uncertain, keep the field but drop confidence and note the uncertain
  character's position in reason (do not silently pick one reading).

═══════════════════════════════════════════════
MULTI-PAGE / CONTINUATION PAGE HANDLING
═══════════════════════════════════════════════
- Each page is scored independently on the fields actually visible on THAT page image. Do
  not assume values from a document's typical page-1 header if this page is a continuation
  page (e.g. "Page 2 of 3") that does not repeat the header block.
- If a continuation page repeats the full header (common on SAP-style forms), extract
  normally from what's repeated on this page.
- If a continuation page shows NO header fields at all (pure line-item table, or terms/
  bank-details-only page), leave all identity fields empty EXCEPT canonical_document_type/
  document_heading if a repeated running header/footer title is visible; set confidence low
  and reason "continuation page, no independent header fields visible."
- Do not fabricate invoice_no/total/date on a continuation page by assuming they must match
  page 1 — only report what is actually printed on the page you are looking at.

═══════════════════════════════════════════════
EDGE CASES
═══════════════════════════════════════════════
E1. Page is entirely a letterhead/logo with no body text yet (e.g. a cover page before the
    real invoice) → canonical_document_type empty, document_heading empty unless a real title
    is printed, all other fields empty, low confidence, reason "letterhead only, no document
    content visible."
E2. Page is not a finance document at all (e.g. an internal memo, a photo, a blank fax cover)
    → all fields empty except document_heading if a visible title exists; canonical_document_
    type empty; reason states what the page appears to be.
E3. Document is in a non-English language with no English anywhere → document_heading in the
    original script/language as printed; canonical_document_type in English if the kind is
    confidently inferable from structure (see canonical rules); fields (dates, totals,
    references) still extracted using the same disambiguation rules, translating only labels
    you're confident about (e.g. "Rechnungsnummer" = invoice number label), never the values.
E4. Two invoice numbers appear — one clearly labeled "Invoice No" and one unlabeled
    alphanumeric code elsewhere (e.g. an internal batch/barcode ID) → use only the labeled
    one for invoice_no; the unlabeled code goes in other_reference only if it's clearly a
    business reference (not a barcode/routing artifact); otherwise omit it entirely.
E5. Perspective cannot be determined because the tenant does not appear as either buyer or
    seller on the page (e.g. a customs authority certificate, or a third-party carrier
    document where the tenant is neither party) → perspective "unknown"; counterparty_name
    may still be extracted if a clear non-tenant commercial party is named, otherwise empty.
E6. Tenant appears on BOTH sides (rare intercompany/self-billing scenario, or a document
    where the tenant is both consignor and consignee for an internal transfer) → perspective
    "unknown"; counterparty_name empty; note the conflict in reason.
E7. Stamped "PAID" or a manually written payment amount elsewhere on the page that differs
    from the printed invoice total → does not change total (total is always the document's
    own invoice value per TOTAL DISAMBIGUATION, not a payment record); note the paid stamp
    in reason as a data-quality flag only.
E8. Revision/version markers (Rev A, v2, "Supersedes Invoice X") on the page → extract this
    page's own header values normally; do not attempt to resolve which version is "final" —
    that is a downstream/document-splitting concern, not a field-extraction concern here.
E9. Currency symbol conflicts with an explicit ISO code elsewhere on the page (e.g. a "$"
    total but "Bank Currency: SGD" printed in a remittance box) → prefer the explicit ISO
    code only if it clearly applies to the SAME amount selected as total; if the ISO code
    applies to a different amount (e.g. the bank section's own figure), do not borrow it for
    an unrelated total — leave currency empty if the total's own currency isn't corroborated.
E10. OCR/image quality is very poor across the whole page → still attempt document_heading/
     canonical_document_type if any legible title fragment supports a confident classification
     structurally; otherwise leave both empty; set confidence low; reason states the quality
     issue plainly (e.g. "heavy skew/blur, only fragments legible").
E11. Multiple "Total" style figures stacked without clear differentiating labels (e.g. two
     unlabeled numbers near the bottom, one clearly larger) → do not guess which is the grand
     total based on position or size alone; require a label per TOTAL DISAMBIGUATION; if
     neither is labeled, leave total and currency empty.
E12. A PO number and an SO number both appear on the same page, correctly labeled as each —
     this is valid and expected on some sales-side documents; populate both po_reference and
     so_reference from their own distinct labeled values (this is not the same as the
     "identical values in both fields are wrong" caution above, which is about copying one
     value into both fields — here they are genuinely two different labeled numbers).

═══════════════════════════════════════════════
CONFIDENCE CALIBRATION
═══════════════════════════════════════════════
- 0.9–1.0: all populated fields have unambiguous, clearly labeled printed sources; no
  competing candidates had to be resolved.
- 0.7–0.89: fields are populated but at least one required a disambiguation rule (date
  locale inference, total priority selection among multiple labeled totals, etc.).
- 0.5–0.69: page is noisy/partial, or several fields left empty due to genuine ambiguity.
- <0.5: sparse/garbled page, most fields empty, only document_heading/type (if any) extracted
  with any confidence.
Confidence reflects the extraction as a whole, not any single field.

═══════════════════════════════════════════════
SELF-CHECK BEFORE RETURNING OUTPUT
═══════════════════════════════════════════════
Before emitting JSON, verify:
- Every key from the required list is present, with empty string (not null, not omitted) for
  anything absent or unresolved.
- total contains no currency symbol/code and no thousands separators.
- invoice_no and proforma_invoice_no are not identical unless both were independently labeled.
- po_reference and so_reference are not identical unless both were independently labeled.
- counterparty_name is never equal to the tenant's own legal_name/alias.
- currency is either empty or a valid ISO 4217 code, never a bare symbol.
- reason is one short sentence and actually reflects the disambiguation path taken (which
  tie-break rule fired, or why a field was left empty).
"""


_VISION_HEADER_EXTRACT_DEFAULT = _vision_header_extract_default()


PROMPT_CATALOG: tuple[PromptDefinition, ...] = (
    PromptDefinition(
        key="llm.classify.system",
        label="Classify (text LLM)",
        group="Classify",
        description="System prompt for Azure OpenAI text classification.",
        default_body=_CLASSIFY_SYSTEM_DEFAULT,
        placeholders=("party_rules",),
    ),
    PromptDefinition(
        key="llm.extract.system",
        label="Extract (text / vision structure)",
        group="Extract",
        description="System prompt for field extraction (text LLM and vision extract).",
        default_body=_EXTRACT_SYSTEM_DEFAULT,
        placeholders=("json_keys", "rule_lines", "party_rules", "country"),
    ),
    PromptDefinition(
        key="llm.combined.system",
        label="Combined classify+extract",
        group="Extract",
        description="System prompt when classify and extract run in one LLM call.",
        default_body=_COMBINED_SYSTEM_DEFAULT,
        placeholders=("json_keys", "rule_lines", "party_rules"),
    ),
    PromptDefinition(
        key="llm.extract.sparse_hint",
        label="Sparse OCR extract hint",
        group="Extract",
        description="Appended to extract system prompt when OCR is sparse / image-backed.",
        default_body=_SPARSE_HINT_DEFAULT,
    ),
    PromptDefinition(
        key="llm.gap_fill.system",
        label="Gap-fill header",
        group="Extract",
        description="Header for second-pass gap-fill extraction (dynamic keys appended in code).",
        default_body=_GAP_FILL_HEADER_DEFAULT,
    ),
    PromptDefinition(
        key="llm.currency.system",
        label="Currency Detection Agent",
        group="Extract",
        description=(
            "Dedicated currency detection: ISO code from corroborating evidence only; "
            "prefer UNCERTAIN over guessing ambiguous symbols."
        ),
        default_body=CURRENCY_DETECT_SYSTEM_DEFAULT,
    ),
    PromptDefinition(
        key="pdf.segment.system",
        label="PDF page segmentation",
        group="Segment",
        description="System prompt for splitting multi-document PDF bundles (v2 hardened).",
        default_body=_SEGMENT_SYSTEM_DEFAULT,
    ),
    PromptDefinition(
        key="vision.gemini.classify.system",
        label="Gemini classify",
        group="Vision",
        description="Gemini vision document-type classification.",
        default_body=_VISION_CLASSIFY_DEFAULT,
        placeholders=("party_rules",),
    ),
    PromptDefinition(
        key="vision.gemini.read.system",
        label="Gemini OCR read",
        group="Vision",
        description="Gemini vision OCR / text excerpt read.",
        default_body=_VISION_READ_DEFAULT,
    ),
    PromptDefinition(
        key="vision.foundry.classify.system",
        label="Foundry classify",
        group="Vision",
        description="Azure Foundry vision document-type classification.",
        default_body=_VISION_CLASSIFY_DEFAULT,
        placeholders=("party_rules",),
    ),
    PromptDefinition(
        key="vision.foundry.read.system",
        label="Foundry OCR read",
        group="Vision",
        description="Azure Foundry vision OCR / text excerpt read.",
        default_body=_VISION_READ_DEFAULT,
    ),
    PromptDefinition(
        key="vision.understand.system",
        label="Vision understand gate",
        group="Vision",
        description="Lightweight yes/no gate: can vision understand this document?",
        default_body=_VISION_UNDERSTAND_DEFAULT,
    ),
    PromptDefinition(
        key="vision.header_extract.system",
        label="Vision header extract",
        group="Vision",
        description=(
            "Extract printed title, counterparty, and linking references from page images "
            "(hardened disambiguation + self-check)."
        ),
        default_body=_VISION_HEADER_EXTRACT_DEFAULT,
    ),
    PromptDefinition(
        key="llm.party_rules",
        label="Party field rules",
        group="Fragments",
        description="Seller/buyer party rules fragment injected into classify/extract prompts.",
        default_body=_PARTY_RULES_DEFAULT,
        placeholders=("tax_id_label", "llm_tax_id_examples"),
    ),
)

PROMPT_BY_KEY: dict[str, PromptDefinition] = {p.key: p for p in PROMPT_CATALOG}


def get_prompt_definition(key: str) -> PromptDefinition | None:
    return PROMPT_BY_KEY.get(key)


def catalog_default_body(key: str) -> str | None:
    defn = PROMPT_BY_KEY.get(key)
    return defn.default_body if defn else None
