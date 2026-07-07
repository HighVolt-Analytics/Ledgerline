import { ROUTE_TARGETS } from "@/lib/v4RuleBookTypes";
import {
  ensureExtractionSuperset,
  normalizeCompulsoryFields,
} from "@/lib/documentCompulsoryFields";

/** Canonical extraction field presets — align with backend document_type_field_keys.py */

export const EXTRACTION_FIELD_OPTIONS = [
  { key: "vendor", label: "Vendor" },
  { key: "abn", label: "Tax ID / ABN" },
  { key: "invoice_no", label: "Invoice number" },
  { key: "invoice_date", label: "Invoice date" },
  { key: "due_date", label: "Due date" },
  { key: "po_reference", label: "PO reference" },
  { key: "so_reference", label: "SO reference" },  { key: "cost_centre", label: "Cost centre" },
  { key: "subtotal", label: "Subtotal" },
  { key: "gst", label: "Tax (GST/VAT)" },
  { key: "gst_rate", label: "Tax rate (%)" },
  { key: "total", label: "Total" },
  { key: "line_items", label: "Line items" },
  { key: "bank_details", label: "Bank details" },
  { key: "attachment_name", label: "Attachment name" },
  { key: "document_heading", label: "Document heading" },
  { key: "document_text", label: "Document text (OCR body)" },
  { key: "billing_address", label: "Billing address" },
  { key: "seller_name", label: "Seller name" },
  { key: "seller_tax_id", label: "Seller tax ID" },
  { key: "seller_address", label: "Seller address" },
  { key: "buyer_name", label: "Buyer name" },
  { key: "buyer_tax_id", label: "Buyer tax ID" },
  { key: "buyer_address", label: "Buyer address" },
  { key: "email_subject", label: "Email subject" },
  { key: "account_code", label: "Account code" },
  { key: "account_name", label: "Account name" },
] as const;

export type ExtractionFieldKey = (typeof EXTRACTION_FIELD_OPTIONS)[number]["key"];

export type RouteTarget = (typeof ROUTE_TARGETS)[number];

/** OCR ingest keys — not pipeline/accounting standard fields. */
export const INFRASTRUCTURE_ONLY_EXTRACTION_FIELD_KEYS = new Set<ExtractionFieldKey>([
  "document_text",
]);

const PRESET_KEYS = new Set(EXTRACTION_FIELD_OPTIONS.map((row) => row.key));

const STANDARD_EXTRACTION_FIELDS_BY_ROUTE: Record<RouteTarget, ExtractionFieldKey[]> = {
  "Purchase Management": [
    "vendor",
    "abn",
    "invoice_no",
    "invoice_date",
    "due_date",
    "po_reference",
    "cost_centre",
    "subtotal",
    "gst",
    "gst_rate",
    "total",
    "line_items",
    "billing_address",
    "bank_details",
  ],
  "Sales Management": [
    "vendor",
    "abn",
    "invoice_no",
    "invoice_date",
    "due_date",
    "so_reference",
    "subtotal",
    "gst",
    "gst_rate",
    "total",
    "line_items",
    "seller_name",
    "seller_tax_id",
    "seller_address",
    "buyer_name",
    "buyer_tax_id",
    "buyer_address",
    "billing_address",
    "bank_details",
  ],
  "Expenses Management": [
    "vendor",
    "abn",
    "invoice_no",
    "invoice_date",
    "due_date",
    "cost_centre",
    "subtotal",
    "gst",
    "gst_rate",
    "total",
  ],
  "Team Expenses": [
    "vendor",
    "abn",
    "invoice_no",
    "invoice_date",
    "due_date",
    "cost_centre",
    "subtotal",
    "gst",
    "gst_rate",
    "total",
  ],
  Vault: ["document_heading", "attachment_name"],
};

const ROUTE_TARGET_SET = new Set<string>(ROUTE_TARGETS);
const LABEL_BY_KEY = Object.fromEntries(
  EXTRACTION_FIELD_OPTIONS.map((row) => [row.key, row.label])
) as Record<ExtractionFieldKey, string>;

const CUSTOM_FIELD_KEY = /^[a-z][a-z0-9_]{0,63}$/;

const SNAKE_CASE_GUIDANCE =
  "Use lowercase letters, numbers, and underscores (e.g. contract_party).";

