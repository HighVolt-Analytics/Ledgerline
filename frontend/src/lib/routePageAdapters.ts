import type { Invoice } from "@/api/types";
import { documentDisplayRef } from "@/lib/format";
import { invoiceFailedValidations } from "@/lib/invoice";
import { sortInvoicesNewestFirst } from "@/lib/invoices";
import { purchaseActionRequiredInvoices } from "@/lib/purchaseRegisterQueue";
import {
  isDueWithinDays,
  isOverdueDate,
} from "@/lib/tenantTime";
import type {
  EmployeeMaster,
  ExpenseRule,
  PurchaseRule,
  TeamExpenseRule,
} from "@/lib/v4RuleBookTypes";
import type {
  ExpenseBudget,
  ExpenseCategoryPolicy,
  ExpenseClaim,
  ExpenseState,
  MatchStatus,
  PaymentRecord,
  PurchaseOrder,
  ThreeWayMatch,
} from "@/lib/v4MockData";
import type { PaymentApi, PurchaseOrderApi } from "@/api/types";

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

function inferClaimChannel(sender: string | null, captureSource?: string | null): string {
  const source = captureSource?.trim().toLowerCase();
  if (source === "whatsapp") return "WhatsApp";
  if (source === "viber") return "Viber";
  if (!sender?.trim()) return "Upload";
  if (sender.includes("@")) return "Email";
  const digits = sender.replace(/\D/g, "");
  if (digits.length >= 8) return "Mobile";
  return "Upload";
}

export type TeamExpenseChannelChip = {
  id: string;
  name: string;
  detail: string;
};

const CHANNEL_META: Record<string, TeamExpenseChannelChip> = {
  email: { id: "em", name: "Email", detail: "Ingestion rules (accept/skip only)" },
  em: { id: "em", name: "Email", detail: "Ingestion rules (accept/skip only)" },
  mob: { id: "mob", name: "Mobile", detail: "SMS / messaging capture" },
  mobile: { id: "mob", name: "Mobile", detail: "SMS / messaging capture" },
  wa: { id: "wa", name: "WhatsApp", detail: "Mobile messaging channel" },
  whatsapp: { id: "wa", name: "WhatsApp", detail: "Mobile messaging channel" },
  viber: { id: "vb", name: "Viber", detail: "Mobile messaging channel" },
  vb: { id: "vb", name: "Viber", detail: "Mobile messaging channel" },
  any: { id: "any", name: "All channels", detail: "Any submission channel" },
};

