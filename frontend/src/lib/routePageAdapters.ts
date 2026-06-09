import type { Invoice } from "@/api/types";
import type { EmployeeMaster, TeamExpenseRule } from "@/lib/v4RuleBookTypes";
import type {
  ExpenseBudget,
  ExpenseCategoryPolicy,
  ExpenseClaim,
  ExpenseState,
} from "@/lib/v4MockData";

function parseAmount(value: string | null | undefined): number {
  if (value == null || value === "") return 0;
  const n = parseFloat(value);
  return Number.isNaN(n) ? 0 : n;
}

function formatTs(iso: string | null | undefined): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString("en-AU", {
      day: "2-digit",
      month: "short",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

function inferClaimChannel(sender: string | null): string {
  if (!sender?.trim()) return "Web";
  if (sender.includes("@")) return "Web";
  return "Mobile";
}

function inferSubmitter(inv: Invoice): string {
  const sender = inv.email_sender?.trim();
  if (sender?.includes("@")) {
    const local = sender.split("@")[0] ?? sender;
    return local.replace(/[._]/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
  }
  if (sender) return sender;
  return inv.vendor?.trim() || "Unknown submitter";
}

export function invoiceToExpenseState(inv: Invoice): ExpenseState {
  if (inv.status === "rejected") return "Rejected";
  if (inv.status === "processed") return "Posted to Ledger";
  if (
    inv.status === "exception" ||
    inv.evaluation_status === "needs_review" ||
    inv.evaluation_status === "pending_vendor"
  ) {
    return "In Review";
  }
  if (inv.status === "validating" || inv.status === "mapping" || inv.status === "journaling") {
    return "In Review";
  }
  return "New";
}

export function invoiceToTeamClaim(inv: Invoice): ExpenseClaim {
  const amount = parseAmount(inv.total);
  const gst = parseAmount(inv.gst);
  return {
    id: String(inv.id),
    submitter: inferSubmitter(inv),
    channel: inferClaimChannel(inv.email_sender),
    category: inv.account_name ?? "Uncategorised",
    amount,
    gst,
    date: inv.invoice_date ?? "—",
    submittedTs: formatTs(inv.created_at),
    state: invoiceToExpenseState(inv),
    purpose: inv.invoice_no ? `Claim ${inv.invoice_no}` : "Team expense claim",
    projectTag: inv.cost_centre ?? "—",
    merchant: inv.vendor ?? "—",
    budgetGroup: inv.account_name ?? "Team",
    approvers: [],
  };
}

export function employeeBudgetRows(employees: EmployeeMaster[]): ExpenseBudget[] {
  const rows: ExpenseBudget[] = [];
  for (const emp of employees) {
    if (emp.budget.monthly > 0) {
      rows.push({
        category: "All categories",
        owner: emp.name,
        period: "Monthly",
        monthlyBudget: emp.budget.monthly,
        used: emp.mtdSpent,
      });
    }
    for (const cat of emp.budget.categories) {
      rows.push({
        category: cat.ledger,
        owner: emp.name,
        period: "Monthly cap",
        monthlyBudget: cat.cap,
        used: Math.min(emp.mtdSpent, cat.cap),
      });
    }
  }
  return rows;
}

export function teamRulesToCategories(rules: TeamExpenseRule[]): ExpenseCategoryPolicy[] {
  return rules
    .filter((rule) => rule.enabled)
    .map((rule) => ({
      category: rule.name,
      glAccount: rule.postTo.ledger,
      requiresReceiptOver: rule.policy.receiptThreshold,
      autoApproveUnder: rule.policy.autoApproveBelow,
      policyNote: rule.policy.requireReceipt
        ? "Receipt required when amount exceeds threshold."
        : "Receipt optional for this category.",
    }));
}

export function purchaseKpisFromInvoices(invoices: Invoice[]) {
  const withPo = invoices.filter((inv) => Boolean(inv.po_reference?.trim()));
  const pendingReview = invoices.filter(
    (inv) =>
      inv.evaluation_status === "needs_review" ||
      inv.evaluation_status === "pending_vendor" ||
      inv.status === "exception"
  );
  const processed = invoices.filter((inv) => inv.status === "processed");
  const open = invoices.filter((inv) => inv.status !== "processed" && inv.status !== "rejected");
  const matchPct =
    invoices.length > 0 ? Math.round((processed.length / invoices.length) * 100) : 0;

  return {
    openPos: open.length,
    pendingGrn: invoices.filter((inv) => !inv.po_reference?.trim()).length,
    matchPct,
    variancesAwaiting: pendingReview.length,
    withPoCount: withPo.length,
  };
}

export function payablesKpis(invoices: Invoice[]) {
  const now = new Date();
  const total = invoices.reduce((sum, inv) => sum + parseAmount(inv.total), 0);
  const overdue = invoices.filter((inv) => {
    if (!inv.due_date) return false;
    return new Date(inv.due_date) < now;
  }).length;
  const dueSoon = invoices.filter((inv) => {
    if (!inv.due_date) return false;
    const due = new Date(inv.due_date);
    const days = (due.getTime() - now.getTime()) / (1000 * 60 * 60 * 24);
    return days >= 0 && days <= 7;
  }).length;
  return { count: invoices.length, total, overdue, dueSoon };
}
