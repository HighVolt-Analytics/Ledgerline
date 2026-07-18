import type { DocumentTypeDefinition } from "@/lib/v5DocumentTypes";
import { isTransPosting } from "@/lib/documentTypeKlass";

type PurchaseKind = "po" | "grn" | "invoice";

type InvoiceTypeFields = {
  document_type_code?: string | null;
  purchase_document_type?: string | null;
  document_heading?: string | null;
  extracted_fields?: Record<string, unknown> | null;
  evaluation_status?: string | null;
  invoice_no?: string | null;
  po_reference?: string | null;
  total?: string | number | null;
  subtotal?: string | number | null;
};

function normalizePurchaseKind(value: string | null | undefined): PurchaseKind | null {
  const key = (value ?? "").trim().toLowerCase();
  if (key === "po" || key === "grn" || key === "invoice") return key;
  return null;
}

/** Vision understood path hold — DT not catalogue-mapped; show AI / printed name. */
export function isVisionUnderstoodHold(
  inv: Pick<InvoiceTypeFields, "evaluation_status"> | null | undefined
): boolean {
  const status = (inv?.evaluation_status ?? "").trim();
  return (
    status === "vision_vaulted" ||
    status === "vision_header_review" ||
    status === "awaiting_classification"
  );
}

/** @deprecated Prefer isVisionUnderstoodHold — kept for existing call sites. */
export function isVisionAwaitingClassification(
  inv: Pick<InvoiceTypeFields, "evaluation_status"> | null | undefined
): boolean {
  return isVisionUnderstoodHold(inv);
}

/** AI / printed document name from vision (or later extract). */
export function visionDocumentTypeLabel(inv: InvoiceTypeFields): string {
  const canonical = inv.extracted_fields?.canonical_document_type;
  if (typeof canonical === "string" && canonical.trim()) return canonical.trim();
  const fromFields = inv.extracted_fields?.document_heading;
  const heading =
    (inv.document_heading ?? "").trim() ||
    (typeof fromFields === "string" ? fromFields.trim() : "");
  return heading;
}

/** Stored catalogue code only — never invent from purchase_document_type. */
export function storedDocumentTypeCode(
  inv: Pick<InvoiceTypeFields, "document_type_code"> | null | undefined
): string {
  return (inv?.document_type_code ?? "").trim().toUpperCase();
}

export function resolveDocumentTypeForPurchaseKind(
  kind: string | null | undefined,
  documentTypes: DocumentTypeDefinition[]
): DocumentTypeDefinition | null {
  const normalized = normalizePurchaseKind(kind);
  if (!normalized) return null;

  const bundleRole = normalized === "po" ? "po" : normalized === "grn" ? "grn" : null;
  if (bundleRole) {
    const match = documentTypes.find(
      (dt) => dt.enabled && (dt.purchaseBundleRole ?? "").toLowerCase() === bundleRole
    );
    if (match) return match;
  }

  if (normalized === "invoice") {
    const transactional = documentTypes.filter(
      (dt) =>
        dt.enabled &&
        dt.routeTarget === "Purchase Management" &&
        isTransPosting(dt)
    );
    if (!transactional.length) return null;
    return [...transactional].sort((a, b) => a.classifier.priority - b.classifier.priority)[0];
  }

  return null;
}

/**
 * Catalogue DT code for an invoice.
 *
 * - Vision hold (`awaiting_classification`): never invent — empty until user/confirm maps DT.
 * - Prefer stored `document_type_code` when present.
 * - Purchase-kind invent is only for legacy rows that already have an evaluation outcome
 *   (not early Received / mid-pipeline), so Upload chips do not show "Non-PO vendor invoice"
 *   before classification.
 */
