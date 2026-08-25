import { ROUTE_TARGETS } from "@/lib/v4RuleBookTypes";
import {
  ensureExtractionSuperset,
  normalizeCompulsoryFields,
} from "@/lib/documentCompulsoryFields";
import { api } from "@/api/client";

/** Canonical extraction field presets — align with backend document_type_field_keys.py */

export type ExtractionFieldOption = { key: string; label: string };

export const EXTRACTION_FIELD_OPTIONS = [
  { key: "vendor", label: "Vendor" },
  { key: "employee_name", label: "Employee name" },
  { key: "abn", label: "Business registration number" },
  { key: "invoice_no", label: "Invoice number" },
  { key: "proforma_invoice_no", label: "Proforma invoice number" },
  { key: "invoice_date", label: "Invoice date" },
  { key: "due_date", label: "Due date" },
  { key: "po_reference", label: "PO reference" },
  { key: "so_reference", label: "SO reference" },
  { key: "cost_centre", label: "Cost centre" },
  { key: "currency", label: "Currency" },
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
  { key: "email_sender", label: "Sender (email or mobile)" },
  { key: "account_code", label: "Account code" },
  { key: "account_name", label: "Account name" },
] as const satisfies readonly ExtractionFieldOption[];

export type ExtractionFieldKey = (typeof EXTRACTION_FIELD_OPTIONS)[number]["key"];

let cachedRegistryOptions: readonly ExtractionFieldOption[] | null = null;

export async function loadExtractionFieldOptions(): Promise<readonly ExtractionFieldOption[]> {
  try {
    const settings = await api.getSettings();
    if (!settings.use_field_registry) {
      return EXTRACTION_FIELD_OPTIONS;
    }
    const registry = await api.getRegistryFields();
    if (!registry.fields?.length) {
      return EXTRACTION_FIELD_OPTIONS;
    }
    cachedRegistryOptions = registry.fields.map((row) => ({
      key: row.key,
      label: row.label,
    }));
    return cachedRegistryOptions;
  } catch {
    return EXTRACTION_FIELD_OPTIONS;
  }
}

export function getExtractionFieldOptions(): readonly ExtractionFieldOption[] {
  return cachedRegistryOptions ?? EXTRACTION_FIELD_OPTIONS;
}

export type RouteTarget = (typeof ROUTE_TARGETS)[number];

/** OCR ingest keys — not pipeline/accounting standard fields. */
export const INFRASTRUCTURE_ONLY_EXTRACTION_FIELD_KEYS = new Set<ExtractionFieldKey>([
  "document_text",
]);

/**
 * Dossier bundling keys — always offered under Add standard field for every route.
 * Vision soft-bundle priority: invoice_no → proforma_invoice_no → po → so → custom.
 * invoice_no / po / so live on invoice columns; proforma lives in extracted_fields.
 */
export const LINKING_STANDARD_EXTRACTION_FIELD_KEYS = [
  "invoice_no",
  "proforma_invoice_no",
  "po_reference",
  "so_reference",
] as const satisfies readonly ExtractionFieldKey[];

const PRESET_KEYS = new Set(EXTRACTION_FIELD_OPTIONS.map((row) => row.key));

/** Common custom-key aliases that should use linking standard fields instead. */
const LINKING_FIELD_CUSTOM_ALIASES: Record<string, (typeof LINKING_STANDARD_EXTRACTION_FIELD_KEYS)[number]> =
  {
    invoice_number: "invoice_no",
    inv_no: "invoice_no",
    inv_number: "invoice_no",
    invoice_num: "invoice_no",
    invoice_ref: "invoice_no",
    proforma_no: "proforma_invoice_no",
    proforma_number: "proforma_invoice_no",
    proforma_invoice_number: "proforma_invoice_no",
    pro_forma_invoice_no: "proforma_invoice_no",
    po_number: "po_reference",
    po_ref: "po_reference",
    purchase_order: "po_reference",
    purchase_order_no: "po_reference",
    purchase_order_number: "po_reference",
    so_number: "so_reference",
    so_ref: "so_reference",
    sales_order: "so_reference",
    sales_order_no: "so_reference",
    sales_order_number: "so_reference",
  };

