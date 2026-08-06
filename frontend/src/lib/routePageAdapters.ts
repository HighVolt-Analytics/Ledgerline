import type { Invoice } from "@/api/types";
import { approvalChainToApproverSteps } from "@/lib/approvalQuorum";
import { documentDisplayRef } from "@/lib/format";
import { invoiceFailedValidations } from "@/lib/invoice";
import { sortInvoicesNewestFirst } from "@/lib/invoices";
import { purchaseActionRequiredInvoices } from "@/lib/purchaseRegisterQueue";
import { salesActionRequiredInvoices } from "@/lib/salesRegisterQueue";
import {
  isDueWithinDays,
  isOverdueDate,
} from "@/lib/tenantTime";
import type {
  EmployeeMaster,
  ExpenseRule,
  PurchaseRule,
  TeamExpenseKind,
  TeamExpenseRule,
} from "@/lib/v4RuleBookTypes";
import { TEAM_EXPENSE_KINDS } from "@/lib/v4RuleBookTypes";
import type {
  ExpenseBudget,
  ExpenseCategoryPolicy,
  ExpenseClaim,
  ExpenseState,
  MatchStatus,
  PaymentRecord,
  CollectionRecord,
  PurchaseOrder,
  SalesOrder,
  ThreeWayMatch,
  ThreeWayMatchDisplay,
  MatchAmountLine,
  LineMatchResult,
} from "@/lib/v4MockData";
import type { PaymentApi, PurchaseOrderApi, SalesOrderApi, MatchAmountLineApi, LineMatchResultApi, ThreeWayMatchApi, ThreeWayMatchDisplayApi, TwoWaySalesMatchApi } from "@/api/types";

export const SALES_TWO_WAY_MODE = "two_way_dn_invoice";
export const SALES_THREE_WAY_MODE = "three_way_so_dn";
export const PURCHASE_TWO_WAY_MODE = "two_way_po_ses";
export const PURCHASE_THREE_WAY_MODE = "three_way_po_grn";

export function isSalesTwoWayMode(matchMode?: string | null): boolean {
  return (matchMode ?? SALES_THREE_WAY_MODE) === SALES_TWO_WAY_MODE;
}

export function isPurchaseTwoWayMode(matchMode?: string | null): boolean {
  return (matchMode ?? PURCHASE_THREE_WAY_MODE) === PURCHASE_TWO_WAY_MODE;
}

export function splitSalesRegisterRows(rows: SalesOrderApi[]) {
  const threeWayRows = rows.filter((row) => !isSalesTwoWayMode(row.match_mode));
  const twoWayRows = rows.filter((row) => isSalesTwoWayMode(row.match_mode));
  return { threeWayRows, twoWayRows };
}

export function splitPurchaseRegisterRows(rows: PurchaseOrderApi[]) {
  const threeWayRows = rows.filter((row) => !isPurchaseTwoWayMode(row.match_mode));
  const twoWayRows = rows.filter((row) => isPurchaseTwoWayMode(row.match_mode));
  return { threeWayRows, twoWayRows };
}

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

export type SalesRegisterRow = {
  id: string;
  documentRef: string;
  customer: string;
  amount: number;
  date: string;
  dueDate: string | null;
  status: string;
  state: ExpenseState;
  submittedTs: string;
  overdue: boolean;
};

export function invoiceToSalesRow(inv: Invoice): SalesRegisterRow {
  const amount = parseAmount(inv.total);
  return {
    id: String(inv.id),
    documentRef: documentDisplayRef(inv),
    customer: inv.vendor?.trim() || "—",
    amount,
    date: inv.invoice_date ?? "—",
    dueDate: inv.due_date ?? null,
    status: inv.status,
    state: invoiceToExpenseState(inv),
    submittedTs: formatTs(inv.created_at),
    overdue: inv.due_date ? isOverdueDate(inv.due_date) : false,
  };
}

