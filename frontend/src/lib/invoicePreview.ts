import type { Invoice, InvoiceDetails, LineItem } from "@/api/types";
import { documentDisplayRef, money } from "@/lib/format";
import { extractionFieldLabel } from "@/lib/documentExtractionFields";
import { counterpartyKind, counterpartyName } from "@/lib/invoice";
import { COUNTRIES } from "@/lib/settingsData";
import { DEFAULT_TENANT_LOCALE } from "@/lib/tenantTime";

export type ContentReference = {
  key: string;
  label: string;
  value: string;
};

export type PreviewLineItem = LineItem & {
  displayQty: string | null;
  displayUnitPrice: string | null;
  displayAmount: string | null;
};

export type LineItemColumnVisibility = {
  showQty: boolean;
  showUnitPrice: boolean;
  showAmount: boolean;
};

export type PartyPreviewBlock = {
  key: "bill_from" | "bill_to";
  label: string;
  name: string | null;
  taxId: string | null;
  address: string | null;
};

export type DocumentContentProfile = {
  counterparty: string | null;
  abn: string | null;
  heading: string | null;
  invoiceNo: string | null;
  docRef: string;
  dates: { issued?: string; due?: string };
  /** @deprecated Use referenceDetails — kept for backward compatibility */
  references: ContentReference[];
  parties: PartyPreviewBlock[];
  referenceDetails: ContentReference[];
  lineItems: PreviewLineItem[];
  lineItemColumns: LineItemColumnVisibility;
  totals: { subtotal?: string; tax?: string; total?: string };
  bankDetails: string | null;
  textExcerpt: string | null;
  footer: string;
  emailSender: string | null;
};

/** Keep in sync with backend HEADER_DEDUP_EXTRACTED_FIELD_KEYS. */
const HEADER_DEDUP_EXTRACTED_FIELD_KEYS = [
  "seller_name",
  "buyer_name",
  "seller_tax_id",
  "buyer_tax_id",
  "seller_abn",
  "buyer_abn",
  "billing_address",
  "document_heading",
  "so_reference",
  "cost_centre",
  "consignment_ref",
  "permit_no",
  "bank_name",
  "bank_bsb",
  "bank_account",
  "customer",
  "delivery_date",
] as const;

/** Keep in sync with backend OPTIONAL_CURRENCY_MONEY_PREFIX. */
const OPTIONAL_CURRENCY_MONEY_PREFIX =
  "(?:[$€£¥]|(?:AUD|USD|SGD|NZD|GBP|EUR|CAD|INR|MYR|THB|HKD|JPY|CNY)\\s*)?";

const PROFILE_SCALAR_KEYS = new Set([
  "vendor",
  "abn",
  "invoice_no",
  "invoice_date",
  "due_date",
  "po_reference",
  "so_reference",
  "cost_centre",
  "subtotal",
  "gst",
  "total",
  "billing_address",
  "email_subject",
  "account_code",
  "account_name",
  "bank_bsb",
  "bank_account",
  "document_heading",
  "document_text",
  "line_items",
  "attachment_name",
  "bank_details",
]);

/** Internal routing metadata — not shown in OCR summary references. */
const INTERNAL_EXTRACTED_KEYS = new Set([
  "perspective",
  "llm_perspective",
  "customer",
]);

/** Party keys rendered via buildPartyBlocks — skip generic extracted_fields loop. */
const PARTY_REFERENCE_KEYS = new Set([
  "seller_name",
  "seller_tax_id",
  "seller_address",
  "seller_abn",
  "buyer_name",
  "buyer_tax_id",
  "buyer_address",
  "buyer_abn",
]);

function partyField(inv: InvoiceDetails, key: string): string | null {
  return invoiceScalarRaw(inv, key);
}

function valuesEqual(a: string | null | undefined, b: string | null | undefined): boolean {
  if (!a || !b) return false;
  return a.trim().toLowerCase() === b.trim().toLowerCase();
}

function normalizeAddressKey(value: string): string {
  return value.trim().toLowerCase().replace(/\s+/g, " ");
}

function addressMatches(a: string | null | undefined, b: string | null | undefined): boolean {
  if (!a?.trim() || !b?.trim()) return false;
  const left = normalizeAddressKey(a);
  const right = normalizeAddressKey(b);
  return left === right || left.includes(right) || right.includes(left);
}

function buildPartyBlock(
  key: "bill_from" | "bill_to",
  label: string,
  name: string | null,
  taxId: string | null,
  address: string | null,
  headerCounterparty: string
): PartyPreviewBlock | null {
  let displayName = name?.trim() || null;
  if (displayName && valuesEqual(displayName, headerCounterparty)) {
    displayName = null;
  }
  const displayTax = taxId?.trim() || null;
  const displayAddress = address?.trim() || null;
  if (!displayName && !displayTax && !displayAddress) return null;
  return {
    key,
    label,
    name: displayName,
    taxId: displayTax,
    address: displayAddress,
  };
}

export function buildPartyBlocks(
  inv: InvoiceDetails,
  absentFields: string[],
  extractionFieldKeys: string[],
  summaryMode = false
): PartyPreviewBlock[] {
  const headerCounterparty = counterpartyName(inv);
  const kind = counterpartyKind(inv);

  const sellerName = partyField(inv, "seller_name");
  const sellerTax = partyField(inv, "seller_tax_id") ?? partyField(inv, "seller_abn");
  const sellerAddress = partyField(inv, "seller_address");
  const buyerName = partyField(inv, "buyer_name");
  const buyerTax = partyField(inv, "buyer_tax_id") ?? partyField(inv, "buyer_abn");
  const buyerAddress =
    partyField(inv, "buyer_address") ??
    invoiceScalarRaw(inv, "billing_address") ??
    inv.billing_address ??
    null;

  const billFrom = buildPartyBlock(
    "bill_from",
    "Bill from",
    sellerName,
    sellerTax,
    sellerAddress,
    headerCounterparty
  );
  const billTo = buildPartyBlock(
    "bill_to",
    "Bill to",
    buyerName,
    buyerTax,
    buyerAddress,
    headerCounterparty
  );

  const blocks: PartyPreviewBlock[] = [];
  const includeBlock = (block: PartyPreviewBlock | null) => {
    if (!block) return;
    if (!shouldIncludeInSummary(block.key, extractionFieldKeys, absentFields, true, summaryMode)) {
      return;
    }
    blocks.push(block);
  };

  if (kind === "customer") {
    includeBlock(billTo);
    if (sellerName && !valuesEqual(sellerName, headerCounterparty)) {
      includeBlock(billFrom);
    }
  } else {
    includeBlock(billFrom);
    if (buyerName && !valuesEqual(buyerName, headerCounterparty)) {
      includeBlock(billTo);
    }
  }

  return blocks;
}