const AMBIGUOUS_LINKING_CUSTOM_KEYS = new Set([
  "reference_no",
  "reference_number",
  "ref_no",
  "ref_number",
  "doc_reference",
  "document_reference",
]);

function withLinkingStandardFields(keys: ExtractionFieldKey[]): ExtractionFieldKey[] {
  const seen = new Set(keys);
  const out = [...keys];
  for (const key of LINKING_STANDARD_EXTRACTION_FIELD_KEYS) {
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(key);
  }
  return out;
}

const STANDARD_EXTRACTION_FIELDS_BY_ROUTE: Record<RouteTarget, ExtractionFieldKey[]> = {
  "Purchase Management": withLinkingStandardFields([
    "vendor",
    "abn",
    "invoice_no",
    "invoice_date",
    "due_date",
    "po_reference",
    "cost_centre",
    "currency",
    "subtotal",
    "gst",
    "gst_rate",
    "total",
    "line_items",
    "billing_address",
    "bank_details",
  ]),
  "Sales Management": withLinkingStandardFields([
    "vendor",
    "abn",
    "invoice_no",
    "invoice_date",
    "due_date",
    "so_reference",
    "currency",
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
  ]),
  "Expenses Management": withLinkingStandardFields([
    "vendor",
    "abn",
    "invoice_no",
    "invoice_date",
    "due_date",
    "cost_centre",
    "currency",
    "subtotal",
    "gst",
    "gst_rate",
    "total",
    "line_items",
  ]),
  "Team Expenses": withLinkingStandardFields([
    "email_sender",
    "employee_name",
    "abn",
    "invoice_no",
    "invoice_date",
    "due_date",
    "cost_centre",
    "currency",
    "subtotal",
    "gst",
    "gst_rate",
    "total",
    "line_items",
  ]),
  // invoice_date feeds Vault year/month folders; vendor feeds the vendor folder.
  Vault: withLinkingStandardFields([
    "document_heading",
    "attachment_name",
    "vendor",
    "invoice_no",
    "invoice_date",
  ]),
};

