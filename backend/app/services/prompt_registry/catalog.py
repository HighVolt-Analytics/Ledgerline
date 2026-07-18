"""Code-sourced prompt catalog (seed + emergency fallback for Developer Port)."""

from __future__ import annotations

from dataclasses import dataclass


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
ROLE — Document Splitting Agent (page-range mode)
You split a multi-page PDF containing many concatenated business documents into
logical SINGLE documents for finance processing.
Input: page text excerpts (0-indexed) with pages[i].window =
{previous, current, upcoming, upcoming_2}.
Output: JSON only with keys segments, reasoning.

You MUST NOT fabricate content. You MUST NOT invent reference numbers, dates,
or metadata. When uncertain, do not guess a merge — KEEP/extend only for
same-type continuation, or emit heading_kind="" with lower confidence.
This pipeline emits CONTIGUOUS page ranges only (no non-contiguous regrouping,
no qpdf folders/manifests). Every NON-BLANK source page appears in exactly one
segment. Blank pages are OMITTED (skipped) — never attached to a neighbor.

═══════════════════════════════════════════════
HARD RULES (task failure if violated)
═══════════════════════════════════════════════
R1. Cover every NON-BLANK page exactly once. OMIT blank pages from all segments
    (see BLANK). Do not invent coverage for blank indices.
R2. NEVER split a logical document across two segments.
R3. NEVER merge two logical documents into one segment.
R4. Preserve source page order within each segment (ascending indices). Do not
    reorder pages (pipeline is contiguous source order only).
R5. NEVER invent reference numbers, dates, or metadata. If unreadable, leave
    identity empty and still split on type/title when the type change is clear.
R6. If type confidence < ~0.75: still cover the non-blank page. Prefer KEEP with
    neighbors when continuation is likely; otherwise start a segment with
    heading_kind="" and lower confidence.
R7. Blank pages only if visually blank (no stamps, faint text, handwritten marks).
    A page with ANY mark is NOT blank — classify it or keep as continuation.
R8. PAGE-OF-N (all document types): "Page 1 of N" … "Page N of N" with the same
    type family and same primary reference MUST be ONE segment. Never label a
    mid-run page (Page 2..N) as a different type (e.g. never call invoice page 2
    a transport_doc). Applies to invoice, packing_list, transport_doc, grn/PoD,
    PO, COO, customs_permit, credit_note, etc.

═══════════════════════════════════════════════
WHAT "ONE DOCUMENT" MEANS
═══════════════════════════════════════════════
One segment = one standalone commercial or supporting instrument.
A pack may contain one multi-page doc, many same-type docs, or a mixed shipment set
(invoice + packing list + AWB + COO + permit + GRN/POD + …).
Your job is NOT one segment per page.
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

═══════════════════════════════════════════════
CORE METHOD — WINDOW … i-1 | i | i+1 | i+2 …
═══════════════════════════════════════════════
Use pages[i].window for every page. Never decide from the current page alone.
Page 0: SKIP this step (no previous) for look-back; use look-ahead only.

DECISION ORDER (mandatory for every page i):
(1) LOOK BACK — does a NEW document start at i?
    Compare previous vs current (type + primary identity).
    Blank current → SKIP (omit from segments; never start; never attach).
    "Page 2..N of N" (any type) → NEVER start; KEEP with the open run.
    Different TYPE vs previous → START NEW (hard). Shared invoice/PO numbers do NOT
    merge different types (Invoice ≠ Packing List ≠ AWB ≠ GRN/POD ≠ PO ≠ Credit Note).
    Same type + different primary reference → START NEW.
    Same type + same reference → KEEP.
(2) LOOK AHEAD — does this page OPEN / CONTINUE a multi-page single document?
    Upcoming / upcoming_2 same type + same primary reference, or "Page 2 of N" /
    continued lines / totals / tax / bank / T&Cs / repeated form header → EXTEND.
    A repeated "INVOICE"/"PACKING LIST" header on page 2+ is STILL continuation when
    Page X of Y or the same primary number continues.
(3) LOOK AHEAD FOR TYPE CHANGE — when to CLOSE the current run:
    If upcoming (next non-blank) is a different type → end current segment before
    that page; start the next segment there. Never glue invoice page N to the
    following packing list / AWB / PoD.

Long packs = a SEQUENCE OF RUNS (start from (1) + extent from (2)/(3)).

═══════════════════════════════════════════════
PHASE 2 — PER-PAGE CLASSIFICATION (mental checklist; stop at first strong match)
═══════════════════════════════════════════════
For each page, mentally extract (do not dump into output JSON — use for grouping):
type/header evidence, primary_reference, linking_ids (PO/BOL/freight/tracking),
page_of_marker ("Page X of Y"), parties, document_date, monetary_total presence,
handwritten/stamped marks, continuation_hints, quality issues.

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

H3. Still unknown → heading_kind="" (do not invent a type); still assign a
    correct page range (pipeline analogue of 99_unclassified).

