import type { Invoice } from "@/api/types";
import { PIPELINE_STATUSES as PIPELINE_STATUS_LIST } from "@/lib/invoiceActions";

export const APPROVAL_BOARD_COLUMNS = [
  { key: "pending", label: "To review" },
  { key: "awaiting", label: "Processing" },
  { key: "approved", label: "Approved" },
  { key: "rejected", label: "Rejected" },
] as const;

export type ApprovalBoardColumnKey = (typeof APPROVAL_BOARD_COLUMNS)[number]["key"];

export const PIPELINE_STATUSES = new Set<string>(PIPELINE_STATUS_LIST);

export const APPROVAL_QUEUE_STATUSES = new Set(["exception", "duplicate_skipped", "rejected"]);

export const APPROVABLE_STATUSES = new Set(["exception", "rejected", "duplicate_skipped"]);

export const PERMANENTLY_DELETABLE = new Set(["rejected", "duplicate_skipped"]);

export const REJECTED_STATUSES = new Set(["rejected", "duplicate_skipped"]);

const SETTLED_AFTER_PIPELINE = new Set(["processed", "exception", ...REJECTED_STATUSES]);

export function boardStatusPriority(status: string): number {
  if (REJECTED_STATUSES.has(status)) return 4;
  if (PIPELINE_STATUSES.has(status)) return 3;
  if (status === "processed") return 2;
  if (status === "exception") return 1;
  return 0;
}

export function mergeBoardInvoices(rows: Invoice[]): Invoice[] {
  const byId = new Map<number, Invoice>();
  for (const inv of rows) {
    const prev = byId.get(inv.id);
    if (!prev || boardStatusPriority(inv.status) >= boardStatusPriority(prev.status)) {
      byId.set(inv.id, inv);
    }
  }
  return [...byId.values()];
}

export function columnForInvoice(
  inv: Invoice,
  pinnedRejectedIds?: ReadonlySet<number>,
  processingIds?: ReadonlySet<number>
): ApprovalBoardColumnKey {
  if (processingIds?.has(inv.id)) return "awaiting";
  if (pinnedRejectedIds?.has(inv.id)) return "rejected";
  if (REJECTED_STATUSES.has(inv.status)) return "rejected";
  if (inv.status === "processed") return "approved";
  if (inv.status === "exception") return "pending";
  if (PIPELINE_STATUSES.has(inv.status)) return "awaiting";
  return "pending";
}

export function shouldClearProcessingId(
  status: string,
  sawPipeline: boolean
): boolean {
  if (PIPELINE_STATUSES.has(status)) return false;
  if (status === "processed" || REJECTED_STATUSES.has(status)) return true;
  if (status === "exception") return sawPipeline;
  return false;
}

export function mergeBoardRowWithLocal(
  row: Invoice,
  local: Invoice | undefined,
  processingIds: ReadonlySet<number>
): Invoice {
  if (processingIds.has(row.id)) {
    if (PIPELINE_STATUSES.has(row.status)) return row;
    if (local && PIPELINE_STATUSES.has(local.status)) return local;
    if (local?.status === "pending") return local;
  }
  return row;
}

export function canShowPermanentDelete(
  inv: Invoice,
  pinnedRejectedIds?: ReadonlySet<number>
): boolean {
  if (PERMANENTLY_DELETABLE.has(inv.status)) return true;
  return Boolean(pinnedRejectedIds?.has(inv.id));
}

export function isPipelineSettled(status: string, sawPipeline: boolean): boolean {
  return SETTLED_AFTER_PIPELINE.has(status) && shouldClearProcessingId(status, sawPipeline);
}
