import type { Invoice } from "@/api/types";
import {
  canReprocessInvoice,
  invoiceCanAttemptReprocess,
  allowsApprovalWithoutStoredFile,
  PIPELINE_STATUSES as PIPELINE_STATUS_LIST,
} from "@/lib/invoiceActions";
import { effectiveEvaluationStatus, isNeedsReviewEvaluation, isPendingApprovalEvaluation } from "@/lib/invoice";

export type ApprovalBoardColumnApi = "review" | "processing" | "approved" | "rejected";

export const APPROVAL_BOARD_COLUMNS = [
  { key: "pending", label: "Review", apiColumn: "review" as const },
  { key: "awaiting", label: "Processing", apiColumn: "processing" as const },
  { key: "approved", label: "Approved", apiColumn: "approved" as const },
  { key: "rejected", label: "Rejected", apiColumn: "rejected" as const },
] as const;

export type ApprovalBoardColumnKey = (typeof APPROVAL_BOARD_COLUMNS)[number]["key"];

export const PIPELINE_STATUSES = new Set<string>(PIPELINE_STATUS_LIST);

export const APPROVAL_QUEUE_STATUSES = new Set(["exception", "duplicate_skipped", "rejected"]);

export const APPROVABLE_STATUSES = new Set(["exception", "rejected", "duplicate_skipped"]);

export const PERMANENTLY_DELETABLE = new Set(["rejected", "duplicate_skipped"]);

export const REJECTED_STATUSES = new Set(["rejected", "duplicate_skipped"]);

const PRE_CLASSIFICATION_EVAL = new Set(["awaiting_classification", "needs_rescan"]);

const SETTLED_AFTER_PIPELINE = new Set(["processed", "exception", ...REJECTED_STATUSES]);

const API_TO_COLUMN_KEY: Record<ApprovalBoardColumnApi, ApprovalBoardColumnKey> = {
  review: "pending",
  processing: "awaiting",
  approved: "approved",
  rejected: "rejected",
};

export function isClassificationConfirmed(inv: Invoice): boolean {
  return Boolean(inv.document_type_code?.trim());
}

export function isPreClassificationReview(inv: Invoice): boolean {
  const col = columnForInvoice(inv);
  return col === "pending";
}

function hasVisionBundleSnapshot(inv: Invoice): boolean {
  const fields = inv.extracted_fields;
  return (
    fields != null &&
    typeof fields === "object" &&
    ("vision_bundle_kind" in fields || "vision_bundle_key" in fields)
  );
}

/** Understood-path docs finished at vault — no posting from Approvals. */
export function isVisionVaultTerminal(inv: Invoice): boolean {
  const evalStatus = (inv.evaluation_status ?? "").trim();
  if (evalStatus === "vision_vaulted") return true;
  if (evalStatus === "awaiting_classification" && hasVisionBundleSnapshot(inv)) return true;
  return false;
}

export function canShowConfirmOnBoard(inv: Invoice, column: ApprovalBoardColumnKey): boolean {
  if (isVisionVaultTerminal(inv)) return false;
  if (column === "approved" || column === "pending" || column === "rejected") return false;
  return APPROVABLE_STATUSES.has(inv.status);
}

export function canShowApproveOnBoard(inv: Invoice, column: ApprovalBoardColumnKey): boolean {
  if (isVisionVaultTerminal(inv)) return false;
  if (column === "approved" || column === "rejected") return false;
  if (!APPROVABLE_STATUSES.has(inv.status)) return false;

  // Processing: manager sign-off while policy holds the document.
  if (column === "awaiting") {
    return isPendingApprovalInvoice(inv);
  }

  // Review: without-document / manual claims are already classified and must
  // still expose Approve (Reject alone is not enough).
  if (column === "pending") {
    return (
      inv.status === "exception" &&
      isClassificationConfirmed(inv) &&
      allowsApprovalWithoutStoredFile(inv)
    );
  }
  return false;
}

/** Reject from Approved: ledger-posted rows, or vision-understood vaulted rows. */
export function canShowRejectOnApprovedBoard(inv: Invoice): boolean {
  if (inv.status === "processed") return true;
  if (inv.status !== "exception") return false;
  const evalStatus = inv.evaluation_status ?? "";
  if (evalStatus === "vision_vaulted") return true;
  const fields = inv.extracted_fields;
  const hasVisionBundle =
    fields != null &&
    typeof fields === "object" &&
    ("vision_bundle_kind" in fields || "vision_bundle_key" in fields);
  return evalStatus === "awaiting_classification" && hasVisionBundle;
}

/** Full pipeline re-run — rejected rows with a stored file only (not duplicate shadows). */
export function canShowReprocessOnBoard(inv: Invoice, column: ApprovalBoardColumnKey): boolean {
  return (
    column === "rejected" &&
    inv.status === "rejected" &&
    canReprocessInvoice(inv.status) &&
    invoiceCanAttemptReprocess(inv)
  );
}

