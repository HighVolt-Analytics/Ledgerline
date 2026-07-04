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
  return row.shortTitle?.trim() || row.title?.trim() || normalized;
}

/** List/table label — prefers classified DT short title, same as the detail drawer. */
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
