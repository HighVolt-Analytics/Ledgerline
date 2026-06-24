import type { AuditLogEntry, InvoiceDetails } from "@/api/types";
import {
  invoiceFailedValidations,
  invoiceSourceKind,
  invoiceSourceLabel,
  invoiceValidationConfidence,
} from "@/lib/invoice";
import { invId } from "@/lib/format";

export type PipelineAuditStep = {
  stage: string;
  when: string;
  detail: string;
  state: "done" | "pending" | "fail" | "skipped";
};

function relativeTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

function latestEventLog(logs: AuditLogEntry[], events: string[]): AuditLogEntry | undefined {
  let best: AuditLogEntry | undefined;
  for (const entry of logs) {
    if (!events.includes(entry.event)) continue;
    if (!best || new Date(entry.created_at).getTime() > new Date(best.created_at).getTime()) {
      best = entry;
    }
  }
  return best;
}

function latestLog(logs: AuditLogEntry[], ...events: string[]): AuditLogEntry | undefined {
  return latestEventLog(logs, events);
}

function isPublishedFromAuditLogs(logs: AuditLogEntry[]): boolean {
  const latestPublish = Math.max(
    0,
    ...logs.filter((l) => l.event === "invoice_published_to_ledger").map((l) => l.id)
  );
  if (latestPublish === 0) return false;
  const latestProcessed = Math.max(
    0,
    ...logs
      .filter(
        (l) => l.event === "invoice_processed" || l.event === "purchase_document_processed"
      )
      .map((l) => l.id)
  );
  return latestPublish > latestProcessed;
}

function isAfter(entry: AuditLogEntry | undefined, pivot: AuditLogEntry | undefined): boolean {
  if (!entry) return false;
  if (!pivot) return true;
  return new Date(entry.created_at).getTime() >= new Date(pivot.created_at).getTime();
}

function validationDetail(
  inv: InvoiceDetails,
  logs: AuditLogEntry[]
): { text: string; state: "done" | "fail" | "pending" } {
  const failed = invoiceFailedValidations(inv);
  if (failed.length) {
    return {
      text: failed.map((r) => r.message).slice(0, 2).join("; ") || "Failed checks",
      state: "fail",
    };
  }
  if (inv.validation_results?.length) {
    return { text: "Passed", state: "done" };
  }

  const latestApprove = latestEventLog(logs, ["invoice_approved"]);
  const latestPassed = latestEventLog(logs, ["validation_passed"]);
  const latestFailed = latestEventLog(logs, ["validation_failed"]);
  const latestHold = latestEventLog(logs, ["vendor_registration_hold"]);

  if (latestHold && isAfter(latestHold, latestApprove) && inv.status === "exception") {
    return { text: "Vendor registration hold", state: "fail" };
  }

  if (latestPassed && latestFailed) {
    const passedNewer =
      new Date(latestPassed.created_at).getTime() > new Date(latestFailed.created_at).getTime();
    if (passedNewer && isAfter(latestPassed, latestApprove)) {
      return { text: "Passed", state: "done" };
    }
    if (!passedNewer && isAfter(latestFailed, latestApprove)) {
      return { text: "Failed checks", state: "fail" };
    }
  } else if (latestPassed && isAfter(latestPassed, latestApprove)) {
    return { text: "Passed", state: "done" };
  } else if (latestFailed && isAfter(latestFailed, latestApprove)) {
    return { text: "Failed checks", state: "fail" };
  }

  if (
    inv.status === "pending" ||
    inv.status === "parsing" ||
    inv.status === "validating" ||
    inv.status === "mapping" ||
    inv.status === "journaling" ||
    inv.status === "reconciling"
  ) {
    return { text: "In progress", state: "pending" };
  }

  if (inv.status === "exception") {
    return { text: "Routed to review", state: "fail" };
  }
  return { text: "Pending", state: "pending" };
}

function stageIndex(status: string): number {
  switch (status) {
    case "pending":
      return 0;
    case "parsing":
      return 1;
    case "validating":
      return 2;
    case "mapping":
    case "journaling":
    case "reconciling":
      return 3;
    case "processed":
      return 5;
    case "exception":
      return 2;
    case "rejected":
    case "duplicate_skipped":
      return 0;
    default:
      return 0;
  }
}