export function salesKpisFromRegister(salesRows: SalesOrderApi[], routed: Invoice[]) {
  const { threeWayRows, twoWayRows } = splitSalesRegisterRows(salesRows);
  const openSos = threeWayRows.filter((r) => r.match.status !== "3-Way Match").length;
  const missingDn = threeWayRows.filter((r) => r.match.status === "No DN").length;
  const matched = threeWayRows.filter((r) => r.match.status === "3-Way Match").length;
  const matchPct =
    threeWayRows.length > 0 ? Math.round((matched / threeWayRows.length) * 100) : 0;
  const twoWayMatched = twoWayRows.filter((r) => r.match.status === "2-Way Match").length;
  const twoWayMatchPct =
    twoWayRows.length > 0 ? Math.round((twoWayMatched / twoWayRows.length) * 100) : 0;
  const variancesAwaiting = salesRows.filter((r) =>
    salesNeedsVarianceApproval(r.match.status, r.variance_approved)
  ).length;
  const awaitingSo = routed.filter((inv) => inv.evaluation_status === "awaiting_so").length;
  const needsAction = salesActionRequiredInvoices(routed, salesRows).length;
  const rows = routed.map(invoiceToSalesRow);
  const open = rows.filter((r) => r.state === "New" || r.state === "In Review").length;
  const pending = rows.filter((r) => r.state === "In Review").length;
  const postedInvoices = routed.filter(
    (inv) => inv.status === "processed" && inv.published_to_ledger
  );
  const postedTotal = postedInvoices.reduce(
    (sum, inv) => sum + (parseFloat(String(inv.total ?? 0)) || 0),
    0
  );
  const overdue = rows.filter((r) => r.overdue && r.state !== "Posted to Ledger").length;

  return {
    openSos,
    missingDn,
    matchPct,
    twoWayMatchPct,
    twoWayCount: twoWayRows.length,
    variancesAwaiting,
    awaitingSo,
    needsAction,
    open,
    pending,
    postedCount: postedInvoices.length,
    postedTotal,
    overdue,
  };
}