export function reviewQueueCount(invoices: Invoice[]): number {
  return invoices.filter((inv) => columnForInvoice(inv) === "pending").length;
}

export function processingQueueCount(invoices: Invoice[]): number {
  return invoices.filter((inv) => columnForInvoice(inv) === "awaiting").length;
}

export function needsReviewQueueCount(invoices: Invoice[]): number {
  return invoices.filter((inv) => isNeedsReviewInvoice(inv)).length;
}

export function isNeedsReviewInvoice(inv: Invoice): boolean {
  // Posted docs close coding review — never queue them as Needs review.
  if (inv.status === "processed") return false;
  return isNeedsReviewEvaluation(effectiveEvaluationStatus(inv));
}

export function isPendingApprovalInvoice(inv: Invoice): boolean {
  return isPendingApprovalEvaluation(inv.evaluation_status);
}

export function filterNeedsReviewInvoices(invoices: Invoice[]): Invoice[] {
  return invoices.filter((inv) => isNeedsReviewInvoice(inv));
}

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

function localApprovalBoardColumn(inv: Invoice): ApprovalBoardColumnApi {
  if (REJECTED_STATUSES.has(inv.status)) return "rejected";
  if (inv.status === "processed") return "approved";

  const evalStatus = inv.evaluation_status ?? "";
  // Vision understood path: finished at vault → Approved; header gaps → review/processing.
  if (evalStatus === "vision_vaulted") return "approved";
  if (evalStatus === "vision_header_review") {
    return isClassificationConfirmed(inv) ? "processing" : "review";
  }
  // Legacy tag before vision_* evals: soft-bundled docs are vaulted.
  if (evalStatus === "awaiting_classification" && hasVisionBundleSnapshot(inv)) return "approved";

  if (PRE_CLASSIFICATION_EVAL.has(evalStatus)) return "review";

  if (inv.status === "exception" && !isClassificationConfirmed(inv)) return "review";

  if (PIPELINE_STATUSES.has(inv.status)) return "processing";

  if (inv.status === "exception" && (isClassificationConfirmed(inv) || isPendingApprovalInvoice(inv))) {
    return "processing";
  }

  return "review";
}

function apiColumnToKey(column: ApprovalBoardColumnApi | null | undefined): ApprovalBoardColumnKey | null {
  if (!column) return null;
  return API_TO_COLUMN_KEY[column] ?? null;
}

export function columnForInvoice(
  inv: Invoice,
  pinnedRejectedIds?: ReadonlySet<number>,
  processingIds?: ReadonlySet<number>
): ApprovalBoardColumnKey {
  if (processingIds?.has(inv.id)) return "awaiting";
  if (pinnedRejectedIds?.has(inv.id)) return "rejected";

  const fromApi = apiColumnToKey(inv.approval_board_column);
  if (fromApi) return fromApi;

  return apiColumnToKey(localApprovalBoardColumn(inv)) ?? "pending";
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
    // Prefer server pipeline progress; once settled, always take fresh server data
    // instead of a stale optimistic pending row from upload/approve.
    if (PIPELINE_STATUSES.has(row.status)) return row;
    if (local && PIPELINE_STATUSES.has(local.status)) return row;
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

/** Vault-only understood path: system-filed, never human-approved. */
export function isSystemFiledVaultTerminal(
  inv: Pick<Invoice, "evaluation_status">,
): boolean {
  return (inv.evaluation_status ?? "").trim() === "vision_vaulted";
}

export function isPostedApprovedRow(inv: Pick<Invoice, "status">): boolean {
  return inv.status === "processed";
}

export type ApprovedKindFilter = "all" | "posted" | "system_filed";

export function approvedRowDtKey(
  inv: Pick<Invoice, "document_type_code" | "document_heading">,
): string {
  return (inv.document_type_code || inv.document_heading || "").trim();
}

export function systemFiledDocumentTypeOptions(
  rows: readonly Pick<Invoice, "evaluation_status" | "document_type_code" | "document_heading">[],
): string[] {
  const keys = new Set<string>();
  for (const inv of rows) {
    if (!isSystemFiledVaultTerminal(inv)) continue;
    const key = approvedRowDtKey(inv);
    if (key) keys.add(key);
  }
  return [...keys].sort((a, b) => a.localeCompare(b));
}

export function filterApprovedBoardRows(
  rows: Invoice[],
  kind: ApprovedKindFilter,
  documentType?: string | null,
): Invoice[] {
  let out = rows;
  if (kind === "posted") out = out.filter(isPostedApprovedRow);
  if (kind === "system_filed") out = out.filter(isSystemFiledVaultTerminal);
  const dt = (documentType ?? "").trim();
  if (kind === "system_filed" && dt) {
    out = out.filter((inv) => approvedRowDtKey(inv) === dt);
  }
  return out;
}