/** Route-level recommended compulsory fields — Rule Book UI guidance only (saved via required_fields). */
export const ROUTE_COMPULSORY_BASELINE: Record<RouteTarget, ExtractionFieldKey[]> = {
  "Purchase Management": ["vendor", "subtotal", "gst", "total", "due_date"],
  "Expenses Management": ["vendor", "subtotal", "gst", "total", "due_date"],
  "Sales Management": ["vendor", "subtotal", "gst", "total", "due_date"],
  "Team Expenses": ["email_sender", "subtotal", "gst", "total"],
  Vault: [],
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
  if (key === "seller_abn") return "Seller business registration number";
  if (key === "buyer_abn") return "Buyer business registration number";
  if (key === "has_abn") return "Has business registration number";
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

export function isLinkingStandardExtractionFieldKey(key: string): boolean {
  return (LINKING_STANDARD_EXTRACTION_FIELD_KEYS as readonly string[]).includes(key);
}

/** Map a custom key to the linking standard field users should add instead. */
export function linkingStandardFieldForCustomAlias(
  key: string
): (typeof LINKING_STANDARD_EXTRACTION_FIELD_KEYS)[number] | null {
  const token = sanitizeExtractionFieldKey(key);
  if (!token) return null;
  return LINKING_FIELD_CUSTOM_ALIASES[token] ?? null;
}

/** Error when a custom key should be a bundling standard field instead. */
export function customFieldLinkingConflictError(raw: string): string | null {
  const token = sanitizeExtractionFieldKey(raw);
  if (!token) return null;
  if (isLinkingStandardExtractionFieldKey(token)) {
    return `“${extractionFieldLabel(token)}” is a standard field — add it under Add standard field so bundling can use it.`;
  }
  const alias = LINKING_FIELD_CUSTOM_ALIASES[token];
  if (alias) {
    return `Use standard field “${extractionFieldLabel(alias)}” (${alias}) instead — custom keys are not used for dossier bundling.`;
  }
  if (AMBIGUOUS_LINKING_CUSTOM_KEYS.has(token)) {
    return `For bundling, add Invoice number, PO reference, or SO reference under Add standard field — not a custom “${token}” field.`;
  }
  return null;
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

export function routeCompulsoryBaseline(routeTarget?: string | null): ExtractionFieldKey[] {
  return [...ROUTE_COMPULSORY_BASELINE[normalizeRouteTarget(routeTarget)]];
}

/** User-facing hint for route compulsory baseline in Rule Book. */
export function routeCompulsoryBaselineHint(routeTarget?: string | null): string | null {
  const route = normalizeRouteTarget(routeTarget);
  const labels = routeCompulsoryBaseline(route).map((key) => extractionFieldLabel(key));
  if (!labels.length) {
    return "Vault route uses only the compulsory fields you star below — no route extras.";
  }
  if (route === "Team Expenses") {
    return `Team route recommends starring: ${labels.join(", ")}. Receipt attachment is enforced separately at approve.`;
  }
  return `This route recommends starring: ${labels.join(", ")}. Star them below (or use Apply route recommendations) so approve and settlement stay aligned.`;
}

/** Route-recommended keys not yet starred compulsory on this document type. */
export function missingRouteRecommendations(input: {
  routeTarget?: string | null;
  requiredFields: string[];
  extractionFields: string[];
  transactional: boolean;
}): string[] {
  if (!input.transactional) return [];
  const recommended = new Set(routeCompulsoryBaseline(input.routeTarget));
  const starred = new Set(
    normalizeCompulsoryFields(input.requiredFields, input.extractionFields)
  );
  return [...recommended].filter((key) => !starred.has(key));
}

export function formatRouteRecommendationList(routeTarget?: string | null): string {
  return routeCompulsoryBaseline(routeTarget)
    .map((key) => extractionFieldLabel(key))
    .join(", ");
}

const NON_TRANSACTIONAL_PLAYBOOK_PROFILES = new Set([
  "supporting",
  "non_actionable",
  "informational",
  "reconciliation",
  "master_data",
  "compliance_route",
]);

/** True when route compulsory baseline should apply in Rule Book. */
export function isTransactionalForRouteCompulsory(draft: {
  posting?: string;
  playbookProfile?: string;
}): boolean {
  if ((draft.posting ?? "").trim() === "No") return false;
  const profile = (draft.playbookProfile ?? "").trim().toLowerCase();
  if (NON_TRANSACTIONAL_PLAYBOOK_PROFILES.has(profile)) return false;
  return true;
}

export function mergeRouteCompulsoryIntoConfig(input: {
  requiredFields: string[];
  extractionFields: string[];
  routeTarget: string;
  transactional: boolean;
}): { requiredFields: string[]; extractionFields: string[] } {
  const extractionBase = normalizeExtractionFieldKeys(input.extractionFields);
  if (!input.transactional) {
    const requiredFields = normalizeCompulsoryFields(input.requiredFields, extractionBase);
    return {
      requiredFields,
      extractionFields: ensureExtractionSuperset(requiredFields, extractionBase),
    };
  }

  const baseline = routeCompulsoryBaseline(input.routeTarget);
  const mergedRequired = normalizeExtractionFieldKeys([...input.requiredFields, ...baseline]);
  const extractionFields = ensureExtractionSuperset(mergedRequired, extractionBase);
  const requiredFields = normalizeCompulsoryFields(mergedRequired, extractionFields);
  return { requiredFields, extractionFields };
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
