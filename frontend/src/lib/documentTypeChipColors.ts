import {
  approvalStatusChipClass,
  kpiStatusChipClass,
  type KpiModuleColor,
} from "@/lib/kpiModuleColors";
import { isTransPosting } from "@/lib/documentTypeKlass";
import type { DocumentTypeDefinition } from "@/lib/v5DocumentTypes";

export type DocumentTypeChipFamily =
  | "commercial_invoice"
  | "purchase_order"
  | "goods_receipt"
  | "credit_note"
  | "debit_note"
  | "sales"
  | "supporting"
  | "informational"
  | "unclassified";

/** Reserved for workflow status chips — never use on document-type tags. */
const RESERVED_STATUS_KPI: ReadonlySet<KpiModuleColor> = new Set(["green", "blue", "cyan"]);

/** Document-type KPI palette (excludes green / blue / cyan). */
const DOCUMENT_TYPE_KPI_PALETTE: readonly KpiModuleColor[] = [
  "violet",
  "sage",
  "rust",
  "rose",
  "teal",
];

/**
 * Each catalogue DT code gets a stable KPI color (DT-01 violet, DT-02 sage, …).
 * Cycles through the document palette only — never status colors.
 */
function documentTypeKpiColorForCode(code: string): KpiModuleColor {
  const n = Number.parseInt(code.replace(/\D/g, ""), 10);
  if (!Number.isNaN(n) && n > 0) {
    return DOCUMENT_TYPE_KPI_PALETTE[(n - 1) % DOCUMENT_TYPE_KPI_PALETTE.length]!;
  }
  return "violet";
}

/** Fallback when no DT code — one distinct chip class per family (8 categories). */
const FAMILY_CHIP_CLASS: Record<Exclude<DocumentTypeChipFamily, "unclassified">, string> = {
  commercial_invoice: kpiStatusChipClass("violet"),
  purchase_order: kpiStatusChipClass("sage"),
  goods_receipt: kpiStatusChipClass("rust"),
  credit_note: kpiStatusChipClass("rose"),
  debit_note: kpiStatusChipClass("teal"),
  sales: approvalStatusChipClass("edit"),
  supporting: approvalStatusChipClass("pending"),
  informational: approvalStatusChipClass("post"),
};

/** Stable catalogue mapping — same DT code always renders the same chip color. */
const DT_CHIP_FAMILY: Record<string, DocumentTypeChipFamily> = {
  "DT-01": "commercial_invoice",
  "DT-02": "purchase_order",
  "DT-03": "goods_receipt",
  "DT-04": "credit_note",
  "DT-05": "debit_note",
  "DT-06": "commercial_invoice",
  "DT-07": "commercial_invoice",
  "DT-08": "commercial_invoice",
  "DT-09": "commercial_invoice",
  "DT-10": "commercial_invoice",
  "DT-11": "commercial_invoice",
  "DT-12": "commercial_invoice",
  "DT-13": "informational",
  "DT-16": "informational",
  "DT-17": "supporting",
  "DT-18": "informational",
  "DT-19": "commercial_invoice",
  "DT-20": "commercial_invoice",
  "DT-21": "commercial_invoice",
  "DT-22": "informational",
  "DT-23": "informational",
  "DT-24": "informational",
  "DT-25": "informational",
  "DT-26": "sales",
  "DT-27": "sales",
  "DT-28": "goods_receipt",
};

function normalizeCode(code?: string | null): string {
  return (code ?? "").trim().toUpperCase();
}

function familyFromPurchaseKind(kind?: string | null): DocumentTypeChipFamily | null {
  const token = (kind ?? "").trim().toLowerCase();
  if (token === "invoice") return "commercial_invoice";
  if (token === "po") return "purchase_order";
  if (token === "grn") return "goods_receipt";
  return null;
}

function familyFromLabel(label?: string | null): DocumentTypeChipFamily | null {
  const token = (label ?? "").trim().toLowerCase();
  if (!token) return null;
  if (token.includes("credit note")) return "credit_note";
  if (token.includes("debit note")) return "debit_note";
  if (token.includes("customer") || token.includes("sales order")) return "sales";
  if (token.includes("delivery note")) return "goods_receipt";
  if (token === "purchase order" || token.includes("purchase order")) return "purchase_order";
  if (token === "grn" || token.includes("goods receipt")) return "goods_receipt";
  if (token === "invoice" || token.includes("invoice")) return "commercial_invoice";
  return null;
}

function familyFromDefinition(row: DocumentTypeDefinition): DocumentTypeChipFamily {
  const mapped = DT_CHIP_FAMILY[row.code.toUpperCase()];
  if (mapped) return mapped;

  const role = (row.purchaseBundleRole ?? "").trim().toLowerCase();
  if (role === "po") return "purchase_order";
  if (role === "grn") return "goods_receipt";

  if ((row.routeTarget ?? "").toLowerCase().includes("sales")) return "sales";

  const title = `${row.title} ${row.shortTitle}`.toLowerCase();
  if (title.includes("credit note")) return "credit_note";
  if (title.includes("debit note")) return "debit_note";

  if (!isTransPosting(row)) {
    return role ? "supporting" : "informational";
  }

  return "commercial_invoice";
}

export function resolveDocumentTypeChipFamily(input: {
  code?: string | null;
  purchaseKind?: string | null;
  label?: string | null;
  documentTypes?: DocumentTypeDefinition[] | null;
}): DocumentTypeChipFamily {
  const code = normalizeCode(input.code);
  if (code) {
    const mapped = DT_CHIP_FAMILY[code];
    if (mapped) return mapped;
    const row = input.documentTypes?.find((dt) => dt.code.toUpperCase() === code);
    if (row) return familyFromDefinition(row);
    return "commercial_invoice";
  }

  const fromKind = familyFromPurchaseKind(input.purchaseKind);
  if (fromKind) return fromKind;

  const fromLabel = familyFromLabel(input.label);
  if (fromLabel) return fromLabel;

  return "unclassified";
}

export function documentTypeStatusChipClass(input: {
  code?: string | null;
  purchaseKind?: string | null;
  label?: string | null;
  documentTypes?: DocumentTypeDefinition[] | null;
}): string {
  const code = normalizeCode(input.code);
  if (code) {
    const color = documentTypeKpiColorForCode(code);
    if (!RESERVED_STATUS_KPI.has(color)) {
      return kpiStatusChipClass(color);
    }
  }

  const family = resolveDocumentTypeChipFamily(input);
  if (family === "unclassified") return approvalStatusChipClass("muted");
  return FAMILY_CHIP_CLASS[family];
}
