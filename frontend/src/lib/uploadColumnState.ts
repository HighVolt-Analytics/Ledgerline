import type { Invoice } from "@/api/types";
import {
  counterpartyName,
  invoiceCounterpartyConfidence,
  invoiceValidationConfidence,
  validationPassApplicable,
  vendorMatchApplicable,
  type ValidationPassDocumentType,
} from "@/lib/invoice";
import { PIPELINE_STATUSES } from "@/lib/invoiceActions";
import { buildMatrixCells, type MatrixStage } from "@/lib/matrix";
import { storedDocumentTypeCode, visionDocumentTypeLabel } from "@/lib/documentTypeResolve";

export type UploadListColumnId =
  | "documentMeta"
  | "documentType"
  | "counterparty"
  | "route"
  | "glAccount"
  | "evaluation"
  | "vrPass"
  | "match"
  | "total";

export type ColumnDisplayMode = "value" | "processing" | "empty";

const COLUMN_STAGE: Record<UploadListColumnId, MatrixStage> = {
  documentMeta: "Parsed",
  documentType: "Parsed",
  counterparty: "Parsed",
  route: "Parsed",
  glAccount: "Mapped",
  evaluation: "Validated",
  vrPass: "Validated",
  match: "Parsed",
  total: "Parsed",
};

const PIPELINE_ACTIVE = new Set<string>(PIPELINE_STATUSES);

const SETTLED_STATUSES = new Set(["processed", "exception", "rejected", "duplicate_skipped"]);

export function isInvoicePipelineActive(
  inv: Pick<Invoice, "status" | "id">,
  processingIds?: ReadonlySet<number>
): boolean {
  if (PIPELINE_ACTIVE.has(inv.status)) return true;
  if (processingIds?.has(inv.id) && !SETTLED_STATUSES.has(inv.status)) return true;
  return false;
}

function requiredStageComplete(inv: Invoice, column: UploadListColumnId): boolean {
  const cell = buildMatrixCells(inv)[COLUMN_STAGE[column]];
  return cell.state === "done";
}

export function columnHasDisplayValue(
  inv: Invoice,
  column: UploadListColumnId,
  documentTypes?: ValidationPassDocumentType[] | null
): boolean {
  switch (column) {
    case "documentMeta":
      return Boolean(inv.invoice_no?.trim());
    case "documentType":
      // Type = vision / printed heading only (not catalogue DT).
      return Boolean(visionDocumentTypeLabel(inv));
    case "counterparty": {
      const name = counterpartyName(inv);
      return name !== "—" && name.trim().length > 0;
    }
    case "route":
      // Route = mapped Rule Book DT code (not vision heading / vault folder label).
      return Boolean(storedDocumentTypeCode(inv));
    case "glAccount":
      if (inv.gl_posting_applicable === false) return true;
      return Boolean(inv.account_name?.trim());
    case "evaluation":
      return inv.evaluation_status != null;
    case "vrPass":
      if (!validationPassApplicable(inv, documentTypes)) return true;
      return invoiceValidationConfidence(inv, documentTypes) != null;
    case "match":
      if (!vendorMatchApplicable(inv, documentTypes)) return true;
      return invoiceCounterpartyConfidence(inv, documentTypes) != null;
    case "total": {
      const total = inv.total?.trim();
      return Boolean(total && !Number.isNaN(Number(total)));
    }
    default:
      return false;
  }
}

export function uploadColumnDisplayMode(
  inv: Invoice,
  column: UploadListColumnId,
  options?: {
    processingIds?: ReadonlySet<number>;
    documentTypes?: ValidationPassDocumentType[] | null;
  }
): ColumnDisplayMode {
  if (columnHasDisplayValue(inv, column, options?.documentTypes)) {
    return "value";
  }

  const activelyProcessing = isInvoicePipelineActive(inv, options?.processingIds);
  const stageDone = requiredStageComplete(inv, column);

  if (activelyProcessing && !stageDone) {
    return "processing";
  }

  return "empty";
}

export function isStageColumnProcessing(
  inv: Pick<Invoice, "status" | "id" | "current_stage_state">,
  processingIds?: ReadonlySet<number>
): boolean {
  if (!isInvoicePipelineActive(inv, processingIds)) return false;
  const state = inv.current_stage_state;
  return state == null || state === "pending";
}

export function uploadListHasActiveProcessing(
  invoices: Invoice[],
  processingIds?: ReadonlySet<number>
): boolean {
  return invoices.some((inv) => isInvoicePipelineActive(inv, processingIds));
}