/** @deprecated Use buildPartyBlocks */
export function buildPartyReferences(
  inv: InvoiceDetails,
  absentFields: string[],
  extractionFieldKeys: string[]
): ContentReference[] {
  return buildPartyBlocks(inv, absentFields, extractionFieldKeys).map((block) => ({
    key: `${block.key}_party`,
    label: block.label,
    value: [block.name, block.taxId, block.address].filter(Boolean).join(" · "),
  }));
}

function shouldOmitBillingAddress(
  billingAddress: string | null,
  parties: PartyPreviewBlock[],
  extracted: Record<string, string>
): boolean {
  if (!billingAddress?.trim()) return true;
  const buyerBlock = parties.find((p) => p.key === "bill_to");
  if (buyerBlock?.address && addressMatches(billingAddress, buyerBlock.address)) {
    return true;
  }
  const buyerAddr = extracted.buyer_address?.trim();
  if (buyerAddr && addressMatches(billingAddress, buyerAddr)) return true;
  return false;
}

function headerAbnVisible(
  abn: string | null,
  parties: PartyPreviewBlock[]
): string | null {
  if (!abn?.trim()) return null;
  if (parties.some((p) => p.taxId && valuesEqual(abn, p.taxId))) return null;
  return abn;
}

function shouldSkipExtractedReference(
  token: string,
  value: string,
  headerCounterparty: string,
  extracted: Record<string, string>
): boolean {
  if (INTERNAL_EXTRACTED_KEYS.has(token)) return true;
  if (PARTY_REFERENCE_KEYS.has(token)) return true;
  if (valuesEqual(value, headerCounterparty)) return true;
  if (token === "customer" && valuesEqual(value, extracted.buyer_name)) return true;
  return false;
}

/** Reserved for ordering configured fields in the summary meta row. */
const SUMMARY_CORE_KEYS = new Set([
  "vendor",
  "invoice_no",
  "invoice_date",
  "due_date",
  "line_items",
  "subtotal",
  "gst",
  "total",
  "bank_details",
  "document_heading",
]);

export function summaryFieldOrder(key: string, extractionFieldKeys: string[]): number {
  if (!extractionFieldKeys.length) return 0;
  if (SUMMARY_CORE_KEYS.has(key)) return extractionFieldKeys.indexOf(key);
  const index = extractionFieldKeys.indexOf(key);
  return index === -1 ? 999 : index;
}

/**
 * Both content-first and user-configured extraction fields:
 * - Any extracted value is shown (content wins)
 * - User-defined fields never render empty (not mandatory)
 * - absentFields still suppresses structurally wrong values
 */
export function shouldIncludeInSummary(
  key: string,
  _extractionFieldKeys: string[],
  absentFields: string[],
  hasValue: boolean,
  summaryMode = false
): boolean {
  if (!hasValue) return false;
  if (summaryMode) return true;
  if (shouldSuppressField(key, absentFields)) return false;
  return true;
}

/** Whether document_text OCR excerpt should appear alongside structured summary. */
export function shouldShowDocumentTextExcerpt(
  extractionFieldKeys: string[],
  absentFields: string[],
  hasFinancialBody: boolean,
  hasDocumentText: boolean,
  summaryMode = false
): boolean {
  if (!hasDocumentText) return false;
  if (summaryMode) {
    return !hasFinancialBody;
  }
  if (shouldSuppressField("document_text", absentFields)) return false;
  if (!hasFinancialBody) return true;
  return extractionFieldKeys.includes("document_text");
}

export function shouldSuppressField(key: string, absentFields: string[]): boolean {
  return absentFields.includes(key);
}

export function invoiceScalarRaw(inv: InvoiceDetails, key: string): string | null {
  const record = inv as unknown as Record<string, unknown>;
  const extracted = inv.extracted_fields;
  if (extracted && typeof extracted === "object") {
    const custom = extracted[key];
    if (custom != null && String(custom).trim()) {
      return String(custom).trim();
    }
  }
  const val = record[key];
  if (val == null) return null;
  const text = String(val).trim();
  return text || null;
}

export function headingFromDocumentText(text: string | null | undefined): string | null {
  if (!text) return null;
  for (const line of text.split(/\r?\n/)) {
    const token = line.trim();
    if (token.length >= 4) return token.slice(0, 120);
  }
  return null;
}

export function excerptDocumentText(text: string | null | undefined, max = 320): string | null {
  const body = text?.trim();
  if (!body) return null;
  if (body.length <= max) return body;
  return `${body.slice(0, max)}…`;
}

function scalarIfPresent(
  inv: InvoiceDetails,
  key: string,
  absentFields: string[],
  extractionFieldKeys: string[],
  summaryMode = false
): string | null {
  const raw = invoiceScalarRaw(inv, key);
  if (!shouldIncludeInSummary(key, extractionFieldKeys, absentFields, Boolean(raw), summaryMode)) {
    return null;
  }
  return raw;
}

function referenceLabel(key: string): string {
  return extractionFieldLabel(key);
}

function pushReference(
  refs: ContentReference[],
  key: string,
  value: string | null | undefined,
  absentFields: string[],
  extractionFieldKeys: string[],
  summaryMode = false
): void {
  const text = value?.trim();
  if (!text) return;
  if (!shouldIncludeInSummary(key, extractionFieldKeys, absentFields, true, summaryMode)) return;
  refs.push({ key, label: referenceLabel(key), value: text });
}

