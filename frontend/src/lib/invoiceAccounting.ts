import type { ChartOfAccountRow, Invoice, JournalEntry, LineItem, PaymentApi } from "@/api/types";
import { exactMainLedgerName } from "@/lib/coaAccountOptions";
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

export type AccountingPipelineLabel = "NA" | "In progress" | "Completed";

export type AccountingPipelineStatus = {
  label: AccountingPipelineLabel;
  tone: "muted" | "pending" | "success";
};

export type AccountingPostingRow = {
  key: string;
  postingDate: string;
  accountCode: string;
  accountName: string;
  ledger?: string;
  subLedger?: string;
  side: "Dr" | "Cr";
  amount: string | null;
};

const EXPENSE_JOURNAL_KINDS = new Set(["invoice_accrual"]);
const PAYMENT_JOURNAL_KINDS = new Set(["payment_settlement", "collection_settlement"]);

function journalKind(entry: JournalEntry): string {
  return (entry.entry_kind ?? "invoice_accrual").trim().toLowerCase();
}

export function filterJournalEntriesByPosting(
  entries: JournalEntry[],
  posting: "expense" | "payment"
): JournalEntry[] {
  const kinds = posting === "expense" ? EXPENSE_JOURNAL_KINDS : PAYMENT_JOURNAL_KINDS;
  return entries.filter((entry) => kinds.has(journalKind(entry)));
}

function journalSide(entry: JournalEntry): "Dr" | "Cr" {
  const type = (entry.entry_type ?? "").trim().toLowerCase();
  if (type === "credit") return "Cr";
  if (type === "debit") return "Dr";
  const debit = Number(entry.debit) || 0;
  const credit = Number(entry.credit) || 0;
  return credit > debit ? "Cr" : "Dr";
}

export function postingRowsFromJournals(
  entries: JournalEntry[],
  fallbackDate: string
): AccountingPostingRow[] {
  if (entries.length === 0) {
    return [
      {
        key: "placeholder-dr",
        postingDate: fallbackDate,
        accountCode: "",
        accountName: "",
        side: "Dr",
        amount: null,
      },
      {
        key: "placeholder-cr",
        postingDate: fallbackDate,
        accountCode: "",
        accountName: "",
        side: "Cr",
        amount: null,
      },
    ];
  }
  return entries.map((entry) => {
    const side = journalSide(entry);
    return {
      key: String(entry.id),
      postingDate: entry.date || fallbackDate,
      accountCode: entry.account_code ?? "",
      accountName: entry.account_name ?? "",
      side,
      amount: side === "Dr" ? entry.debit : entry.credit,
    };
  });
}

export function expensePostingPipelineStatus(
  inv: Pick<Invoice, "status" | "published_to_ledger">,
  expenseEntries: JournalEntry[]
): AccountingPipelineStatus {
  const status = (inv.status ?? "").trim().toLowerCase();
  if (status === "rejected" || status === "exception" || status === "duplicate_skipped") {
    return { label: "NA", tone: "muted" };
  }
  if (inv.published_to_ledger || expenseEntries.length > 0 || status === "processed") {
    return { label: "Completed", tone: "success" };
  }
  if (status === "journaling" || status === "reconciling") {
    return { label: "In progress", tone: "pending" };
  }
  return { label: "NA", tone: "muted" };
}

export function paymentPostingPipelineStatus(
  payment: PaymentApi | null | undefined,
  paymentEntries: JournalEntry[]
): AccountingPipelineStatus {
  if (paymentEntries.length > 0) {
    return { label: "Completed", tone: "success" };
  }
  const status = (payment?.status ?? "").trim().toLowerCase();
  if (status === "paid") {
    return { label: "Completed", tone: "success" };
  }
  if (status === "failed") {
    return { label: "NA", tone: "muted" };
  }
  if (payment && (status === "queue" || status === "awaiting" || status === "scheduled")) {
    return { label: "In progress", tone: "pending" };
  }
  if (payment) {
    return { label: "In progress", tone: "pending" };
  }
  return { label: "NA", tone: "muted" };
}

export function resolveJournalGlSelection(
  entry: Pick<AccountingPostingRow, "accountCode" | "accountName" | "ledger" | "subLedger">,
  accounts: ChartOfAccountRow[]
): { ledger: string; subLedger: string } {
  const seededLedger = entry.ledger?.trim() ?? "";
  const seededSub = entry.subLedger?.trim() ?? "";
  if (seededLedger || seededSub) {
    return { ledger: seededLedger, subLedger: seededSub };
  }

  const code = entry.accountCode.trim();
  const name = entry.accountName.trim();

  for (const row of accounts) {
    for (const sub of row.subLedgers ?? []) {
      const subCode = sub.code.trim();
      if (subCode && (subCode === code || code === `${row.code.trim()}-${subCode}`)) {
        return { ledger: row.name, subLedger: sub.name };
      }
    }
  }

  const nameLower = name.toLowerCase();
  if (nameLower) {
    for (const row of accounts) {
      for (const sub of row.subLedgers ?? []) {
        if (sub.name.trim().toLowerCase() === nameLower) {
          return { ledger: row.name, subLedger: sub.name };
        }
      }
    }
  }

  const byCode = accounts.find((row) => row.code.trim() === code);
  if (byCode) return { ledger: byCode.name, subLedger: "" };

  const byName = exactMainLedgerName(name, accounts);
  if (byName) return { ledger: byName, subLedger: "" };

  if (code.includes("-")) {
    const parentCode = code.split("-")[0]?.trim() ?? "";
    const parent = accounts.find((row) => row.code.trim() === parentCode);
    if (parent) {
      const rest = code.slice(parentCode.length + 1);
      const sub = (parent.subLedgers ?? []).find(
        (row) => row.code.trim() === rest || row.code.trim() === code
      );
      return { ledger: parent.name, subLedger: sub?.name ?? "" };
    }
  }

  return { ledger: name || code, subLedger: "" };
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
  baseTabs: readonly string[] = ["fields", "lines", "po", "audit", "vault"]
): string[] {
  let tabs = isMatchRoute(route) ? [...baseTabs] : baseTabs.filter((t) => t !== "po");
  if (postingApplies) {
    const after = tabs.includes("po") ? "po" : "lines";
    const insertAt = Math.max(tabs.indexOf(after), 0) + 1;
    tabs = [...tabs.slice(0, insertAt), "accounting", ...tabs.slice(insertAt)];
  }
  return tabs;
}
