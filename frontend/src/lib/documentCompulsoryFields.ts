import shippedDefaults from "@/lib/documentTypeDefaults.json";
import { normalizeExtractionFieldKeys } from "@/lib/documentExtractionFields";
import {
  effectiveValidationRules,
  type ValidationRuleConfig,
} from "@/lib/documentValidationChecks";

type DefaultsRow = {
  required_fields?: string[];
};

const DEFAULTS_INDEX = shippedDefaults as Record<string, DefaultsRow>;

/** Keys that block GL posting when absent (subset of compulsory). */
export const POSTING_CRITICAL_FIELD_KEYS = new Set([
  "vendor",
  "invoice_no",
  "invoice_date",
  "due_date",
  "total",
  "subtotal",
  "gst",
  "gst_rate",
  "abn",
  "po_reference",
  "so_reference",
  "line_items",
  "seller_name",
  "seller_abn",
  "buyer_name",
  "buyer_abn",
  "bank_details",
]);

export function isPostingCriticalField(key: string): boolean {
  return POSTING_CRITICAL_FIELD_KEYS.has(key.trim().toLowerCase());
}

/** Keys filled by ingest/OCR — should not be starred compulsory for playbook blocking. */
export const INFRASTRUCTURE_EXTRACTION_FIELD_KEYS = new Set([
  "attachment_name",
  "document_text",
]);

/** Compulsory keys must be a subset of extraction keys. Preserves empty (all optional). */
export function normalizeCompulsoryFields(
  required: string[] | null | undefined,
  extraction: string[] | null | undefined
): string[] {
  const ext = normalizeExtractionFieldKeys(extraction ?? []);
  const extSet = new Set(ext);
  const req = normalizeExtractionFieldKeys(required ?? []).filter(
    (key) => !INFRASTRUCTURE_EXTRACTION_FIELD_KEYS.has(key)
  );
  return req.filter((key) => extSet.has(key));
}

/** Ensure extraction list contains every compulsory key. */
export function ensureExtractionSuperset(
  required: string[],
  extraction: string[]
): string[] {
  const out = normalizeExtractionFieldKeys(extraction);
  const seen = new Set(out);
  for (const key of normalizeExtractionFieldKeys(required)) {
    if (!seen.has(key)) {
      out.push(key);
      seen.add(key);
    }
  }
  return out;
}

export function defaultCompulsoryForTemplate(matrixCode: string): string[] {
  const row = DEFAULTS_INDEX[matrixCode.trim().toUpperCase()];
  return normalizeExtractionFieldKeys(row?.required_fields ?? []);
}

export function optionalExtractionFields(
  extraction: string[],
  required: string[]
): string[] {
  const compulsory = new Set(normalizeExtractionFieldKeys(required));
  return normalizeExtractionFieldKeys(extraction).filter((key) => !compulsory.has(key));
}

type ApprovalFieldBag = {
  vendor?: string | null;
  total?: string | null;
  due_date?: string | null;
  invoice_no?: string | null;
  po_reference?: string | null;
  invoice_date?: string | null;
  subtotal?: string | null;
  gst?: string | null;
  abn?: string | null;
  cost_centre?: string | null;
  billing_address?: string | null;
  line_items?: unknown[] | null;
};

function approvalFieldPresent(fields: ApprovalFieldBag, key: string): boolean {
  const token = key.trim().toLowerCase();
  if (token === "vendor") return Boolean(fields.vendor?.trim());
  if (token === "invoice_no") return Boolean(fields.invoice_no?.trim());
  if (token === "po_reference") return Boolean(fields.po_reference?.trim());
  if (token === "due_date") return Boolean(fields.due_date?.trim());
  if (token === "invoice_date") return Boolean(fields.invoice_date?.trim());
  if (token === "total") {
    const raw = fields.total?.trim();
    return Boolean(raw && !Number.isNaN(Number(raw)) && Number(raw) > 0);
  }
  if (token === "subtotal") {
    const raw = fields.subtotal?.trim();
    return Boolean(raw && !Number.isNaN(Number(raw)));
  }
  if (token === "gst") {
    const raw = fields.gst?.trim();
    return Boolean(raw && !Number.isNaN(Number(raw)));
  }
  if (token === "abn") return Boolean(fields.abn?.trim());
  if (token === "cost_centre") return Boolean(fields.cost_centre?.trim());
  if (token === "billing_address") return Boolean(fields.billing_address?.trim());
  if (token === "line_items") return Boolean(fields.line_items?.length);
  return false;
}

export function validateCompulsoryFieldsForApproval(
  fields: ApprovalFieldBag,
  compulsory: string[]
): { ok: true } | { ok: false; message: string } {
  const missing = compulsory.filter((key) => !approvalFieldPresent(fields, key));
  if (missing.length) {
    return {
      ok: false,
      message: `Cannot approve: missing compulsory field(s): ${missing.join(", ")}. Save corrections before approving.`,
    };
  }
  return { ok: true };
}

export function compulsoryFieldsForDocumentType(
  documentTypes: Array<{
    code: string;
    requiredFields?: string[];
    validationProfile?: string;
    validationRules?: ValidationRuleConfig[];
  }>,
  code: string | null | undefined
): string[] {
  const token = (code ?? "").trim().toUpperCase();
  if (!token) return [];
  const row = documentTypes.find((dt) => dt.code.trim().toUpperCase() === token);
  if (!row) return [];
  const vr03Enabled = effectiveValidationRules(row).some(
    (rule) => rule.code === "VR03" && rule.enabled
  );
  if (!vr03Enabled) return [];
  return normalizeExtractionFieldKeys(row.requiredFields ?? []);
}
