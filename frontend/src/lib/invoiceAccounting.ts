import type { Invoice, JournalEntry, LineItem, PaymentApi } from "@/api/types";
import { isMatchRoute } from "@/lib/documentRowActions";

export type InvoiceAccountingPostingStatus = {
  label: string;
  detail: string;
  tone: "muted" | "pending" | "success" | "error";
};

export type JournalEntryGroup = {
  id: string;
  title: string;
  entries: JournalEntry[];
};

const POSTING_PIPELINE_STATUSES = new Set([
  "journaling",
  "reconciling",
  "processed",
]);

export function invoiceAccountingPostingStatus(
  inv: Pick<
    Invoice,
    "status" | "published_to_ledger" | "current_stage" | "current_stage_state"
  >
): InvoiceAccountingPostingStatus {
  const status = (inv.status ?? "").trim().toLowerCase();
  const stage = (inv.current_stage ?? "").trim();

  if (status === "rejected") {
    return {
      label: "Not posted",
      detail: "Invoice was rejected — no ledger entries.",
      tone: "error",
    };
  }
  if (status === "exception" || status === "duplicate_skipped") {
    return {
      label: "Blocked",
      detail: "Resolve exceptions and approve before accounting can post.",
      tone: "error",
    };
  }
  if (inv.published_to_ledger) {
    return {
      label: "Posted to ledger",
      detail: "Accrual journals are published to the workbook.",
      tone: "success",
    };
  }
  if (status === "processed") {
    return {
      label: "Journals posted",
      detail: "Accrual complete — awaiting ledger export if not yet published.",
      tone: "success",
    };
  }
  if (status === "reconciling") {
    return {
      label: "Reconciling",
      detail: "Daily AP reconciliation is running before final posting.",
      tone: "pending",
    };
  }
  if (status === "journaling") {
    return {
      label: "Posting journals",
      detail: "Generating accrual journal entries for this invoice.",
      tone: "pending",
    };
  }
  if (POSTING_PIPELINE_STATUSES.has(status)) {
    return {
      label: "In progress",
      detail: stage ? `Pipeline stage: ${stage}.` : "Accounting pipeline in progress.",
      tone: "pending",
    };
  }
  return {
    label: "Not yet posted",
    detail: "Approve and process this invoice to generate journal entries.",
    tone: "muted",
  };
}

export function journalEntryKindLabel(kind: string | null | undefined): string {
  switch ((kind ?? "").trim().toLowerCase()) {
    case "invoice_accrual":
      return "Accrual";
    case "payment_settlement":
      return "Payment settlement";
    case "collection_settlement":
      return "Collection settlement";
    case "bank_create":
      return "Bank entry";
    case "bank_transfer":
      return "Bank transfer";
    default:
      return kind?.trim() || "Journal";
  }
}

export function groupJournalEntries(entries: JournalEntry[]): JournalEntryGroup[] {
  if (entries.length === 0) return [];

  const buckets = new Map<string, JournalEntry[]>();
  for (const entry of entries) {
    const kind = (entry.entry_kind ?? "invoice_accrual").trim().toLowerCase();
    const list = buckets.get(kind) ?? [];
    list.push(entry);
    buckets.set(kind, list);
  }

  const order = [
    "invoice_accrual",
    "payment_settlement",
    "collection_settlement",
    "bank_create",
    "bank_transfer",
  ];

  const groups: JournalEntryGroup[] = [];
  for (const kind of order) {
    const rows = buckets.get(kind);
    if (!rows?.length) continue;
    groups.push({
      id: kind,
      title: journalEntryKindLabel(kind),
      entries: rows,
    });
    buckets.delete(kind);
  }

  for (const [kind, rows] of buckets.entries()) {
    groups.push({
      id: kind,
      title: journalEntryKindLabel(kind),
      entries: rows,
    });
  }

  return groups;
}

export function summarizeLineGlCoding(
  lineItems: LineItem[],
  parentLedger: string
): Array<{
  key: string;
  description: string;
  mainGl: string;
  subGl: string;
  source: string | null;
}> {
  return lineItems.map((line, index) => {
    const mainGl =
      line.parent_ledger?.trim() ||
      line.effective_ledger?.trim() ||
      parentLedger.trim() ||
      "—";
    const subGl = line.sub_ledger?.trim() || "—";
    return {
      key: String(line.id ?? index),
      description: line.description?.trim() || `Line ${index + 1}`,
      mainGl,
      subGl,
      source: line.gl_mapping_source?.trim() || null,
    };
  });
}

export function paymentStatusDisplay(payment: PaymentApi | null | undefined): {
  label: string;
  detail: string;
} {
  if (!payment) {
    return {
      label: "Not queued",
      detail: "Payment is created after the invoice is processed.",
    };
  }

  const status = (payment.status ?? "").trim().toLowerCase();
  if (status === "paid") {
    return {
      label: "Paid",
      detail: payment.paid_date
        ? `Paid on ${payment.paid_date}.`
        : "Marked as paid.",
    };
  }
  if (status === "failed") {
    return {
      label: "Failed",
      detail: payment.failure_reason?.trim() || "Payment attempt failed.",
    };
  }
  if (status === "scheduled") {
    return {
      label: "Scheduled",
      detail: payment.scheduled_date
        ? `Scheduled for ${payment.scheduled_date}.`
        : "Scheduled for disbursement.",
    };
  }
  if (status === "awaiting") {
    return { label: "Awaiting approval", detail: "Payment needs approver release." };
  }
  if (status === "queue") {
    return { label: "In queue", detail: "Payment queued for processing." };
  }
  return {
    label: payment.status || "Pending",
    detail: "Payment record exists for this invoice.",
  };
}

export function drawerTabsForInvoice(
  route: string | null | undefined,
  postingApplies: boolean,
  baseTabs: readonly string[] = ["fields", "lines", "po", "tax", "audit", "vault"]
): string[] {
  let tabs = isMatchRoute(route) ? [...baseTabs] : baseTabs.filter((t) => t !== "po");
  if (postingApplies) {
    const taxIndex = tabs.indexOf("tax");
    const insertAt = taxIndex >= 0 ? taxIndex + 1 : tabs.length - 1;
    tabs = [...tabs.slice(0, insertAt), "accounting", ...tabs.slice(insertAt)];
  }
  return tabs;
}
