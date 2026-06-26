import { api } from "@/api/client";
import type { InvoiceUpdatePayload } from "@/api/types";

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

export function canRejectClaim(status: string): boolean {
  return status === "exception" || status === "processed";
}

/** Processed invoices can re-run the full pipeline; queue items use Approve. */
export function canQueuePipeline(status: string): boolean {
  return status === "processed";
}

export function canRequestInfo(status: string): boolean {
  return !(APPROVAL_QUEUE_STATUSES as readonly string[]).includes(status);
}

export function validateInvoiceFieldsForApproval(fields: {
  vendor?: string | null;
  total?: string | null;
  due_date?: string | null;
}): { ok: true } | { ok: false; message: string } {
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

/** Poll one invoice until it leaves the pipeline (processed / exception / rejected). */
export async function watchInvoiceUntilSettled(
  invoiceId: number,
  refresh: () => Promise<void>,
  timeoutMs = PROCESSING_TIMEOUT_MS
): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    await refresh();
    const inv = await api.getInvoice(invoiceId, { fresh: true });
    if (!PIPELINE_ACTIVE.has(inv.status)) {
      return;
    }
    await new Promise((r) => setTimeout(r, PROCESSING_POLL_MS));
  }
  await refresh();
}

export async function approveAndProcess(
  invoiceId: number,
  refresh: () => Promise<void>,
  pendingEdits?: InvoiceUpdatePayload
): Promise<void> {
  if (pendingEdits) {
    await api.updateInvoice(invoiceId, pendingEdits);
  }
  await api.approve(invoiceId);
  await watchInvoiceUntilSettled(invoiceId, refresh);
}

/** Re-parse a stuck invoice (clears extracted fields, runs pipeline for this row). */
export async function reprocessAndWatch(
  invoiceId: number,
  refresh: () => Promise<void>
): Promise<void> {
  await api.reprocess(invoiceId);
  await watchInvoiceUntilSettled(invoiceId, refresh);
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