export function salesNeedsVarianceApproval(
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

export function invoiceToTeamClaim(
  inv: Invoice,
  employees: EmployeeMaster[] = []
): ExpenseClaim {
  const amount = parseAmount(inv.total);
  const gst = parseAmount(inv.gst);
  const matched = matchEmployeeForSender(inv.email_sender, employees);
  return {
    id: String(inv.id),
    documentRef: documentDisplayRef(inv),
    submitter: matched?.name ?? inferSubmitter(inv),
    employeeId: matched?.id ?? "",
    division: matched?.division ?? "",
    location: matched?.location ?? "",
    advanceBalance: matched?.advanceBalance ?? 0,
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
    approvers: approvalChainToApproverSteps(inv.approval_chain),
    kind: normalizeTeamExpenseKind(inv.team_expense_kind),
  };
}

export function normalizeTeamExpenseKind(value: string | null | undefined): TeamExpenseKind {
  const cleaned = (value ?? "").trim().toLowerCase();
  // Legacy against-advance invoices display/edit as expense claims.
  if (cleaned === "expense_against_advance") return "expense_claim";
  return TEAM_EXPENSE_KINDS.includes(cleaned as TeamExpenseKind)
    ? (cleaned as TeamExpenseKind)
    : "expense_claim";
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
  let key = sender.trim().toLowerCase();
  const angle = key.match(/<([^>]+)>/);
  if (angle?.[1]?.includes("@")) key = angle[1].trim();
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
  if (inv.duplicate_review_suggested) return "Possible duplicate — review suggested";
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
  const { threeWayRows, twoWayRows } = splitPurchaseRegisterRows(rows);
  const openPos = threeWayRows.filter((r) => r.match.status !== "3-Way Match").length;
  const missingGrn = threeWayRows.filter((r) => r.match.status === "No GRN").length;
  const matched = threeWayRows.filter((r) => r.match.status === "3-Way Match").length;
  const matchPct =
    threeWayRows.length > 0 ? Math.round((matched / threeWayRows.length) * 100) : 0;
  const twoWayMatched = twoWayRows.filter((r) => r.match.status === "2-Way Match").length;
  const twoWayMatchPct =
    twoWayRows.length > 0 ? Math.round((twoWayMatched / twoWayRows.length) * 100) : 0;
  const variancesAwaiting = rows.filter((r) =>
    purchaseNeedsVarianceApproval(r.match.status, r.variance_approved)
  ).length;
  const awaitingPo = routed.filter((inv) => inv.evaluation_status === "awaiting_po").length;
  const needsAction = purchaseActionRequiredInvoices(routed, rows).length;
  const withoutPoRef = routed.filter((inv) => !inv.po_reference?.trim()).length;

  return {
    openPos,
    missingGrn,
    matchPct,
    twoWayMatchPct,
    twoWayCount: twoWayRows.length,
    variancesAwaiting,
    awaitingPo,
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

function mapMatchAmountLine(line: MatchAmountLineApi): MatchAmountLine {
  return {
    qty: line.qty,
    uom: line.uom ?? null,
    unitPrice: line.unit_price ?? null,
    lineValue: line.line_value ?? null,
  };
}

function mapMatchDisplay(d: ThreeWayMatchDisplayApi): ThreeWayMatchDisplay {
  return {
    baseUom: d.base_uom ?? undefined,
    poOnDocument: mapMatchAmountLine(d.po_on_document),
    poForMatch: mapMatchAmountLine(d.po_for_match),
    grnOnDocument: d.grn_on_document ? mapMatchAmountLine(d.grn_on_document) : null,
    grnForMatch: d.grn_for_match ? mapMatchAmountLine(d.grn_for_match) : null,
    invoiceOnDocument: d.invoice_on_document ? mapMatchAmountLine(d.invoice_on_document) : null,
    invoiceForMatch: d.invoice_for_match ? mapMatchAmountLine(d.invoice_for_match) : null,
    matchExplanation: d.match_explanation ?? null,
  };
}

export function mapThreeWayMatchFromApi(match: ThreeWayMatchApi): ThreeWayMatch {
  const lineResults: LineMatchResult[] | undefined = match.line_results?.map(
    (row: LineMatchResultApi) => ({
      status: row.status,
      description: row.description,
      sku: row.sku,
      orderQty: row.order_qty,
      orderUom: row.order_uom,
      orderUnitPrice: row.order_unit_price,
      receivedQty: row.received_qty,
      receivedUom: row.received_uom,
      invoiceQty: row.invoice_qty,
      invoiceUom: row.invoice_uom,
      invoiceUnitPrice: row.invoice_unit_price,
      qtyVarianceValue: row.qty_variance_value,
      priceVarianceValue: row.price_variance_value,
    }),
  );
  return {
    status: match.status as MatchStatus,
    qtyVarianceValue: match.qty_variance_value,
    priceVarianceValue: match.price_variance_value,
    totalDeviation: match.total_deviation,
    poValue: match.po_value,
    invoiceValue: match.invoice_value,
    invoiceGst: match.invoice_gst,
    invoiceTotal: match.invoice_total,
    display: match.display ? mapMatchDisplay(match.display) : null,
    lineResults,
  };
}

export function apiPurchaseToRow(row: PurchaseOrderApi): {
  purchaseId: number;
  invoiceId: number | null;
  po: PurchaseOrder;
  m: ThreeWayMatch;
  matchMode: string;
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
  const m: ThreeWayMatch = mapThreeWayMatchFromApi(row.match);
  return {
    purchaseId: row.id,
    invoiceId: row.invoice_id,
    po,
    m,
    matchMode: row.match_mode ?? PURCHASE_THREE_WAY_MODE,
    threeWayAuditStatus: row.three_way_match_status ?? null,
  };
}

export function apiSalesToRow(row: SalesOrderApi): {
  salesId: number;
  invoiceId: number | null;
  so: SalesOrder;
  m: ThreeWayMatch;
  matchMode: string;
  threeWayAuditStatus: SalesOrderApi["three_way_match_status"];
} {
  const so: SalesOrder = {
    id: row.so_number,
    customer: row.customer ?? "—",
    date: row.so_date ?? "—",
    requestor: row.requestor ?? "—",
    item: row.item ?? "—",
    soQty: row.so_qty,
    soUnitPrice: row.so_unit_price,
    dnQty: row.dn_qty,
    dnDate: row.dn_date,
    dnShipper: row.dn_shipper,
    dnCondition: row.dn_condition,
    invoiceNo: row.invoice_no ?? "—",
    invoiceQty: row.invoice_qty,
    invoiceUnitPrice: row.invoice_unit_price,
    gstRate: row.gst_rate,
    routedForApproval: salesNeedsVarianceApproval(row.match.status, row.variance_approved),
    matchedRuleName: row.matched_rule_name ?? null,
    matchedGl: row.matched_gl ?? null,
    evaluationStatus: row.evaluation_status ?? null,
    matchedRuleIds: row.matched_rule_ids ?? [],
    soDocumentId: row.so_document_id ?? null,
    dnDocumentId: row.dn_document_id ?? null,
  };
  const m: ThreeWayMatch = mapThreeWayMatchFromApi(row.match);
  return {
    salesId: row.id,
    invoiceId: row.invoice_id,
    so,
    m,
    matchMode: row.match_mode ?? SALES_THREE_WAY_MODE,
    threeWayAuditStatus: row.three_way_match_status ?? null,
  };
}

export type SalesTwoWayOrphanRow = {
  kind: "orphan";
  invoiceId: number;
  dnInvoiceId: number | null;
  invoiceNo: string;
  customer: string;
  dnQty: number | null;
  invoiceQty: number;
  m: ThreeWayMatch;
};

export function apiTwoWaySalesOrphanToRow(row: TwoWaySalesMatchApi): SalesTwoWayOrphanRow {
  return {
    kind: "orphan",
    invoiceId: row.invoice_id,
    dnInvoiceId: row.dn_invoice_id,
    invoiceNo: row.invoice_no ?? "—",
    customer: row.customer ?? "—",
    dnQty: row.dn_qty,
    invoiceQty: row.invoice_qty,
    m: mapThreeWayMatchFromApi(row.match),
  };
}

export type SalesRegisterTableRow =
  | ({ kind: "register" } & ReturnType<typeof apiSalesToRow>)
  | SalesTwoWayOrphanRow;

export function salesTwoWayTableRowKey(row: SalesRegisterTableRow): string {
  if (row.kind === "orphan") return `orphan-${row.invoiceId}`;
  return `${row.salesId}-${row.invoiceId ?? "none"}`;
}

export function apiPaymentToRecord(row: PaymentApi): PaymentRecord {
  return {
    id: String(row.id),
    invoiceId: String(row.invoice_id),
    vendor: row.vendor ?? "—",
    amount: row.amount,
    currency: (row.currency || "").trim().toUpperCase(),
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
    executionInstruction: row.execution_instruction
      ? {
          id: row.execution_instruction.id,
          instructionReference: row.execution_instruction.instruction_reference,
          vendorName: row.execution_instruction.vendor_name ?? "—",
          vendorPayoutMethodLabel: row.execution_instruction.vendor_payout_method_label ?? "—",
          amount: row.execution_instruction.amount,
          currency: row.execution_instruction.currency,
          dueDate: row.execution_instruction.due_date ?? undefined,
          executionMode: row.execution_instruction.execution_mode,
          status: row.execution_instruction.status,
          createdByName: row.execution_instruction.created_by_name ?? undefined,
          createdAt: row.execution_instruction.created_at,
        }
      : undefined,
  };
}

export function collectionsKpis(rows: CollectionRecord[], timeZone: string) {
  const open = rows.filter((c) => c.tab === "queue" || c.tab === "awaiting");
  const total = open.reduce((sum, c) => sum + c.amount, 0);
  const totalByCurrency: Record<string, number> = {};
  for (const c of open) {
    const code = (c.currency || "").trim().toUpperCase();
    totalByCurrency[code] = (totalByCurrency[code] ?? 0) + c.amount;
  }
  const overdue = open.filter((c) => isOverdueDate(c.dueDate, timeZone)).length;
  const dueSoon = open.filter((c) => isDueWithinDays(c.dueDate, 7, timeZone)).length;
  return { count: open.length, total, totalByCurrency, overdue, dueSoon };
}

export function paymentsKpis(rows: PaymentRecord[], timeZone: string) {
  const open = rows.filter((p) => p.tab === "queue" || p.tab === "awaiting" || p.tab === "scheduled");
  const total = open.reduce((sum, p) => sum + p.amount, 0);
  const totalByCurrency: Record<string, number> = {};
  for (const p of open) {
    const code = (p.currency || "").trim().toUpperCase();
    totalByCurrency[code] = (totalByCurrency[code] ?? 0) + p.amount;
  }
  const overdue = open.filter((p) => isOverdueDate(p.dueDate, timeZone)).length;
  const dueSoon = open.filter((p) => isDueWithinDays(p.dueDate, 7, timeZone)).length;
  return { count: open.length, total, totalByCurrency, overdue, dueSoon };
}

export function payablesKpis(invoices: Invoice[], timeZone: string) {
  const total = invoices.reduce((sum, inv) => sum + parseAmount(inv.total), 0);
  const overdue = invoices.filter((inv) => isOverdueDate(inv.due_date, timeZone)).length;
  const dueSoon = invoices.filter((inv) => isDueWithinDays(inv.due_date, 7, timeZone)).length;
  return { count: invoices.length, total, overdue, dueSoon };
}