export function teamExpenseChannelsFromRules(rules: TeamExpenseRule[]): TeamExpenseChannelChip[] {
  const seen = new Set<string>();
  const out: TeamExpenseChannelChip[] = [];
  for (const rule of rules) {
    if (!rule.enabled) continue;
    const raw = (rule.matchOn.channelEquals ?? "any").trim().toLowerCase();
    const key = raw === "" ? "any" : raw;
    const meta = CHANNEL_META[key] ?? CHANNEL_META.any;
    if (seen.has(meta.id)) continue;
    seen.add(meta.id);
    out.push(meta);
  }
  if (out.length === 0) {
    out.push(CHANNEL_META.any);
  }
  return out;
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

const PIPELINE_IN_REVIEW = new Set([
  "pending",
  "parsing",
  "validating",
  "mapping",
  "journaling",
  "reconciling",
]);

export function invoiceToExpenseState(inv: Invoice): ExpenseState {
  if (inv.status === "rejected") return "Rejected";
  if (inv.status === "processed") {
    return inv.published_to_ledger ? "Posted to Ledger" : "Approved";
  }
  if (PIPELINE_IN_REVIEW.has(inv.status)) return "In Review";
  if (
    inv.status === "exception" ||
    inv.evaluation_status === "needs_review" ||
    inv.evaluation_status === "pending_vendor" ||
    inv.evaluation_status === "unmatched_expense_vendor"
  ) {
    return "In Review";
  }
  return "New";
}

export function invoiceToBusinessExpense(inv: Invoice): ExpenseClaim {
  const claim = invoiceToTeamClaim(inv);
  return {
    ...claim,
    submitter: inv.vendor?.trim() || claim.submitter,
    purpose: inv.invoice_no ? `Expense ${inv.invoice_no}` : "Business expense",
    budgetGroup: inv.account_name ?? "Operating",
    channel: inferClaimChannel(inv.email_sender, inv.capture_source),
  };
}

export function invoiceToTeamClaim(inv: Invoice): ExpenseClaim {
  const amount = parseAmount(inv.total);
  const gst = parseAmount(inv.gst);
  return {
    id: String(inv.id),
    documentRef: documentDisplayRef(inv),
    submitter: inferSubmitter(inv),
    channel: inferClaimChannel(inv.email_sender, inv.capture_source),
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

export type RecentClaimValidation = {
  id: string;
  employee: string;
  amount: number;
  channel: string;
  outcome: "approved" | "warning" | "rejected";
  reason: string;
};

function normalizePhone(value: string): string {
  return value.replace(/\D/g, "");
}

function matchEmployeeForSender(
  sender: string | null | undefined,
  employees: EmployeeMaster[]
): EmployeeMaster | undefined {
  if (!sender?.trim()) return undefined;
  const key = sender.trim().toLowerCase();
  const phone = normalizePhone(sender);
  for (const emp of employees) {
    const email = (emp.email ?? "").trim().toLowerCase();
    if (email && email === key) return emp;
    for (const field of [emp.whatsappNumber, emp.viberNumber ?? ""]) {
      const digits = normalizePhone(field);
      if (digits && phone && digits === phone) return emp;
    }
  }
  return undefined;
}

function teamValidationRules(inv: Invoice) {
  return (inv.validation_results ?? []).filter((r) => r.rule.startsWith("VR-TE"));
}

function claimValidationReason(inv: Invoice): string {
  const teamRules = teamValidationRules(inv);
  const failed = teamRules.filter((r) => !r.skipped && !r.passed);
  if (failed.length) return failed[0]!.message;

  const allFailed = invoiceFailedValidations(inv);
  if (allFailed.length) return allFailed[0]!.message;

  const passed = teamRules.filter((r) => !r.skipped && r.passed);
  if (passed.length) return passed[passed.length - 1]!.message;

  if (inv.status === "processed") return "Posted to ledger";
  if (inv.status === "rejected") return "Claim rejected";
  if (inv.evaluation_status === "needs_review") return "Needs manual review";
  if (inv.status === "exception") return "Validation exception";
  return "Pending validation";
}

function claimValidationOutcome(inv: Invoice): RecentClaimValidation["outcome"] {
  if (inv.status === "rejected" || inv.status === "exception") return "rejected";
  if (inv.status === "processed") return "approved";

  const failed = invoiceFailedValidations(inv);
  if (failed.some((r) => r.rule.startsWith("VR-TE"))) return "rejected";
  if (failed.length) return "warning";

  if (
    inv.evaluation_status === "needs_review" ||
    inv.evaluation_status === "pending_vendor" ||
    PIPELINE_IN_REVIEW.has(inv.status)
  ) {
    return "warning";
  }

  return "approved";
}

export function invoiceToRecentClaimValidation(
  inv: Invoice,
  employees: EmployeeMaster[] = []
): RecentClaimValidation {
  const matched = matchEmployeeForSender(inv.email_sender, employees);
  const claim = invoiceToTeamClaim(inv);
  return {
    id: String(inv.id),
    employee: matched?.name ?? claim.submitter,
    amount: claim.amount,
    channel: claim.channel,
    outcome: claimValidationOutcome(inv),
    reason: claimValidationReason(inv),
  };
}

export function recentClaimValidationsFromInvoices(
  invoices: Invoice[],
  employees: EmployeeMaster[],
  limit = 10
): RecentClaimValidation[] {
  return sortInvoicesNewestFirst(invoices)
    .slice(0, limit)
    .map((inv) => invoiceToRecentClaimValidation(inv, employees));
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

export function expenseRulesToCategories(rules: ExpenseRule[]): ExpenseCategoryPolicy[] {
  return rules
    .filter((rule) => rule.enabled)
    .map((rule) => ({
      category: rule.name,
      glAccount: rule.postTo.ledger,
      requiresReceiptOver: 0,
      autoApproveUnder: 0,
      policyNote: "Matched by expense rule book criteria.",
    }));
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

function formatPurchaseMatchCriteria(matchOn: PurchaseRule["matchOn"]): string {
  const parts: string[] = [];
  if (matchOn.poPrefix) parts.push(`PO prefix ${matchOn.poPrefix}`);
  if (matchOn.poRegex) parts.push(`PO regex ${matchOn.poRegex}`);
  if (matchOn.vendorContains) parts.push(`vendor contains "${matchOn.vendorContains}"`);
  if (matchOn.grnLinkedToPo) parts.push("GRN linked to PO");
  if (matchOn.invoiceReferencesPo) parts.push("invoice references PO");
  return parts.length ? parts.join(" · ") : "Purchase rule criteria";
}

export function purchaseRulesToCategories(rules: PurchaseRule[]): ExpenseCategoryPolicy[] {
  return rules
    .filter((rule) => rule.enabled)
    .map((rule) => ({
      category: rule.name,
      glAccount: rule.postTo.ledger,
      requiresReceiptOver: 0,
      autoApproveUnder: 0,
      policyNote: formatPurchaseMatchCriteria(rule.matchOn),
    }));
}

export function purchaseKpisFromRegister(rows: PurchaseOrderApi[], routed: Invoice[]) {
  const openPos = rows.filter((r) => r.match.status !== "3-Way Match").length;
  const missingGrn = rows.filter((r) => r.match.status === "No GRN").length;
  const matched = rows.filter((r) => r.match.status === "3-Way Match").length;
  const matchPct = rows.length > 0 ? Math.round((matched / rows.length) * 100) : 0;
  const variancesAwaiting = rows.filter((r) =>
    purchaseNeedsVarianceApproval(r.match.status, r.variance_approved)
  ).length;
  const needsAction = purchaseActionRequiredInvoices(routed, rows).length;
  const withoutPoRef = routed.filter((inv) => !inv.po_reference?.trim()).length;

  return {
    openPos,
    missingGrn,
    matchPct,
    variancesAwaiting,
    needsAction,
    withoutPoRef,
  };
}

export function purchaseNeedsVarianceApproval(
  matchStatus: string,
  varianceApproved: boolean
): boolean {
  if (varianceApproved) return false;
  return (
    matchStatus === "Routed for Approval" ||
    matchStatus === "Price Variance" ||
    matchStatus === "Qty Variance"
  );
}

export function apiPurchaseToRow(row: PurchaseOrderApi): {
  purchaseId: number;
  invoiceId: number | null;
  po: PurchaseOrder;
  m: ThreeWayMatch;
  threeWayAuditStatus: PurchaseOrderApi["three_way_match_status"];
} {
  const po: PurchaseOrder = {
    id: row.po_number,
    vendor: row.vendor ?? "—",
    date: row.po_date ?? "—",
    requestor: row.requestor ?? "—",
    item: row.item ?? "—",
    poQty: row.po_qty,
    poUnitPrice: row.po_unit_price,
    grnQty: row.grn_qty,
    grnDate: row.grn_date,
    grnReceiver: row.grn_receiver,
    grnCondition: row.grn_condition,
    invoiceNo: row.invoice_no ?? "—",
    invoiceQty: row.invoice_qty,
    invoiceUnitPrice: row.invoice_unit_price,
    gstRate: row.gst_rate,
    routedForApproval: purchaseNeedsVarianceApproval(row.match.status, row.variance_approved),
    matchedRuleName: row.matched_rule_name ?? null,
    matchedGl: row.matched_gl ?? null,
    evaluationStatus: row.evaluation_status ?? null,
    matchedRuleIds: row.matched_rule_ids ?? [],
    poDocumentId: row.po_document_id ?? null,
    grnDocumentId: row.grn_document_id ?? null,
  };
  const m: ThreeWayMatch = {
    status: row.match.status as MatchStatus,
    qtyVarianceValue: row.match.qty_variance_value,
    priceVarianceValue: row.match.price_variance_value,
    totalDeviation: row.match.total_deviation,
    poValue: row.match.po_value,
    invoiceValue: row.match.invoice_value,
    invoiceGst: row.match.invoice_gst,
    invoiceTotal: row.match.invoice_total,
  };
  return {
    purchaseId: row.id,
    invoiceId: row.invoice_id,
    po,
    m,
    threeWayAuditStatus: row.three_way_match_status ?? null,
  };
}

export function apiPaymentToRecord(row: PaymentApi): PaymentRecord {
  return {
    id: String(row.id),
    invoiceId: String(row.invoice_id),
    vendor: row.vendor ?? "—",
    amount: row.amount,
    dueDate: row.due_date ?? "—",
    tab: row.tab as PaymentRecord["tab"],
    invoiceApprovedBy: row.invoice_approved_by ? String(row.invoice_approved_by) : "",
    invoiceApprovedByName: "",
    approvers: (row.approvers ?? []).map((a) => ({
      id: String(a.id ?? ""),
      name: String(a.name ?? ""),
      role: String(a.role ?? ""),
      state: (a.state as "pending" | "approved" | "rejected") ?? "pending",
    })),
    scheduledDate: row.scheduled_date ?? undefined,
    paidDate: row.paid_date ?? undefined,
    paymentIntent: row.payment_intent ?? undefined,
    failureReason: row.failure_reason ?? undefined,
    vendorPayoutStatus: row.vendor_payout_status ?? undefined,
    vendorPayoutMethodType: row.vendor_payout_method_type ?? undefined,
    executionReadinessStatus: row.execution_readiness_status ?? undefined,
    executionBlockingReason: row.execution_blocking_reason ?? undefined,
  };
}

export function paymentsKpis(rows: PaymentRecord[], timeZone: string) {
  const open = rows.filter((p) => p.tab === "queue" || p.tab === "awaiting" || p.tab === "scheduled");
  const total = open.reduce((sum, p) => sum + p.amount, 0);
  const overdue = open.filter((p) => isOverdueDate(p.dueDate, timeZone)).length;
  const dueSoon = open.filter((p) => isDueWithinDays(p.dueDate, 7, timeZone)).length;
  return { count: open.length, total, overdue, dueSoon };
}

export function payablesKpis(invoices: Invoice[], timeZone: string) {
  const total = invoices.reduce((sum, inv) => sum + parseAmount(inv.total), 0);
  const overdue = invoices.filter((inv) => isOverdueDate(inv.due_date, timeZone)).length;
  const dueSoon = invoices.filter((inv) => isDueWithinDays(inv.due_date, 7, timeZone)).length;
  return { count: invoices.length, total, overdue, dueSoon };
}
