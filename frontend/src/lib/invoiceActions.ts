import { api } from "@/api/client";
import type { InvoiceDetails, InvoiceUpdatePayload, PaymentApi } from "@/api/types";
import {
  validateCompulsoryFieldsForApproval,
} from "@/lib/documentCompulsoryFields";

export const APPROVAL_QUEUE_STATUSES = ["exception", "duplicate_skipped", "rejected"] as const;

export const PIPELINE_STATUSES = [
  "pending",
  "parsing",
  "validating",
  "mapping",
  "journaling",
  "reconciling",
] as const;

const PROCESSING_POLL_MS = 2_000;
const PROCESSING_TIMEOUT_MS = 90_000;

const PIPELINE_ACTIVE = new Set<string>(PIPELINE_STATUSES);

export function canApproveClaim(status: string): boolean {
  return (APPROVAL_QUEUE_STATUSES as readonly string[]).includes(status);
}

/** Approve from drawer — rejected/duplicate rows use Reprocess only. */
export function canApproveFromDrawer(status: string): boolean {
  return (
    canApproveClaim(status) && status !== "rejected" && status !== "duplicate_skipped"
  );
}

export function canRejectClaim(status: string): boolean {
  return status === "exception" || status === "processed";
}

/** Processed invoices can re-run the full pipeline; queue items use Approve. */
export function canQueuePipeline(status: string): boolean {
  return status === "processed";
}

/** Matches POST /api/invoices/{id}/reprocess allowed statuses. */
export function canReprocessInvoice(status: string): boolean {
  return (
    status === "exception" ||
    status === "duplicate_skipped" ||
    status === "processed" ||
    status === "rejected"
  );
}

export function canRequestInfo(status: string): boolean {
  return !(APPROVAL_QUEUE_STATUSES as readonly string[]).includes(status);
}

export function validateInvoiceFieldsForApproval(
  fields: {
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
  },
  compulsoryFields?: string[]
): { ok: true } | { ok: false; message: string } {
  if (compulsoryFields?.length) {
    return validateCompulsoryFieldsForApproval(fields, compulsoryFields);
  }
  const missing: string[] = [];
  if (!fields.vendor?.trim()) missing.push("vendor");
  const total = fields.total?.trim();
  if (!total || Number.isNaN(Number(total)) || Number(total) <= 0) missing.push("total");
  if (!fields.due_date?.trim()) missing.push("due date");
  if (missing.length) {
    return {
      ok: false,
      message: `Cannot approve: missing required field(s): ${missing.join(", ")}. Save corrections before approving.`,
    };
  }
  return { ok: true };
}

export function invoiceFieldsFromDetails(inv: {
  vendor?: string | null;
  total?: string | null;
  due_date?: string | null;
}): {
  vendor: string | null;
  total: string | null;
  due_date: string | null;
} {
  return {
    vendor: inv.vendor ?? null,
    total: inv.total ?? null,
    due_date: inv.due_date ?? null,
  };
}

function approvalFailureMessage(inv: InvoiceDetails): string {
  if (inv.status === "exception") {
    if (inv.evaluation_status === "awaiting_po") {
      return "Approval blocked: a matching purchase order is required for this document.";
    }
    if (inv.evaluation_status === "pending_vendor") {
      return "Approval blocked: register the vendor in Vendors → Pending vendor registration, then approve again.";
    }
    if (inv.evaluation_status === "needs_review") {
      return "Approval blocked: document still requires review after processing.";
    }
    const failed = inv.validation_results?.find((row) => !row.passed && !row.skipped);
    if (failed?.message) {
      return `Approval blocked: ${failed.message}`;
    }
    return "Approval did not complete — document returned to review. Check validation or routing rules.";
  }
  if (PIPELINE_ACTIVE.has(inv.status)) {
    return `Approval did not complete — processing still ${inv.status}. Wait or use Reprocess from the drawer.`;
  }
  return `Approval did not complete (status: ${inv.status}).`;
}