export function effectiveDocumentTypeCode(
  inv: Pick<
    InvoiceTypeFields,
    "document_type_code" | "purchase_document_type" | "evaluation_status"
  >,
  documentTypes: DocumentTypeDefinition[]
): string {
  const stored = storedDocumentTypeCode(inv);
  if (stored) return stored;

  if (isVisionAwaitingClassification(inv)) {
    return "";
  }

  // Early pipeline: purchase_document_type may be set at ingest, but no DT yet.
  const evalStatus = (inv.evaluation_status ?? "").trim();
  if (!evalStatus) {
    return "";
  }

  const kind = normalizePurchaseKind(inv.purchase_document_type);
  if (!kind) return "";
  return resolveDocumentTypeForPurchaseKind(kind, documentTypes)?.code.toUpperCase() ?? "";
}

export function documentTypeLabelForCode(
  documentTypes: DocumentTypeDefinition[],
  code: string | null | undefined
): string | null {
  const normalized = (code ?? "").trim().toUpperCase();
  if (!normalized) return null;
  const row = documentTypes.find((dt) => dt.code.toUpperCase() === normalized);
  if (!row) return normalized;
  return row.title?.trim() || row.shortTitle?.trim() || normalized;
}

/** Compact chip label — prefers org Rule Book shortTitle. */
export function documentTypeShortLabelForCode(
  documentTypes: DocumentTypeDefinition[],
  code: string | null | undefined
): string | null {
  const normalized = (code ?? "").trim().toUpperCase();
  if (!normalized) return null;
  const row = documentTypes.find((dt) => dt.code.toUpperCase() === normalized);
  if (!row) return normalized;
  return row.shortTitle?.trim() || row.title?.trim() || normalized;
}

/** Compact label for document-type status chips (kanban cards, tables, headers). */
export function documentTypeChipDisplayLabel(input: {
  code?: string | null;
  purchaseKind?: string | null;
  label?: string | null;
  documentTypes?: DocumentTypeDefinition[] | null;
}): string {
  const code = (input.code ?? "").trim().toUpperCase();

  if (code && input.documentTypes?.length) {
    const fromOrg = documentTypeShortLabelForCode(input.documentTypes, code);
    if (fromOrg) return fromOrg;
  }

  const label = input.label?.trim();
  if (label) return label;
  if (code) return code;
  return "Unclassified";
}

/**
 * List/table document-type label — pipeline-aware:
 * - Vision hold / vision header present: AI canonical or printed heading (matches vault)
 * - Classified: catalogue title from stored document_type_code only
 * - Never invent Rule Book titles from purchase_document_type alone
 */
export function invoiceDocumentTypeDisplayLabel(
  inv: InvoiceTypeFields,
  documentTypes?: DocumentTypeDefinition[] | null
): string {
  const vision = visionDocumentTypeLabel(inv);

  // Vision path hold: always prefer AI / printed name over catalogue invent.
  if (isVisionAwaitingClassification(inv)) {
    if (vision) return vision;
  }

  const stored = storedDocumentTypeCode(inv);
  if (stored && documentTypes?.length) {
    const label = documentTypeLabelForCode(documentTypes, stored);
    if (label) return label;
  }
  if (stored) return stored;

  // Header extract done but DT not confirmed yet (or eval not set): show vision name.
  if (vision) return vision;

  const purchaseType = inv.purchase_document_type?.toLowerCase();
  if (purchaseType === "po") return "Purchase Order";
  if (purchaseType === "grn") return "GRN";
  const ref = (inv.invoice_no ?? inv.po_reference ?? "").toLowerCase();
  if (
    ref.includes("credit") ||
    ref.includes("cn-") ||
    ref.startsWith("cn") ||
    ref.includes("credit-note")
  ) {
    return "Credit Note";
  }
  for (const amount of [inv.total, inv.subtotal]) {
    if (amount == null || amount === "") continue;
    const n = parseFloat(String(amount));
    if (!Number.isNaN(n) && n < 0) return "Credit Note";
  }
  if (purchaseType === "invoice") return "Invoice";
  return "Unclassified";
}
