import { api } from "@/api/client";

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

export function canRequestInfo(status: string): boolean {
  return !(APPROVAL_QUEUE_STATUSES as readonly string[]).includes(status);
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
    const inv = await api.getInvoice(invoiceId);
    if (!PIPELINE_ACTIVE.has(inv.status)) {
      return;
    }
    await new Promise((r) => setTimeout(r, PROCESSING_POLL_MS));
  }
  await refresh();
}

export async function approveAndProcess(
  invoiceId: number,
  refresh: () => Promise<void>
): Promise<void> {
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
