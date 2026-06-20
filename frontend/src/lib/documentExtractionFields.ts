/** Canonical extraction field presets — align with backend document_type_field_keys.py */

export const EXTRACTION_FIELD_OPTIONS = [
  { key: "vendor", label: "Vendor" },
  { key: "abn", label: "Tax ID / ABN" },
  { key: "invoice_no", label: "Invoice number" },
  { key: "invoice_date", label: "Invoice date" },
  { key: "due_date", label: "Due date" },
  { key: "po_reference", label: "PO reference" },
  { key: "cost_centre", label: "Cost centre" },
  { key: "subtotal", label: "Subtotal" },
  { key: "gst", label: "Tax (GST/VAT)" },
  { key: "total", label: "Total" },
  { key: "line_items", label: "Line items" },
  { key: "bank_details", label: "Bank details" },
  { key: "attachment_name", label: "Attachment name" },
  { key: "document_text", label: "Document text (OCR body)" },
  { key: "billing_address", label: "Billing address" },
  { key: "email_subject", label: "Email subject" },
  { key: "account_code", label: "Account code" },
  { key: "account_name", label: "Account name" },
] as const;

export type ExtractionFieldKey = (typeof EXTRACTION_FIELD_OPTIONS)[number]["key"];

const PRESET_KEYS = new Set(EXTRACTION_FIELD_OPTIONS.map((row) => row.key));

const LABEL_BY_KEY = Object.fromEntries(
  EXTRACTION_FIELD_OPTIONS.map((row) => [row.key, row.label])
) as Record<ExtractionFieldKey, string>;

const CUSTOM_FIELD_KEY = /^[a-z][a-z0-9_]{0,63}$/;

export function sanitizeExtractionFieldKey(raw: string): string | null {
  const key = raw.trim().toLowerCase().replace(/\s+/g, "_");
  if (!key || !CUSTOM_FIELD_KEY.test(key)) return null;
  return key;
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

export function extractionFieldsForDocumentType(
  documentTypes: Array<{ code: string; extractionFields?: string[]; requiredFields?: string[] }>,
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