/** Normalize user input while typing — lowercase snake_case, strip invalid chars. */
export function formatExtractionFieldKeyInput(raw: string): string {
  let key = raw
    .toLowerCase()
    .replace(/[\s-]+/g, "_")
    .replace(/[^a-z0-9_]/g, "")
    .replace(/_+/g, "_");
  key = key.replace(/^_+/, "").replace(/^[0-9]+/, "");
  return key.slice(0, 64);
}

export function sanitizeExtractionFieldKey(raw: string): string | null {
  const key = formatExtractionFieldKeyInput(raw.trim());
  if (!key || !CUSTOM_FIELD_KEY.test(key)) return null;
  return key;
}

export function extractionFieldKeyError(raw: string): string | null {
  const trimmed = raw.trim();
  if (!trimmed) {
    return "Enter a field name (e.g. contract_party).";
  }
  const formatted = formatExtractionFieldKeyInput(trimmed);
  if (!formatted) {
    return "Must start with a letter.";
  }
  if (!CUSTOM_FIELD_KEY.test(formatted)) {
    return SNAKE_CASE_GUIDANCE;
  }
  return null;
}

export function isValidExtractionFieldKey(key: string): boolean {
  const normalized = sanitizeExtractionFieldKey(key);
  return normalized !== null;
}

export function extractionFieldLabel(key: string): string {
  if (LABEL_BY_KEY[key as ExtractionFieldKey]) {
    return LABEL_BY_KEY[key as ExtractionFieldKey];
  }
  return key
    .split("_")
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

export function normalizeExtractionFieldKeys(values: string[] | null | undefined): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const raw of values ?? []) {
    const key = sanitizeExtractionFieldKey(raw);
    if (!key || seen.has(key)) continue;
    seen.add(key);
    out.push(key);
  }
  return out;
}

export function isPresetExtractionFieldKey(key: string): boolean {
  return PRESET_KEYS.has(key as ExtractionFieldKey);
}

export function isStandardExtractionFieldKey(key: string): boolean {
  return (
    isPresetExtractionFieldKey(key) &&
    !INFRASTRUCTURE_ONLY_EXTRACTION_FIELD_KEYS.has(key as ExtractionFieldKey)
  );
}

function normalizeRouteTarget(routeTarget?: string | null): RouteTarget {
  const token = (routeTarget ?? "").trim();
  if (ROUTE_TARGET_SET.has(token)) {
    return token as RouteTarget;
  }
  return "Vault";
}

export function standardExtractionFieldsForRoute(
  routeTarget?: string | null
): ExtractionFieldKey[] {
  return [...STANDARD_EXTRACTION_FIELDS_BY_ROUTE[normalizeRouteTarget(routeTarget)]];
}

export function splitExtractionFields(keys: string[] | null | undefined): {
  standard: string[];
  custom: string[];
} {
  const normalized = normalizeExtractionFieldKeys(keys);
  const standard: string[] = [];
  const custom: string[] = [];
  for (const key of normalized) {
    if (isStandardExtractionFieldKey(key)) {
      standard.push(key);
    } else {
      custom.push(key);
    }
  }
  return { standard, custom };
}

export function reconcileExtractionFieldsForRoute(input: {
  extractionFields: string[];
  requiredFields: string[];
  nextRoute: string;
}): {
  extractionFields: string[];
  requiredFields: string[];
  removedStandardFields: string[];
} {
  const allowedStandard = new Set(standardExtractionFieldsForRoute(input.nextRoute));
  const { standard, custom } = splitExtractionFields(input.extractionFields);
  const keptStandard = standard.filter((key) => allowedStandard.has(key as ExtractionFieldKey));
  const removedStandardFields = standard.filter(
    (key) => !allowedStandard.has(key as ExtractionFieldKey)
  );
  const mergedExtraction = normalizeExtractionFieldKeys([...keptStandard, ...custom]);
  const requiredFields = normalizeCompulsoryFields(input.requiredFields, mergedExtraction);
  const extractionFields = ensureExtractionSuperset(requiredFields, mergedExtraction);
  return { extractionFields, requiredFields, removedStandardFields };
}

export function extractionFieldsForDocumentType(  documentTypes: Array<{ code: string; extractionFields?: string[]; requiredFields?: string[] }>,
  documentTypeCode: string | null | undefined
): string[] {
  const code = (documentTypeCode ?? "").trim().toUpperCase();
  if (!code) return [];
  const row = documentTypes.find((dt) => dt.code.toUpperCase() === code);
  if (!row) return [];
  const explicit = normalizeExtractionFieldKeys(row.extractionFields);
  if (explicit.length) return explicit;
  return normalizeExtractionFieldKeys(row.requiredFields);
}