/** Six-step pipeline narrative aligned with Ledgerline v3. */
export function buildPipelineAuditSteps(
  inv: InvoiceDetails,
  logs: AuditLogEntry[]
): PipelineAuditStep[] {
  const receivedLog = latestLog(logs, "email_ingested", "invoice_uploaded", "invoice_file_attached");
  const parsedLog = latestLog(logs, "parse_completed", "invoice_parsed", "parsing_failed");
  const validatedLog = latestLog(logs, "validation_passed", "validation_failed");
  const mappedLog = latestLog(logs, "mapping_applied");
  const approvedLog = latestLog(logs, "invoice_approved", "approval_requested");
  const publishedLog = latestLog(logs, "invoice_published_to_ledger", "invoice_processed");

  const source = invoiceSourceKind(inv);
  const sourceLabel = invoiceSourceLabel(source);
  const receivedVia = inv.email_sender ?? sourceLabel;
  const receivedWhen = relativeTime(receivedLog?.created_at ?? inv.created_at);

  const parseConfidence =
    (parsedLog?.detail?.confidence as number | undefined) ??
    invoiceValidationConfidence(inv) ??
    null;
  const parsedWhen = parsedLog
    ? relativeTime(parsedLog.created_at)
    : stageIndex(inv.status) >= 1
      ? relativeTime(inv.created_at)
      : "—";
  const parsedDetail =
    parsedLog?.event === "parsing_failed"
      ? "Could not read document"
      : parseConfidence != null
        ? `${parseConfidence}% confidence`
        : stageIndex(inv.status) >= 1
          ? "OCR complete"
          : "Pending";

  const validation = validationDetail(inv, logs);
  const validatedWhen = validatedLog
    ? relativeTime(validatedLog.created_at)
    : stageIndex(inv.status) >= 2
      ? relativeTime(parsedLog?.created_at ?? inv.created_at)
      : "—";

  const account =
    inv.account_name ??
    (stageIndex(inv.status) >= 3 ? "Suspense Account" : "—");
  const mappedSuspense = account.toLowerCase().includes("suspense");
  const mappedWhen = mappedLog
    ? relativeTime(mappedLog.created_at)
    : stageIndex(inv.status) >= 3
      ? relativeTime(validatedLog?.created_at ?? inv.created_at)
      : "—";

  let approvedDetail = "Pending policy";
  let approvedState: PipelineAuditStep["state"] = "pending";
  let approvedWhen = "—";
  if (approvedLog) {
    approvedWhen = relativeTime(approvedLog.created_at);
    const actor =
      typeof approvedLog.detail?.actor_name === "string"
        ? approvedLog.detail.actor_name
        : null;
    if (inv.status === "processed") {
      approvedDetail = actor ? `${actor} · Approved` : "Approved for processing";
      approvedState = "done";
    } else if (
      inv.status === "pending" ||
      inv.status === "parsing" ||
      inv.status === "validating" ||
      inv.status === "mapping" ||
      inv.status === "journaling" ||
      inv.status === "reconciling"
    ) {
      approvedDetail = actor ? `${actor} · Processing` : "Approved · processing";
      approvedState = "pending";
    } else if (inv.status === "exception") {
      approvedDetail = actor ? `${actor} · Reprocess needed` : "Approved · reprocess needed";
      approvedState = "pending";
    } else {
      approvedDetail = actor ? `${actor} · Approved` : "Approved for processing";
      approvedState = "done";
    }
  } else if (inv.status === "processed") {
    approvedWhen = relativeTime(publishedLog?.created_at ?? inv.created_at);
    approvedDetail = "Within policy";
    approvedState = "done";
  } else if (inv.status === "exception") {
    approvedDetail = "Awaiting review";
    approvedState = "pending";
  }

  let publishedDetail = "Pending";
  let publishedState: PipelineAuditStep["state"] = "pending";
  let publishedWhen = "—";
  const ledgerPublished =
    inv.published_to_ledger ?? isPublishedFromAuditLogs(logs);
  if (ledgerPublished) {
    const publishLog = latestLog(logs, "invoice_published_to_ledger");
    publishedWhen = relativeTime(publishLog?.created_at ?? inv.created_at);
    publishedDetail = inv.invoice_no ?? invId(inv.id);
    publishedState = "done";
  } else if (inv.status === "processed") {
    publishedWhen = relativeTime(publishedLog?.created_at ?? inv.created_at);
    publishedDetail = `${invId(inv.id)} · ready to publish`;
    publishedState = "pending";
  }

  if (inv.status === "rejected") {
    return [
      {
        stage: "Received",
        when: receivedWhen,
        detail: `${sourceLabel} · ${receivedVia}`,
        state: "done",
      },
      {
        stage: "Rejected",
        when: relativeTime(latestLog(logs, "invoice_rejected")?.created_at),
        detail: "Document rejected",
        state: "fail",
      },
    ];
  }

  return [
    {
      stage: "Received",
      when: receivedWhen,
      detail: `${sourceLabel} · ${receivedVia}`,
      state: "done",
    },
    {
      stage: "Parsed",
      when: parsedWhen,
      detail: parsedLog?.event === "parsing_failed" ? parsedDetail : `OCR complete · ${parsedDetail}`,
      state:
        parsedLog?.event === "parsing_failed"
          ? "fail"
          : stageIndex(inv.status) >= 1
            ? "done"
            : "pending",
    },
    {
      stage: "Validated",
      when: validatedWhen,
      detail: `Tax & totals checked · ${validation.text}`,
      state: validation.state,
    },
    {
      stage: "Mapped",
      when: mappedWhen,
      detail: `Rule book applied · ${account}`,
      state: mappedSuspense && inv.status === "exception" ? "fail" : stageIndex(inv.status) >= 3 ? "done" : "pending",
    },
    {
      stage: "Approved",
      when: approvedWhen,
      detail: approvedDetail,
      state: approvedState,
    },
    {
      stage: "Published",
      when: publishedWhen,
      detail: `Ledger · ${publishedDetail}`,
      state: publishedState,
    },
  ];
}
