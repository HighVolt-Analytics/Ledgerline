import type { DocumentTypeDefinition } from "@/lib/v5DocumentTypes";
import { isTransPosting } from "@/lib/documentTypeKlass";

type PurchaseKind = "po" | "grn" | "invoice";

function normalizePurchaseKind(value: string | null | undefined): PurchaseKind | null {
  const key = (value ?? "").trim().toLowerCase();
  if (key === "po" || key === "grn" || key === "invoice") return key;
  return null;
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

export function effectiveDocumentTypeCode(
  inv: {
    document_type_code?: string | null;
    purchase_document_type?: string | null;
  },
  documentTypes: DocumentTypeDefinition[]
): string {
  const stored = (inv.document_type_code ?? "").trim().toUpperCase();
  if (stored) return stored;
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

/** Compact label for document-type status chips (kanban cards, tables, headers). */
const DOCUMENT_TYPE_CHIP_LABEL_BY_CODE: Record<string, string> = {
  "DT-01": "Goods invoice",
  "DT-03": "GRN",
  "DT-28": "Delivery note",
};

function normalizeChipLabelFromText(label: string): string | null {
  const token = label.trim().toLowerCase();
  if (!token) return null;
  if (token.includes("po-based goods invoice") || token.includes("po goods invoice")) {
    return "Goods invoice";
  }
  if (token.includes("goods receipt") || token.startsWith("grn")) return "GRN";
  if (token.includes("delivery note")) return "Delivery note";
  return null;
}

export function documentTypeChipDisplayLabel(input: {
  code?: string | null;
  purchaseKind?: string | null;
  label?: string | null;
  documentTypes?: DocumentTypeDefinition[] | null;
}): string {
  const code = (input.code ?? "").trim().toUpperCase();
  if (code && DOCUMENT_TYPE_CHIP_LABEL_BY_CODE[code]) {
    return DOCUMENT_TYPE_CHIP_LABEL_BY_CODE[code]!;
  }

  const fromLabel = input.label ? normalizeChipLabelFromText(input.label) : null;
  if (fromLabel) return fromLabel;

  const purchaseType = (input.purchaseKind ?? "").trim().toLowerCase();
  if (purchaseType === "grn") return "GRN";

  if (code && input.documentTypes?.length) {
    const row = input.documentTypes.find((dt) => dt.code.toUpperCase() === code);
    const short = row?.shortTitle?.trim();
    if (short) {
      const fromShort = normalizeChipLabelFromText(short);
      if (fromShort) return fromShort;
      return short;
    }
  }

  if (code) return code;
  const label = input.label?.trim();
  if (label) return label;
  return "Unclassified";
}

/** List/table label — prefers classified DT document name (title), same as the detail drawer. */
export function invoiceDocumentTypeDisplayLabel(
  inv: {
    document_type_code?: string | null;
    purchase_document_type?: string | null;
    invoice_no?: string | null;
    po_reference?: string | null;
    total?: string | number | null;
    subtotal?: string | number | null;
  },
  documentTypes?: DocumentTypeDefinition[] | null
): string {
  if (documentTypes?.length) {
    const code = effectiveDocumentTypeCode(inv, documentTypes);
    const label = code ? documentTypeLabelForCode(documentTypes, code) : null;
    if (label) return label;
  }
  const stored = (inv.document_type_code ?? "").trim();
  if (stored) return stored;
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
  return "Invoice";
}
