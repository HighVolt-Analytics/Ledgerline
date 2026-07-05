import type { Invoice, InvoiceDetails, LineItem } from "@/api/types";
import { documentDisplayRef } from "@/lib/format";
import { extractionFieldLabel } from "@/lib/documentExtractionFields";
import { counterpartyKind, counterpartyName } from "@/lib/invoice";

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
  extractionFieldKeys: string[]
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
    if (!shouldIncludeInSummary(block.key, extractionFieldKeys, absentFields, true)) return;
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
  hasValue: boolean
): boolean {
  if (shouldSuppressField(key, absentFields)) return false;
  if (hasValue) return true;
  return false;
}

/** Whether document_text OCR excerpt should appear alongside structured summary. */
export function shouldShowDocumentTextExcerpt(
  extractionFieldKeys: string[],
  absentFields: string[],
  hasFinancialBody: boolean,
  hasDocumentText: boolean
): boolean {
  if (!hasDocumentText || shouldSuppressField("document_text", absentFields)) return false;
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
  extractionFieldKeys: string[]
): string | null {
  const raw = invoiceScalarRaw(inv, key);
  if (!shouldIncludeInSummary(key, extractionFieldKeys, absentFields, Boolean(raw))) return null;
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
  extractionFieldKeys: string[]
): void {
  const text = value?.trim();
  if (!text) return;
  if (!shouldIncludeInSummary(key, extractionFieldKeys, absentFields, true)) return;
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
  if (/^(?:total|subtotal|grand total|gst|tax)\b/.test(text)) return true;
  if (/\b(?:total\s+no\.?\s+of\s+pallet|no\.?\s+of\s+pallet)\b/.test(text)) return true;
  if (/^(?:customer|ship(?:ped)?(?:\s*(?:to|date|qty|ped))?|delivery\s*date|invoice\s*(?:no|number|#)|po\s*(?:no|number|reference)?|order\s*(?:no|number)?|so\s*reference|bill(?:ed)?\s*to|ship\s*to|vendor|supplier|abn|gstin|bsb|account\s*(?:no|number)?|payment\s*terms|due\s*date|date\s*paid|receipt\s*(?:no|number)?|phone|tel(?:ephone)?|mobile|email|fax|address|attn|attention)\s*:?\s*$/.test(text)) {
    return true;
  }
  if (/^(?:description|item|product|qty|quantity|unit\s*price|amount|rate|uom|sku)\s*:?\s*$/.test(text)) {
    return true;
  }
  if (text.endsWith(":") && text.length <= 40) return true;
  return false;
}

function filterLineItemsForPreview(items: LineItem[]): LineItem[] {
  return items.filter((line) => !isSummaryLineDescription(line.description));
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

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function parseRowFromTextLine(description: string, line: string): ParsedTextLineRow | null {
  const needle = description.trim();
  if (!needle || !line.toLowerCase().includes(needle.toLowerCase())) return null;

  const cols = line
    .trim()
    .split(/\s{2,}|\t+/)
    .map((part) => part.trim())
    .filter(Boolean);
  if (
    cols.length >= 4 &&
    cols[0].toLowerCase().startsWith(needle.toLowerCase().slice(0, Math.min(needle.length, 24)))
  ) {
    return {
      descKey: normalizeDescriptionKey(cols[0]),
      qty: cols[1] ?? null,
      unitPrice: cleanMoneyToken(cols[2]),
      amount: cleanMoneyToken(cols[3]),
    };
  }

  const escaped = escapeRegExp(needle);
  const inline = line.match(
    new RegExp(
      `${escaped}\\s+(\\d+(?:\\.\\d+)?)\\s+(?:[$€£]|AUD\\s*)?([\\d,]+\\.?\\d*)\\s+(?:[$€£]|AUD\\s*)?([\\d,]+\\.?\\d*)`,
      "i"
    )
  );
  if (!inline) return null;

  return {
    descKey: normalizeDescriptionKey(needle),
    qty: inline[1] ?? null,
    unitPrice: cleanMoneyToken(inline[2]),
    amount: cleanMoneyToken(inline[3]),
  };
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
  const fullRow = /^(.{4,120}?)\s+(\d+(?:\.\d+)?)\s+(?:[$€£]|AUD\s*)?([\d,]+\.?\d*)\s+(?:[$€£]|AUD\s*)?([\d,]+\.?\d*)\s*$/i;

  for (const line of text.split(/\r?\n/)) {
    const trimmed = line.trim();
    if (!trimmed || /^(?:description|item|qty|quantity|unit|amount|total|subtotal)\b/i.test(trimmed)) {
      continue;
    }

    const cols = trimmed.split(/\s{2,}|\t+/).map((part) => part.trim()).filter(Boolean);
    if (cols.length >= 4) {
      const descKey = normalizeDescriptionKey(cols[0]);
      if (!descKey || isSummaryLineDescription(descKey)) continue;
      rows.set(descKey, {
        descKey,
        qty: cols[1] ?? null,
        unitPrice: cleanMoneyToken(cols[2]),
        amount: cleanMoneyToken(cols[3]),
      });
      continue;
    }

    const match = trimmed.match(fullRow);
    if (match) {
      const descKey = normalizeDescriptionKey(match[1]);
      if (!descKey || isSummaryLineDescription(descKey)) continue;
      rows.set(descKey, {
        descKey,
        qty: match[2] ?? null,
        unitPrice: cleanMoneyToken(match[3]),
        amount: cleanMoneyToken(match[4]),
      });
      continue;
    }

    const tail = trimmed.match(
      /(\d+(?:\.\d+)?)\s+(?:[$€£]|AUD\s*)?([\d,]+\.?\d*)\s+(?:[$€£]|AUD\s*)?([\d,]+\.?\d*)\s*$/i
    );
    if (!tail) continue;
    const desc = trimmed.slice(0, trimmed.length - tail[0].length).trim();
    if (desc.length < 4 || isSummaryLineDescription(desc)) continue;
    const descKey = normalizeDescriptionKey(desc);
    rows.set(descKey, {
      descKey,
      qty: tail[1] ?? null,
      unitPrice: cleanMoneyToken(tail[2]),
      amount: cleanMoneyToken(tail[3]),
    });
  }

  return rows;
}

function cleanMoneyToken(raw: string | null | undefined): string | null {
  if (raw == null) return null;
  const cleaned = String(raw).replace(/,/g, "").trim();
  return cleaned || null;
}

export function enrichLineItemsForPreview(items: LineItem[]): PreviewLineItem[] {
  return items.map((line) => {
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
  }
): DocumentContentProfile {
  const absentFields = options.absentFields ?? [];
  const extractionFieldKeys = options.extractionFieldKeys ?? [];

  const counterpartyRaw = counterpartyName(inv);
  const counterparty =
    counterpartyRaw && counterpartyRaw !== "—"
      ? shouldIncludeInSummary("vendor", extractionFieldKeys, absentFields, true)
        ? counterpartyRaw
        : null
      : scalarIfPresent(inv, "vendor", absentFields, extractionFieldKeys);
  const abn = scalarIfPresent(inv, "abn", absentFields, extractionFieldKeys);
  const invoiceNo = scalarIfPresent(inv, "invoice_no", absentFields, extractionFieldKeys);

  const headingRaw =
    scalarIfPresent(inv, "document_heading", absentFields, extractionFieldKeys) ??
    headingFromDocumentText(inv.document_text);
  const heading = headingRaw || options.documentTypeLabel?.trim() || null;

  const dates: DocumentContentProfile["dates"] = {};
  const issued = scalarIfPresent(inv, "invoice_date", absentFields, extractionFieldKeys);
  const due = scalarIfPresent(inv, "due_date", absentFields, extractionFieldKeys);
  if (issued) dates.issued = issued;
  if (due) dates.due = due;

  const parties = buildPartyBlocks(inv, absentFields, extractionFieldKeys);
  const referenceDetails: ContentReference[] = [];

  pushReference(
    referenceDetails,
    "po_reference",
    inv.po_reference,
    absentFields,
    extractionFieldKeys
  );
  pushReference(
    referenceDetails,
    "so_reference",
    inv.so_reference,
    absentFields,
    extractionFieldKeys
  );
  pushReference(
    referenceDetails,
    "cost_centre",
    inv.cost_centre,
    absentFields,
    extractionFieldKeys
  );
  const billingAddress =
    invoiceScalarRaw(inv, "billing_address") ?? inv.billing_address ?? null;
  if (!shouldOmitBillingAddress(billingAddress, parties, inv.extracted_fields ?? {})) {
    pushReference(
      referenceDetails,
      "billing_address",
      billingAddress,
      absentFields,
      extractionFieldKeys
    );
  }
  pushReference(
    referenceDetails,
    "email_subject",
    inv.email_subject,
    absentFields,
    extractionFieldKeys
  );
  pushReference(
    referenceDetails,
    "account_code",
    inv.account_code,
    absentFields,
    extractionFieldKeys
  );
  pushReference(
    referenceDetails,
    "account_name",
    inv.account_name,
    absentFields,
    extractionFieldKeys
  );

  if (
    shouldIncludeInSummary(
      "attachment_name",
      extractionFieldKeys,
      absentFields,
      Boolean(inv.email_attachment_name?.trim())
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
    if (!shouldIncludeInSummary(token, extractionFieldKeys, absentFields, true)) continue;
    if (referenceDetails.some((row) => row.key === token)) continue;
    referenceDetails.push({ key: token, label: referenceLabel(token), value });
  }

  if (extractionFieldKeys.length) {
    const order = new Map(extractionFieldKeys.map((key, index) => [key, index]));
    referenceDetails.sort(
      (a, b) => (order.get(a.key) ?? 999) - (order.get(b.key) ?? 999)
    );
  }

  const displayAbn = headerAbnVisible(abn, parties);

  const totals: DocumentContentProfile["totals"] = {};
  const subtotal = scalarIfPresent(inv, "subtotal", absentFields, extractionFieldKeys);
  const tax = scalarIfPresent(inv, "gst", absentFields, extractionFieldKeys);
  const total = scalarIfPresent(inv, "total", absentFields, extractionFieldKeys);
  if (subtotal) totals.subtotal = subtotal;
  if (tax) totals.tax = tax;
  if (total) totals.total = total;

  let bankDetails: string | null = null;
  const bankParts = [inv.bank_bsb, inv.bank_account]
    .map((v) => (v == null ? "" : String(v).trim()))
    .filter(Boolean);
  if (
    bankParts.length &&
    shouldIncludeInSummary("bank_details", extractionFieldKeys, absentFields, true)
  ) {
    bankDetails = bankParts.join(" / ");
  }

  const rawLineItems = filterLineItemsForPreview(options.lineItems ?? inv.line_items);
  const sanitizedLineItems = sanitizeLineItemValues(rawLineItems, total);
  const sourceLineItems = enrichLineItemsFromDocumentText(
    sanitizedLineItems,
    inv.document_text
  );
  const visibleLineItems = shouldSuppressField("line_items", absentFields)
    ? []
    : enrichLineItemsForPreview(sourceLineItems);
  const lineItemColumns = lineItemColumnsForPreview(visibleLineItems);

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
    Boolean(inv.document_text?.trim())
  );
  const textExcerpt = mayShowTextExcerpt ? excerptDocumentText(inv.document_text) : null;

  return { ...profileSoFar, textExcerpt };
}

export function formatPreviewMoney(
  value: string | null | undefined,
  currency: string
): string {
  if (value == null || value === "") return "—";
  const n = parseFloat(value);
  if (Number.isNaN(n)) return value;
  try {
    return new Intl.NumberFormat("en-US", {
      style: "currency",
      currency: currency || "AUD",
    }).format(n);
  } catch {
    return value;
  }
}

export function taxMetaForCurrency(currency: string): { label: string; rate: number } {
  if (currency === "INR") return { label: "GST", rate: 18 };
  if (currency === "GBP") return { label: "VAT", rate: 20 };
  return { label: "GST", rate: 10 };
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