function parseNumeric(value: string | null | undefined): number | null {
  if (value == null || value === "") return null;
  const n = parseFloat(String(value).replace(/,/g, ""));
  return Number.isNaN(n) ? null : n;
}

function formatNumericForDisplay(value: number): string {
  const rounded = Math.round(value * 100) / 100;
  return Number.isInteger(rounded) ? String(rounded) : rounded.toFixed(2);
}

function hasDisplayValue(value: string | null | undefined): boolean {
  return value != null && String(value).trim() !== "";
}

export function isSummaryLineDescription(description: string | null | undefined): boolean {
  const text = normalizeDescriptionKey(description);
  if (!text) return false;
  if (/^sub\s*total\s*:?\s*$/.test(text)) return true;
  if (/^(?:grand\s+)?total\s*:?\s*$/.test(text)) return true;
  if (/^(?:gst|tax)\s*:?\s*$/.test(text)) return true;
  if (/\b(?:total\s+no\.?\s+of\s+pallet|no\.?\s+of\s+pallet|pallet\s*:)\b/.test(text)) {
    return true;
  }
  if (/\b(?:total\s*due|amount\s*due)\b/.test(text)) return true;
  if (/^abn\s*:?\s*\d/.test(text)) return true;
  if (
    /^(?:(?:grand\s+)?(?:sub\s*)?total(?:\s+(?:gst|tax|excl(?:uding)?\s*gst|incl(?:uding)?\s*gst))?|total\s+(?:gst|tax|amount|due)|amount\s*(?:due|payable)|balance\s*(?:due|owing)|net\s*(?:payable|amount|total)|(?:gst|tax)\s*(?:amount|total)?)\b(?:\s*:?\s*\$?\s*[\d,]+\.?\d*)?\s*$/.test(
      text
    )
  ) {
    return true;
  }
  if (
    /\b(?:bank\s*(?:details|name|account)|account\s*name|bsb|swift|iban|remittance\s*(?:advice|to)|please\s*remit|payment\s*to)\b/.test(
      text
    ) &&
    text.length <= 120
  ) {
    return true;
  }
  // Label-only or Label: value header rows (keep in sync with backend skip patterns)
  if (
    /^(?:customer|ship(?:ped)?(?:\s*(?:to|date|qty|ped))?|delivery\s*date|invoice\s*(?:no|number|#|date)|po\s*(?:no|number|reference)?|order\s*(?:no|number)?|so\s*(?:no|number|reference)?|bill(?:ed)?\s*to|ship\s*to|vendor|supplier|abn|gstin|bsb|account\s*(?:no|number|name)?|payment\s*terms|due\s*date|date\s*paid|receipt\s*(?:no|number)?|consignment|permit|cost\s*cent(?:er|re)|phone|tel(?:ephone)?(?:\s*no\.?)?|mobile|email|fax|address|attn|attention|bank(?:\s*name)?|swift|iban|remittance)\s*:?\s*$/.test(
      text
    )
  ) {
    return true;
  }
  if (
    /^(?:customer|ship(?:ped)?(?:\s*(?:to|date|qty|ped))?|delivery\s*date|invoice\s*(?:no|number|#|date)|po\s*(?:no|number|reference)?|order\s*(?:no|number)?|so\s*(?:no|number|reference)?|bill(?:ed)?\s*to|ship\s*to|vendor|supplier|abn|gstin|bsb|account\s*(?:no|number|name)?|payment\s*terms|due\s*date|date\s*paid|receipt\s*(?:no|number)?|consignment|permit|cost\s*cent(?:er|re)|phone|tel(?:ephone)?(?:\s*no\.?)?|mobile|email|fax|address|attn|attention|bank(?:\s*name)?)\s*:\s+\S/.test(
      text
    )
  ) {
    return true;
  }
  if (
    /^(?:invoice\s*(?:no|number|#|date)|po\s*(?:no|number|reference)?|so\s*(?:no|number|reference)?|order\s*(?:no|number)?|ship\s*to|bill(?:ed)?\s*to|due\s*date|delivery\s*date|ship(?:ped)?\s*date|payment\s*terms|abn|gstin|bsb|account\s*(?:no|number|name))\s+(?:-+\s+)?\S/.test(
      text
    )
  ) {
    return true;
  }
  if (/^(?:tel(?:ephone)?|phone|mobile|fax)\s*(?:no\.?|number|#)?\s*:?\s*\+?\d/i.test(text)) {
    return true;
  }
  if (
    /^(?:description|item(?:\s*description)?|product|qty|quantity|unit\s*price|amount|rate|uom|sku|hs\s*code|country\s*of\s*origin|net\s*weight|gross\s*weight)\s*:?\s*$/.test(
      text
    )
  ) {
    return true;
  }
  if (
    /^(?:description|item|product)\b.+\b(?:qty|quantity|amount|unit\s*price|rate)\b/.test(text) &&
    text.split(/\s+/).length <= 10
  ) {
    return true;
  }
  if (text.endsWith(":") && text.length <= 40) return true;
  return false;
}

/** Keep in sync with backend is_noise_line_item_row. */
export function isNoiseLineItemRow(
  description: string | null | undefined,
  qty?: string | number | null
): boolean {
  const desc = String(description ?? "").trim();
  if (!desc) return true;
  if (/\b(?:DOCUMENTARY\s+CREDIT|CERTIFICATE|REFERENCE\s+NO|CONTRACT\s+NO|IRC\s+NO|TIN\b|BIN\s+NO)\b/i.test(desc)) {
    return true;
  }
  if (
    /^(?:page\s*\d+(?:\s*of(?:\s*\d+)?)?|continued(?:\s+on\s+next\s+page)?|end\s+of\s+(?:document|invoice))\s*$/i.test(
      desc
    )
  ) {
    return true;
  }
  if (
    /^(?:\$|€|£)?\s*[\d,]+\.?\d*\s*(?:[A-Z]{3})?\s*due\b|\b(?:amount|balance|total)\s+due\b|\bdue\s+(?:on\s+)?(?:\d{1,2}[/\-.]\d{1,2}|jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)/i.test(
      desc
    )
  ) {
    return true;
  }
  if (
    /^(?:\d{1,2}[/\-.]\d{1,2}[/\-.]\d{2,4}|\d{4}[/\-.]\d{1,2}[/\-.]\d{1,2}|\d{1,2}\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+\d{2,4})$/i.test(
      desc
    )
  ) {
    return true;
  }
  if (
    /^(?:abn|gstin|acn|tfn)\s*:?\s*[\d\s]{8,}|\b(?:bank\s*(?:details|name|account)|account\s*name|bsb|swift|iban|remittance|please\s*(?:pay|remit)|payment\s*instructions|tel(?:ephone)?|phone|mobile|fax|email|www\.|http)\b/i.test(
      desc
    ) &&
    desc.split(/\s+/).length <= 14
  ) {
    return true;
  }
  if (
    /\b(?:street|st\.?|road|rd\.?|avenue|ave\.?|drive|dr\.?|lane|ln\.?|boulevard|blvd\.?|straat|gracht|weg|laan|plein|allee|suite|floor|building|unit\s+\d+|henderson|singapore|postal|zip\s*code|australia|nsw|vic|qld|sa|wa|act|tas|nz|new\s+zealand)\b/i.test(
      desc
    ) &&
    (/\b\d{4,6}\b/.test(desc) || desc.split(/\s+/).length <= 8)
  ) {
    return true;
  }
  if (
    /^(?:[A-Za-z]+(?:straat|gracht|weg|laan|plein|allee|avenue|street|road|drive|lane))(?:\s+\d+[A-Za-z]?)?$/i.test(
      desc
    )
  ) {
    return true;
  }
  const qtyNum = qty == null || qty === "" ? null : Number(String(qty).replace(/,/g, ""));
  if (qtyNum != null && Number.isFinite(qtyNum) && qtyNum > 1000 && desc.split(/\s+/).length <= 3) {
    if (!/\b(?:cpu|chip|part|widget|item|unit|kg|pcs)\b/i.test(desc)) return true;
  }
  return false;
}

function duplicatesHeaderLineDescription(
  description: string | null | undefined,
  headerValues: Set<string>
): boolean {
  const normalized = normalizeDescriptionKey(description);
  if (!normalized || normalized.length < 3) return false;
  if (headerValues.has(normalized)) return true;
  for (const value of headerValues) {
    if (value.length >= 8 && (normalized.includes(value) || value.includes(normalized))) {
      return true;
    }
  }
  return false;
}

function buildLineItemHeaderValues(inv: InvoiceDetails): Set<string> {
  const values = new Set<string>();
  const add = (raw: string | null | undefined) => {
    const token = normalizeDescriptionKey(raw);
    if (token.length >= 3) values.add(token);
  };
  add(inv.vendor);
  add(inv.invoice_no);
  add(inv.po_reference);
  add(inv.so_reference);
  add(inv.cost_centre);
  const extracted = inv.extracted_fields ?? {};
  for (const key of HEADER_DEDUP_EXTRACTED_FIELD_KEYS) {
    add(extracted[key]);
  }
  return values;
}

export function filterLineItemsForPreview(
  items: LineItem[],
  headerValues?: Set<string>
): LineItem[] {
  const filtered = items.filter((line) => {
    if (isSummaryLineDescription(line.description)) return false;
    if (isNoiseLineItemRow(line.description, line.qty)) return false;
    if (headerValues && duplicatesHeaderLineDescription(line.description, headerValues)) {
      return false;
    }
    return true;
  });
  return dedupeNearDuplicateLineItems(filtered);
}

function lineDescriptionKey(description: string | null | undefined): string {
  let text = normalizeDescriptionKey(description);
  const pipe = text.indexOf(" | ");
  if (pipe > 0) text = text.slice(0, pipe).trim();
  return text.replace(/[^\w\s]/g, " ").replace(/\s+/g, " ").trim();
}

function lineItemsNearDuplicate(left: LineItem, right: LineItem): boolean {
  const leftKey = lineDescriptionKey(left.description);
  const rightKey = lineDescriptionKey(right.description);
  if (!leftKey || !rightKey) return false;
  if (leftKey === rightKey) return true;
  if (leftKey.startsWith(rightKey) || rightKey.startsWith(leftKey)) return true;
  const leftAmount = parseNumeric(left.amount);
  const rightAmount = parseNumeric(right.amount);
  if (leftAmount != null && rightAmount != null && amountsRoughlyEqual(leftAmount, rightAmount)) {
    const stem = Math.min(leftKey.length, rightKey.length, 24);
    if (
      stem >= 8 &&
      (leftKey.startsWith(rightKey.slice(0, stem)) || rightKey.startsWith(leftKey.slice(0, stem)))
    ) {
      return true;
    }
  }
  return false;
}

function lineItemRichness(line: LineItem): number {
  let score = (line.description ?? "").trim().length;
  if (hasDisplayValue(line.qty)) score += 10;
  if (hasDisplayValue(line.unit_price)) score += 10;
  if (hasDisplayValue(line.amount)) score += 10;
  return score;
}

/** Collapse duplicate / near-duplicate product rows (DI + layout merge bleed). */
export function dedupeNearDuplicateLineItems(items: LineItem[]): LineItem[] {
  if (items.length < 2) return items;
  const keep = items.map(() => true);
  for (let i = 0; i < items.length; i += 1) {
    if (!keep[i]) continue;
    for (let j = i + 1; j < items.length; j += 1) {
      if (!keep[j]) continue;
      if (!lineItemsNearDuplicate(items[i], items[j])) continue;
      if (lineItemRichness(items[i]) >= lineItemRichness(items[j])) {
        keep[j] = false;
      } else {
        keep[i] = false;
        break;
      }
    }
  }
  return items.filter((_, index) => keep[index]);
}

function amountsRoughlyEqual(a: number, b: number): boolean {
  const scale = Math.max(Math.abs(a), Math.abs(b), 1);
  return Math.abs(a - b) / scale < 0.02;
}

/** Drop invoice-level totals and inconsistent qty/unit/amount combinations. */
export function sanitizeLineItemValues(
  items: LineItem[],
  invoiceTotal: string | null | undefined
): LineItem[] {
  const headerTotal = parseNumeric(invoiceTotal);

  return items.map((line) => {
    const qty = parseNumeric(line.qty);
    const unitPrice = parseNumeric(line.unit_price);
    let amount = parseNumeric(line.amount);

    if (
      amount != null &&
      headerTotal != null &&
      amountsRoughlyEqual(amount, headerTotal) &&
      (qty == null || qty > 1)
    ) {
      amount = null;
    }

    if (qty != null && unitPrice != null && amount != null && qty > 0) {
      const expected = qty * unitPrice;
      if (!amountsRoughlyEqual(expected, amount)) {
        amount = null;
      }
    }

    return {
      ...line,
      unit_price: unitPrice != null ? formatNumericForDisplay(unitPrice) : line.unit_price,
      amount: amount != null ? formatNumericForDisplay(amount) : null,
    };
  });
}

function parseRowFromTextLine(description: string, line: string): ParsedTextLineRow | null {
  const needle = description.trim();
  if (!needle || !line.toLowerCase().includes(needle.toLowerCase())) return null;

  const parsedRows = parseLineItemRowsFromDocumentText(line);
  const descKey = normalizeDescriptionKey(needle);
  const direct = descKey ? parsedRows.get(descKey) : null;
  if (direct) return direct;

  for (const row of parsedRows.values()) {
    if (
      row.descKey.startsWith(descKey.slice(0, Math.min(descKey.length, 24))) ||
      descKey.startsWith(row.descKey.slice(0, Math.min(row.descKey.length, 24)))
    ) {
      return row;
    }
  }
  return null;
}

/** Fill missing qty/unit/amount on line rows from OCR text (helps already-processed invoices). */
export function enrichLineItemsFromDocumentText(
  items: LineItem[],
  documentText: string | null | undefined
): LineItem[] {
  const text = documentText?.trim();
  if (!text || !items.length) return items;

  const parsedByDesc = parseLineItemRowsFromDocumentText(text);

  return items.map((line) => {
    if (isSummaryLineDescription(line.description)) return line;

    const descKey = normalizeDescriptionKey(line.description);
    const match =
      (descKey && parsedByDesc.get(descKey)) ||
      findLineRowInDocumentText(line.description, text);
    if (!match) return line;

    return {
      ...line,
      qty: line.qty ?? match.qty,
      unit_price: line.unit_price ?? match.unitPrice,
      amount: line.amount ?? match.amount,
    };
  });
}

function findLineRowInDocumentText(
  description: string | null | undefined,
  text: string
): ParsedTextLineRow | null {
  const needle = (description ?? "").trim();
  if (!needle) return null;

  for (const line of text.split(/\r?\n/)) {
    const parsed = parseRowFromTextLine(needle, line);
    if (parsed) return parsed;
  }
  return null;
}

function normalizeDescriptionKey(description: string | null | undefined): string {
  return (description ?? "").trim().toLowerCase().replace(/\s+/g, " ");
}

type ParsedTextLineRow = {
  descKey: string;
  qty: string | null;
  unitPrice: string | null;
  amount: string | null;
};

function parseLineItemRowsFromDocumentText(text: string): Map<string, ParsedTextLineRow> {
  const rows = new Map<string, ParsedTextLineRow>();
  const tailRow5 = new RegExp(
    `(\\d+(?:\\.\\d+)?)\\s+${OPTIONAL_CURRENCY_MONEY_PREFIX}([\\d,]+\\.?\\d*)\\s+${OPTIONAL_CURRENCY_MONEY_PREFIX}([\\d,]+\\.?\\d*)\\s+${OPTIONAL_CURRENCY_MONEY_PREFIX}([\\d,]+\\.?\\d*)\\s*$`,
    "i"
  );
  const tailRow4 = new RegExp(
    `(\\d+(?:\\.\\d+)?)\\s+${OPTIONAL_CURRENCY_MONEY_PREFIX}([\\d,]+\\.?\\d*)\\s+${OPTIONAL_CURRENCY_MONEY_PREFIX}([\\d,]+\\.?\\d*)\\s*$`,
    "i"
  );

  for (const line of text.split(/\r?\n/)) {
    const trimmed = line.trim();
    if (!trimmed || /^(?:description|item|qty|quantity|unit|amount|total|subtotal)\b/i.test(trimmed)) {
      continue;
    }

    const cols = trimmed.split(/\s{2,}|\t+/).map((part) => part.trim()).filter(Boolean);
    if (cols.length >= 4 && !looksLikeMoneyToken(cols[1] ?? "")) {
      const descKey = normalizeDescriptionKey(cols[0]);
      if (!descKey || isSummaryLineDescription(descKey)) continue;
      if (cols.length >= 5) {
        rows.set(descKey, {
          descKey,
          qty: cols[1] ?? null,
          unitPrice: cleanMoneyToken(cols[2]),
          amount: cleanMoneyToken(cols[4]),
        });
      } else {
        rows.set(descKey, {
          descKey,
          qty: cols[1] ?? null,
          unitPrice: cleanMoneyToken(cols[2]),
          amount: cleanMoneyToken(cols[3]),
        });
      }
      continue;
    }

    const tail5 = trimmed.match(tailRow5);
    if (tail5) {
      const desc = trimmed.slice(0, trimmed.length - tail5[0].length).trim();
      const descKey = normalizeDescriptionKey(desc);
      if (!descKey || isSummaryLineDescription(descKey)) continue;
      rows.set(descKey, {
        descKey,
        qty: tail5[1] ?? null,
        unitPrice: cleanMoneyToken(tail5[2]),
        amount: cleanMoneyToken(tail5[4]),
      });
      continue;
    }

    const tail4 = trimmed.match(tailRow4);
    if (tail4) {
      const desc = trimmed.slice(0, trimmed.length - tail4[0].length).trim();
      const descKey = normalizeDescriptionKey(desc);
      if (!descKey || isSummaryLineDescription(descKey)) continue;
      rows.set(descKey, {
        descKey,
        qty: tail4[1] ?? null,
        unitPrice: cleanMoneyToken(tail4[2]),
        amount: cleanMoneyToken(tail4[3]),
      });
    }
  }

  return rows;
}

function looksLikeMoneyToken(raw: string): boolean {
  const cleaned = raw.trim();
  if (!cleaned) return false;
  if (new RegExp(`^${OPTIONAL_CURRENCY_MONEY_PREFIX}[\\d,]+\\.?\\d*$`, "i").test(cleaned)) return true;
  return /^[\d,]+\.\d{2}$/.test(cleaned);
}

function cleanMoneyToken(raw: string | null | undefined): string | null {
  if (raw == null) return null;
  const cleaned = String(raw).replace(/,/g, "").trim();
  return cleaned || null;
}

export function enrichLineItemsForPreview(
  items: LineItem[],
  options?: { exactOnly?: boolean }
): PreviewLineItem[] {
  const exactOnly = options?.exactOnly ?? false;
  return items.map((line) => {
    if (exactOnly) {
      const displayQty = line.qty != null && String(line.qty).trim() ? String(line.qty).trim() : null;
      const displayUnitPrice =
        line.unit_price != null && String(line.unit_price).trim()
          ? String(line.unit_price).trim()
          : null;
      const displayAmount =
        line.amount != null && String(line.amount).trim() ? String(line.amount).trim() : null;
      return { ...line, displayQty, displayUnitPrice, displayAmount };
    }

    const qty = parseNumeric(line.qty);
    const unitPrice = parseNumeric(line.unit_price);
    let amount = parseNumeric(line.amount);

    if (amount == null && qty != null && unitPrice != null) {
      amount = qty * unitPrice;
    }

    let derivedUnitPrice = unitPrice;
    if (derivedUnitPrice == null && amount != null && qty != null && qty > 0) {
      derivedUnitPrice = amount / qty;
    }

    return {
      ...line,
      displayQty: qty != null ? formatNumericForDisplay(qty) : null,
      displayUnitPrice:
        derivedUnitPrice != null ? formatNumericForDisplay(derivedUnitPrice) : null,
      displayAmount: amount != null ? formatNumericForDisplay(amount) : null,
    };
  });
}

export function lineItemColumnsForPreview(items: PreviewLineItem[]): LineItemColumnVisibility {
  return {
    showQty: items.some((line) => hasDisplayValue(line.displayQty)),
    showUnitPrice: items.some((line) => hasDisplayValue(line.displayUnitPrice)),
    showAmount: items.some((line) => hasDisplayValue(line.displayAmount)),
  };
}

/** CSS grid template for drawer line-item rows — columns follow OCR content. */
export function lineItemGridTemplateColumns(
  columns: LineItemColumnVisibility,
  withActions = false,
  showGlAccount = false
): string {
  const parts = ["minmax(11rem, 1fr)"];
  if (columns.showQty) parts.push("5.5rem");
  if (columns.showUnitPrice) parts.push("8.5rem");
  if (columns.showAmount) parts.push("8.5rem");
  if (showGlAccount) parts.push("minmax(11rem, 13rem)");
  if (withActions) parts.push("2.75rem");
  return parts.join(" ");
}

export function countPreviewLineItems(
  inv: InvoiceDetails,
  options: {
    absentFields?: string[];
    extractionFieldKeys?: string[];
    sourceKind?: string;
    lineItems?: LineItem[];
  } = {}
): number {
  return resolvePreviewLineItems(inv, options).items.length;
}

export function resolvePreviewLineItems(
  inv: InvoiceDetails,
  options: {
    absentFields?: string[];
    extractionFieldKeys?: string[];
    sourceKind?: string;
    lineItems?: LineItem[];
  } = {}
): { items: PreviewLineItem[]; columns: LineItemColumnVisibility } {
  const profile = buildDocumentContentProfile(inv, {
    absentFields: options.absentFields ?? [],
    extractionFieldKeys: options.extractionFieldKeys ?? [],
    sourceKind: options.sourceKind ?? "upload",
    lineItems: options.lineItems,
  });
  return { items: profile.lineItems, columns: profile.lineItemColumns };
}

export function anyLineHasQtyOrUnitPrice(items: PreviewLineItem[]): boolean {
  return items.some(
    (line) => hasDisplayValue(line.displayQty) || hasDisplayValue(line.displayUnitPrice)
  );
}

function sumLineAmounts(items: PreviewLineItem[]): string | null {
  if (!items.length) return null;
  let sum = 0;
  for (const line of items) {
    const amount = parseNumeric(line.displayAmount);
    if (amount == null) return null;
    sum += amount;
  }
  return formatNumericForDisplay(sum);
}

export function contentHasFinancialBody(profile: DocumentContentProfile): boolean {
  return (
    profile.lineItems.length > 0 ||
    Boolean(profile.totals.subtotal || profile.totals.tax || profile.totals.total)
  );
}

export function isCompactReceiptStyle(profile: DocumentContentProfile): boolean {
  return (
    profile.lineItems.length === 1 &&
    !profile.totals.subtotal &&
    !profile.dates.due &&
    !anyLineHasQtyOrUnitPrice(profile.lineItems)
  );
}

export function buildDocumentContentProfile(
  inv: InvoiceDetails,
  options: {
    documentTypeLabel?: string | null;
    absentFields?: string[];
    extractionFieldKeys?: string[];
    sourceKind: string;
    lineItems?: LineItem[];
    /** Summary tab: show all extracted values, no derived fields or DT field gating. */
    summaryMode?: boolean;
  }
): DocumentContentProfile {
  const summaryMode = options.summaryMode ?? false;
  const absentFields = summaryMode ? [] : (options.absentFields ?? []);
  const extractionFieldKeys = options.extractionFieldKeys ?? [];

  const counterpartyRaw = counterpartyName(inv);
  const counterparty =
    counterpartyRaw && counterpartyRaw !== "—"
      ? shouldIncludeInSummary("vendor", extractionFieldKeys, absentFields, true, summaryMode)
        ? counterpartyRaw
        : null
      : scalarIfPresent(inv, "vendor", absentFields, extractionFieldKeys, summaryMode);
  const abn = scalarIfPresent(inv, "abn", absentFields, extractionFieldKeys, summaryMode);
  const invoiceNo = scalarIfPresent(inv, "invoice_no", absentFields, extractionFieldKeys, summaryMode);

  const headingRaw = summaryMode
    ? scalarIfPresent(inv, "document_heading", absentFields, extractionFieldKeys, summaryMode)
    : scalarIfPresent(inv, "document_heading", absentFields, extractionFieldKeys, summaryMode) ??
      headingFromDocumentText(inv.document_text);
  const heading = headingRaw || options.documentTypeLabel?.trim() || null;

  const dates: DocumentContentProfile["dates"] = {};
  const issued = scalarIfPresent(inv, "invoice_date", absentFields, extractionFieldKeys, summaryMode);
  const due = scalarIfPresent(inv, "due_date", absentFields, extractionFieldKeys, summaryMode);
  if (issued) dates.issued = issued;
  if (due) dates.due = due;

  const parties = buildPartyBlocks(inv, absentFields, extractionFieldKeys, summaryMode);
  const referenceDetails: ContentReference[] = [];

  pushReference(
    referenceDetails,
    "po_reference",
    inv.po_reference,
    absentFields,
    extractionFieldKeys,
    summaryMode
  );
  pushReference(
    referenceDetails,
    "so_reference",
    inv.so_reference,
    absentFields,
    extractionFieldKeys,
    summaryMode
  );
  pushReference(
    referenceDetails,
    "cost_centre",
    inv.cost_centre,
    absentFields,
    extractionFieldKeys,
    summaryMode
  );
  const billingAddress =
    invoiceScalarRaw(inv, "billing_address") ?? inv.billing_address ?? null;
  if (!shouldOmitBillingAddress(billingAddress, parties, inv.extracted_fields ?? {})) {
    pushReference(
      referenceDetails,
      "billing_address",
      billingAddress,
      absentFields,
      extractionFieldKeys,
      summaryMode
    );
  }
  pushReference(
    referenceDetails,
    "email_subject",
    inv.email_subject,
    absentFields,
    extractionFieldKeys,
    summaryMode
  );
  pushReference(
    referenceDetails,
    "account_code",
    inv.account_code,
    absentFields,
    extractionFieldKeys,
    summaryMode
  );
  pushReference(
    referenceDetails,
    "account_name",
    inv.account_name,
    absentFields,
    extractionFieldKeys,
    summaryMode
  );

  if (
    shouldIncludeInSummary(
      "attachment_name",
      extractionFieldKeys,
      absentFields,
      Boolean(inv.email_attachment_name?.trim()),
      summaryMode
    ) &&
    inv.email_attachment_name?.trim()
  ) {
    referenceDetails.push({
      key: "attachment_name",
      label: referenceLabel("attachment_name"),
      value: inv.email_attachment_name.trim(),
    });
  }

  const extracted = inv.extracted_fields ?? {};
  const headerCounterparty = counterparty ?? "";
  for (const [key, raw] of Object.entries(extracted)) {
    const token = key.trim().toLowerCase();
    if (!token || PROFILE_SCALAR_KEYS.has(token)) continue;
    const value = String(raw ?? "").trim();
    if (!value) continue;
    if (shouldSkipExtractedReference(token, value, headerCounterparty, extracted)) continue;
    if (!shouldIncludeInSummary(token, extractionFieldKeys, absentFields, true, summaryMode)) {
      continue;
    }
    if (referenceDetails.some((row) => row.key === token)) continue;
    referenceDetails.push({ key: token, label: referenceLabel(token), value });
  }

  if (extractionFieldKeys.length && !summaryMode) {
    const order = new Map(extractionFieldKeys.map((key, index) => [key, index]));
    referenceDetails.sort(
      (a, b) => (order.get(a.key) ?? 999) - (order.get(b.key) ?? 999)
    );
  } else {
    referenceDetails.sort((a, b) => a.label.localeCompare(b.label));
  }

  const displayAbn = headerAbnVisible(abn, parties);

  const totals: DocumentContentProfile["totals"] = {};
  const subtotal = scalarIfPresent(inv, "subtotal", absentFields, extractionFieldKeys, summaryMode);
  const tax = scalarIfPresent(inv, "gst", absentFields, extractionFieldKeys, summaryMode);
  const total = scalarIfPresent(inv, "total", absentFields, extractionFieldKeys, summaryMode);
  if (subtotal) totals.subtotal = subtotal;
  if (tax) totals.tax = tax;
  if (total) totals.total = total;

  let bankDetails: string | null = null;
  const bankName = invoiceScalarRaw(inv, "bank_name");
  const bankParts = [bankName, inv.bank_bsb, inv.bank_account]
    .map((v) => (v == null ? "" : String(v).trim()))
    .filter(Boolean);
  if (
    bankParts.length &&
    shouldIncludeInSummary("bank_details", extractionFieldKeys, absentFields, true, summaryMode)
  ) {
    bankDetails = bankParts.join(" / ");
  }

  const rawLineItems = filterLineItemsForPreview(
    options.lineItems ?? inv.line_items,
    buildLineItemHeaderValues(inv)
  );
  const sanitizedLineItems = sanitizeLineItemValues(rawLineItems, total);
  const sourceLineItems = summaryMode
    ? sanitizedLineItems
    : enrichLineItemsFromDocumentText(sanitizedLineItems, inv.document_text);
  const visibleLineItems = shouldSuppressField("line_items", absentFields)
    ? []
    : enrichLineItemsForPreview(sourceLineItems, { exactOnly: summaryMode });
  const lineItemColumns = lineItemColumnsForPreview(visibleLineItems);

  if (!summaryMode) {
    const derivedLineSum = !subtotal ? sumLineAmounts(visibleLineItems) : null;
    if (derivedLineSum) {
      const showDerivedSubtotal =
        visibleLineItems.length > 1 || anyLineHasQtyOrUnitPrice(visibleLineItems);
      if (showDerivedSubtotal) {
        totals.subtotal = derivedLineSum;
      }
      if (!totals.total && !tax) {
        totals.total = derivedLineSum;
      }
    }
  }

  const profileSoFar: DocumentContentProfile = {
    counterparty,
    abn: displayAbn,
    heading,
    invoiceNo,
    docRef: documentDisplayRef(inv),
    dates,
    references: referenceDetails,
    parties,
    referenceDetails,
    lineItems: visibleLineItems,
    lineItemColumns,
    totals,
    bankDetails,
    textExcerpt: null,
    footer: buildPreviewFooter(inv, options.sourceKind),
    emailSender: inv.email_sender?.trim() || null,
  };

  const mayShowTextExcerpt = shouldShowDocumentTextExcerpt(
    extractionFieldKeys,
    absentFields,
    contentHasFinancialBody(profileSoFar),
    Boolean(inv.document_text?.trim()),
    summaryMode
  );
  const excerptMax = summaryMode ? 1200 : 320;
  const textExcerpt = mayShowTextExcerpt
    ? excerptDocumentText(inv.document_text, excerptMax)
    : null;

  return { ...profileSoFar, textExcerpt };
}

export function formatPreviewMoney(
  value: string | null | undefined,
  currency: string | null | undefined,
  locale?: string,
  displaySymbol?: string | null
): string {
  if (value == null || value === "") return "—";
  const n = parseFloat(value);
  if (Number.isNaN(n)) return value;
  // Delegate to money() so blank currency never invents SGD; symbol used when no ISO.
  return money(n, currency, locale || DEFAULT_TENANT_LOCALE, displaySymbol);
}

export type TaxMeta = { label: string; rate: number | null };

type JurisdictionTaxSource =
  | string
  | {
      country?: string | null;
      tax_label?: string | null;
      statutory_tax_rate?: number | null;
    };

type DocumentTaxAmounts = {
  currency?: string | null;
  gst_rate?: string | number | null;
  subtotal?: string | number | null;
  gst?: string | number | null;
};

const TAX_RATE_PERCENT_RE = /(\d+(?:\.\d+)?)\s*%/;

/** Parse a document tax rate into percentage form (10 = 10%). Never uses jurisdiction defaults. */
export function parseDocumentTaxRatePercent(raw: string | number | null | undefined): number | null {
  if (raw == null) return null;
  let token = String(raw).trim();
  if (!token) return null;
  const match = TAX_RATE_PERCENT_RE.exec(token);
  if (match) token = match[1];
  else token = token.replace(/%/g, "").trim();
  if (!token) return null;
  let value = Number(token);
  if (!Number.isFinite(value) || value < 0) return null;
  // Fractions like 0.1 → 10%
  if (value > 0 && value <= 1) value = value * 100;
  if (value > 100) return null;
  return Math.round(value * 100) / 100;
}

/**
 * Tax % for display: extracted `gst_rate`, else calculate from gst ÷ subtotal.
 * Does not use country / statutory application defaults.
 */
export function resolveDocumentTaxRatePercent(amounts: DocumentTaxAmounts): number | null {
  const direct = parseDocumentTaxRatePercent(amounts.gst_rate);
  if (direct != null) return direct;

  const subtotal = Number(amounts.subtotal);
  const gst = Number(amounts.gst);
  if (!Number.isFinite(subtotal) || !Number.isFinite(gst) || subtotal <= 0) return null;
  const inferred = (gst / subtotal) * 100;
  if (!Number.isFinite(inferred) || inferred < 0 || inferred > 100) return null;
  return Math.round(inferred * 100) / 100;
}

/** Resolve tax label only from country / institution (never a default %). */
export function taxMetaForJurisdiction(countryOrInstitution: JurisdictionTaxSource): TaxMeta {
  if (countryOrInstitution && typeof countryOrInstitution === "object") {
    const countryCode = countryOrInstitution.country?.trim().toUpperCase() ?? "";
    const fromCountry = countryCode
      ? COUNTRIES.find((c) => c.code === countryCode)
      : undefined;
    const label =
      countryOrInstitution.tax_label?.trim() ||
      fromCountry?.taxLabel ||
      (countryCode === "US" ? "Sales Tax" : "Tax");
    return { label, rate: null };
  }

  const code = String(countryOrInstitution ?? "").trim().toUpperCase();
  if (!code) return { label: "Tax", rate: null };
  const match = COUNTRIES.find((c) => c.code === code);
  if (!match) return { label: "Tax", rate: null };
  return { label: match.taxLabel, rate: null };
}

/** Thin currency→country lookup for tax label only (no assumed rate). */
export function taxMetaForCurrency(currency: string): TaxMeta {
  const code = String(currency ?? "").trim().toUpperCase();
  if (!code) return { label: "Tax", rate: null };
  const match = COUNTRIES.find((c) => c.currency === code);
  if (!match) return { label: "Tax", rate: null };
  return taxMetaForJurisdiction(match.code);
}

/** Label from jurisdiction/currency + rate from the document (extract or calculate). */
export function invoiceTaxMeta(amounts: DocumentTaxAmounts): TaxMeta {
  const { label } = taxMetaForCurrency(String(amounts.currency ?? ""));
  return { label, rate: resolveDocumentTaxRatePercent(amounts) };
}

export function previewFilename(inv: Invoice): string {
  const attachment = inv.email_attachment_name?.trim();
  if (attachment) return attachment;
  const path = inv.raw_file_path?.trim();
  if (path) {
    const parts = path.replace(/\\/g, "/").split("/");
    const base = parts[parts.length - 1]?.trim();
    if (base) return base;
  }
  return "document";
}

export function previewCaptureSource(inv: Invoice, fallbackSourceKind: string): string {
  const explicit = inv.capture_source?.trim().toLowerCase();
  if (explicit) return explicit;
  return fallbackSourceKind;
}

export function buildPreviewFooter(inv: Invoice, fallbackSourceKind: string): string {
  const filename = previewFilename(inv);
  const source = previewCaptureSource(inv, fallbackSourceKind);
  return `${filename} · captured via ${source}`;
}