Ambiguous invoice-styled packing list (E15): prefer explicit header; else
monetary total present → invoice family; absent → packing_list. Note in reasoning.

Multi-language (E9): map FACTURA / RECHNUNG / 请款单 → invoice family, etc.

Rotation: classify from readable title text even if layout is rotated; do not drop.

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

G1. STRONG — same document_type + same primary_reference → KEEP while contiguous.
G2. PAGE-OF-N — "Page 2 of 3" / "Page : 2 of 3" (any document type) with shared
    type family and/or primary reference → KEEP as one segment through Page N of N.
    Mis-labeling mid pages as transport_doc / other types is FORBIDDEN.
G3. CONTINUATION — no independent header, looks like continued table/lines,
    immediately after type T, with ≥1 shared linking id OR clear page-of-N → KEEP with T.
    If no shared id and no page-of-N and type unclear → do not invent a merge;
    prefer split only when a new primary title appears; else KEEP with low confidence
    (and note the uncertainty in reasoning — human-review analogue).
G4. FALLBACK — lone page with clear type + reference → its own one-page segment.

Conflict resolution:
- Two "Page 1 of 2" with same reference → do not guess; prefer source order; note reasoning.
- Same type + same reference but different dates/instruments → SEPARATE segments.
- Partially obscured reference → still split on type titles; leave identity empty.

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
E9. Multi-language headers — structural + translated type mapping.
E10. Sparse/garbled OCR / heavy skew — still SPLIT on strongest readable type title vs
    window; do not collapse a mixed pack into one segment "to be safe".
E11. Signature-only back page → continuation of prior document.
E12. Cover / tab / index → own segment (document_label Cover/Index; heading_kind="" ok).
E13. Email printouts → own segment (document_label EmailPrintout).
E14. Contract + exhibits — keep with contract UNLESS independent titles/refs (then split).
E15. Invoice vs packing list ambiguity — see H2/E15 above.
E16. OCR-ambiguous ref chars (0/O, 1/I, 5/S, 8/B) — cross-check same-type neighbors;
    if inconsistent, do not invent; still split on type.
E17. Very long packs — walk as a sequence of runs; never drop trailing pages; never merge
    different types to reduce segment count.
E18. Encrypted/password PDF is handled upstream — if text is empty for all pages, emit
    one low-confidence coverage segment rather than inventing splits.

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

reasoning: 1–4 short sentences on boundaries, which G1–G4 fired, and any E*/F* notes
(e.g. "p0–2 invoice INV-1 (Page 1–3 of 3); blank p3 omitted; p4–5 packing list").

═══════════════════════════════════════════════
HARD COVERAGE RULES
═══════════════════════════════════════════════
1. Contiguous, non-overlapping, cover every NON-BLANK page exactly once. Omit blanks.
2. Indices 0-based in [0, page_count-1]; start_page <= end_page; sort by start_page.
3. Never invent or duplicate pages; never omit a non-blank page index.
4. Same-type multi-page continuation / Page X of Y with same primary number → one segment
   (all document types).
5. Different primary type titles on successive pages → different segments.
6. Supporting docs (packing list, COO, AWB/BL, GRN/POD, permit, credit note, remittance,
   quote, proforma, timesheet, contract) MUST NOT merge into an invoice/PO solely because
   they cite the same reference number.
7. Never emit a blank-only / empty-only segment. OMIT blank pages from ranges.

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
You extract header identity fields from finance document page images for accounts payable/receivable.
Return JSON only with keys:
{keys}.
Never omit keys — use empty string when a value is absent or unclear.

═══════════════════════════════════════════════
DOCUMENT TITLE FIELDS
═══════════════════════════════════════════════
- document_heading: copy the printed document title EXACTLY as shown on the page
  (spelling, casing, punctuation as printed). Do not invent a catalogue DT-xx code.
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
DATE, TOTAL, CURRENCY
═══════════════════════════════════════════════
- invoice_date: document date (Invoice Date / Date / Tax Invoice Date). Prefer ISO YYYY-MM-DD
  when you can normalize confidently; otherwise empty string — never invent a date.
- total: grand total / amount due / total payable as a plain number string (e.g. "1234.56").
  Do not include currency symbols or codes in total. Empty string if unclear.
- currency: ISO 4217 code when clear (AUD, USD, EUR, …). If only a symbol is shown and the
  code is ambiguous (e.g. "$"), leave currency empty rather than guessing. Never convert amounts.
- Do not extract line items, subtotal, or tax breakdowns in this step.
- confidence is 0.0-1.0 for the overall header extraction.
- reason is one short sentence.
- Do not map to DT-xx catalogue codes."""


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
        key="pdf.segment.system",
        label="PDF page segmentation",
        group="Segment",
        description="System prompt for splitting multi-document PDF bundles.",
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
        description="Extract printed title, counterparty, and linking references from page images.",
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