export async function watchProcessingUntilIdle(
  refresh: () => Promise<void>,
  timeoutMs = PROCESSING_TIMEOUT_MS
): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  let sawRunning = false;
  while (Date.now() < deadline) {
    await refresh();
    const status = await api.getProcessingStatus();
    if (status.state === "running" || status.active_tasks > 0) {
      sawRunning = true;
    }
    if (sawRunning && status.state === "idle" && status.active_tasks === 0) {
      await refresh();
      return;
    }
    if (!sawRunning && status.state === "idle" && status.active_tasks === 0) {
      await new Promise((r) => setTimeout(r, PROCESSING_POLL_MS));
      await refresh();
      return;
    }
    await new Promise((r) => setTimeout(r, PROCESSING_POLL_MS));
  }
  await refresh();
}

export type WatchInvoiceUntilSettledOptions = {
  /** Wait for a pipeline status before treating exception/rejected/processed as settled. */
  requirePipelineObserved?: boolean;
};

/** Poll one invoice until it leaves the pipeline (processed / exception / rejected). */
export async function watchInvoiceUntilSettled(
  invoiceId: number,
  refresh: () => Promise<void>,
  timeoutMs = PROCESSING_TIMEOUT_MS,
  options?: WatchInvoiceUntilSettledOptions
): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  let sawPipeline = !options?.requirePipelineObserved;
  while (Date.now() < deadline) {
    await refresh();
    const inv = await api.getInvoice(invoiceId, { fresh: true });
    if (PIPELINE_ACTIVE.has(inv.status)) {
      sawPipeline = true;
    }
    if (sawPipeline && !PIPELINE_ACTIVE.has(inv.status)) {
      return;
    }
    await new Promise((r) => setTimeout(r, PROCESSING_POLL_MS));
  }
  await refresh();
}

/** True when a stored path exists or the API verified the blob (reprocess can repair paths). */
export function invoiceCanAttemptReprocess(inv: {
  has_stored_file?: boolean;
  raw_file_path?: string | null;
}): boolean {
  return Boolean(inv.has_stored_file || inv.raw_file_path?.trim());
}

export type ApproveAndProcessResult = {
  invoice: InvoiceDetails;
  payment?: PaymentApi;
};

export async function approveAndProcess(
  invoiceId: number,
  refresh: () => Promise<void>,
  pendingEdits?: InvoiceUpdatePayload
): Promise<ApproveAndProcessResult> {
  if (pendingEdits) {
    await api.updateInvoice(invoiceId, pendingEdits);
  }
  await api.approve(invoiceId);
  await watchInvoiceUntilSettled(invoiceId, refresh, PROCESSING_TIMEOUT_MS, {
    requirePipelineObserved: true,
  });
  const invoice = await api.getInvoice(invoiceId, { fresh: true });

  if (invoice.status !== "processed") {
    throw new Error(approvalFailureMessage(invoice));
  }

  const payable =
    Boolean(invoice.vendor?.trim()) &&
    Boolean(invoice.total?.trim()) &&
    Boolean(invoice.due_date?.trim()) &&
    Number(invoice.total) > 0;

  let payment: PaymentApi | undefined;
  if (payable) {
    const payments = await api.listPayments(undefined, { fresh: true });
    payment = payments.find((row) => row.invoice_id === invoiceId);
    if (!payment) {
      throw new Error(
        "Invoice processed but no payment row was created. Confirm this is a supplier invoice with vendor, total, and due date."
      );
    }
  }

  return { invoice, payment };
}

/** Re-parse a stuck invoice (clears extracted fields, runs pipeline for this row). */
export async function reprocessAndWatch(
  invoiceId: number,
  refresh: () => Promise<void>,
  options?: { hadManualEdits?: boolean }
): Promise<void> {
  if (options?.hadManualEdits) {
    const proceed = window.confirm(
      "Reprocess re-runs OCR extraction and may still return to review. " +
        "To process with your saved corrections, use Approve instead. Continue reprocess?"
    );
    if (!proceed) return;
  }
  const queued = await api.reprocess(invoiceId);
  if (!PIPELINE_ACTIVE.has(queued.status)) {
    throw new Error(
      `Reprocess did not queue the pipeline (status: ${queued.status}). Check the stored file and try again.`
    );
  }
  await watchInvoiceUntilSettled(invoiceId, refresh, PROCESSING_TIMEOUT_MS, {
    requirePipelineObserved: true,
  });
}
