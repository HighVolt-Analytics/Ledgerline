import raw from "./v4MockData.json";
import { money } from "@/lib/format";

export type ExpenseState =
  | "New"
  | "In Review"
  | "Approved"
  | "Rejected"
  | "Posted to Ledger";

export type ApproverStep = {
  id: string;
  name: string;
  role: string;
  state: "pending" | "approved" | "rejected";
  ts?: string;
};

export type ExpenseClaim = {
  id: string;
  /** Org document label (DOC-… / document_ref) — not the legacy INV- prefix. */
  documentRef?: string;
  submitter: string;
  channel: string;
  category: string;
  amount: number;
  gst: number;
  date: string;
  submittedTs: string;
  state: ExpenseState;
  purpose: string;
  projectTag: string;
  merchant: string;
  budgetGroup: string;
  approvers: ApproverStep[];
};

export type ExpenseBudget = {
  category: string;
  owner: string;
  period: string;
  monthlyBudget: number;
  used: number;
};

export type ExpenseCategoryPolicy = {
  category: string;
  glAccount: string;
  requiresReceiptOver: number;
  autoApproveUnder: number;
  policyNote: string;
};

export type ClaimChannel = {
  id: string;
  name: string;
  detail: string;
  connected: boolean;
};

export type PurchaseOrder = {
  id: string;
  vendor: string;
  date: string;
  requestor: string;
  item: string;
  poQty: number;
  poUnitPrice: number;
  grnQty: number | null;
  grnDate: string | null;
  grnReceiver: string | null;
  grnCondition: string | null;
  invoiceNo: string;
  invoiceQty: number;
  invoiceUnitPrice: number;
  gstRate: number;
  routedForApproval?: boolean;
  approvers?: ApproverStep[];
  matchedRuleName?: string | null;
  matchedGl?: string | null;
  evaluationStatus?: string | null;
  matchedRuleIds?: string[];
  poDocumentId?: number | null;
  grnDocumentId?: number | null;
};

export type MatchStatus =
  | "3-Way Match"
  | "Qty Variance"
  | "Price Variance"
  | "Routed for Approval"
  | "No GRN";

export type ThreeWayMatch = {
  status: MatchStatus;
  qtyVarianceValue: number;
  priceVarianceValue: number;
  totalDeviation: number;
  poValue: number;
  invoiceValue: number;
  invoiceGst: number;
  invoiceTotal: number;
};

export type PaymentTab = "queue" | "awaiting" | "scheduled" | "paid" | "failed";

export type PaymentRecord = {
  id: string;
  invoiceId: string;
  vendor: string;
  amount: number;
  dueDate: string;
  tab: PaymentTab;
  invoiceApprovedBy: string;
  invoiceApprovedByName: string;
  approvers: ApproverStep[];
  scheduledDate?: string;
  paidDate?: string;
  paymentIntent?: string;
  failureReason?: string;
  vendorPayoutStatus?: string;
  vendorPayoutMethodType?: string;
  executionReadinessStatus?:
    | "not_ready"
    | "awaiting_approval"
    | "blocked_stripe_setup"
    | "blocked_vendor_payout_setup"
    | "ready_dry_run"
    | "manual_instruction_available"
    | "instruction_created"
    | "blocked_limit"
    | "blocked_tenant_disabled"
    | "scheduled"
    | "paid"
    | "failed";
  executionBlockingReason?: string;
  executionInstruction?: {
    id: number;
    instructionReference: string;
    vendorName: string;
    vendorPayoutMethodLabel: string;
    amount: number;
    currency: string;
    dueDate?: string;
    executionMode: string;
    status: string;
    createdByName?: string;
    createdAt: string;
  };
};

export type WalletTxn = {
  id: string;
  ts: string;
  label: string;
  delta: number;
};

export type StripeWallet = {
  balance: number;
  available: number;
  lastTopUp: string;
  txns: WalletTxn[];
};

export type LedgerExportRow = {
  id: string;
  doc: string;
  date: string;
  party: string;
  debit: string;
  credit: string;
  amount: number;
  status: string;
};

export type AuditEvent = {
  id: string;
  docId: string;
  ts: string;
  actor: string;
  action: string;
  detail: string;
};

export type LedgerPosting = {
  account: string;
  debit?: number;
  credit?: number;
};

export type LedgerReconInvoice = {
  id: string;
  vendor: string;
  total: number;
  postings: LedgerPosting[];
};

export type LedgerReconDay = {
  date: string;
  count: number;
  sumDr: number;
  sumCr: number;
  delta: number;
  invoices: LedgerReconInvoice[];
};

export type LedgerRecon = {
  balanced: boolean;
  deltaDrCr: number;
  sumDr: number;
  sumCr: number;
  byDate: LedgerReconDay[];
};

export const INITIAL_EXPENSES = raw.expenses as ExpenseClaim[];
export const EXPENSE_BUDGETS = raw.budgets as ExpenseBudget[];
export const EXPENSE_CATEGORIES = raw.categories as ExpenseCategoryPolicy[];
export const CLAIM_CHANNELS = raw.channels as ClaimChannel[];
export const INITIAL_PURCHASES = raw.purchases as PurchaseOrder[];
export const INITIAL_PAYMENTS = raw.payments as PaymentRecord[];
export const MOCK_WALLET = raw.wallet as StripeWallet;
export const LEDGER_INVOICES = raw.ledgerInvoices as LedgerExportRow[];
export const LEDGER_BILLS = raw.ledgerBills as LedgerExportRow[];
export const LEDGER_EXPENSES = raw.ledgerExpenses as LedgerExportRow[];
export const LEDGER_PURCHASES = raw.ledgerPurchases as LedgerExportRow[];
export const LEDGER_PAYMENTS = raw.ledgerPayments as LedgerExportRow[];
export const EXPORT_HISTORY = raw.exportHistory as {
  id: string;
  ts: string;
  target: string;
  count: number;
  user: string;
  status: string;
}[];
export const AUDIT_EVENTS = raw.auditEvents as AuditEvent[];

export const EXPORT_TARGETS = [
  "Xero",
  "QuickBooks Online",
  "MYOB",
  "NetSuite",
  "Generic CSV",
] as const;

export const PAYMENT_TABS: { value: PaymentTab; label: string }[] = [
  { value: "queue", label: "Payment Queue" },
  { value: "awaiting", label: "Awaiting Approval" },
  { value: "scheduled", label: "Approved · Scheduled" },
  { value: "paid", label: "Paid" },
  { value: "failed", label: "Failed" },
];

export const MOCK_LEDGER_RECON: LedgerRecon = {
  balanced: true,
  deltaDrCr: 0,
  sumDr: 42892,
  sumCr: 42892,
  byDate: [
    {
      date: "2026-05-28",
      count: 3,
      sumDr: 18432,
      sumCr: 18432,
      delta: 0,
      invoices: [
        {
          id: "INV-001",
          vendor: "Amazon Web Services",
          total: 3113,
          postings: [
            { account: "Cloud Hosting Expense", debit: 2830 },
            { account: "GST Paid", debit: 283 },
            { account: "Accounts Payable", credit: 3113 },
          ],
        },
        {
          id: "INV-002",
          vendor: "Atlassian Pty Ltd",
          total: 3179,
          postings: [
            { account: "Software Subscription Expense", debit: 2889 },
            { account: "GST Paid", debit: 290 },
            { account: "Accounts Payable", credit: 3179 },
          ],
        },
        {
          id: "EXP-006",
          vendor: "Arup · Qantas",
          total: 540,
          postings: [
            { account: "Travel Expense", debit: 491 },
            { account: "GST Paid", debit: 49 },
            { account: "Employee Reimbursements", credit: 540 },
          ],
        },
      ],
    },
    {
      date: "2026-05-29",
      count: 2,
      sumDr: 12340,
      sumCr: 12340,
      delta: 0,
      invoices: [
        {
          id: "INV-004",
          vendor: "Meta Platforms Ireland",
          total: 3080,
          postings: [
            { account: "Marketing Expense", debit: 2800 },
            { account: "GST Paid", debit: 280 },
            { account: "Accounts Payable", credit: 3080 },
          ],
        },
        {
          id: "PO-2026-101",
          vendor: "Officeworks",
          total: 10395,
          postings: [
            { account: "Office Equipment", debit: 9450 },
            { account: "GST Paid", debit: 945 },
            { account: "Accounts Payable", credit: 10395 },
          ],
        },
      ],
    },
  ],
};

const GENERIC_AUDIT: AuditEvent[] = [
  {
    id: "gen-captured",
    docId: "",
    ts: "2026-05-30 08:00",
    actor: "Capture channel",
    action: "Captured",
    detail: "Document received and parsed",
  },
  {
    id: "gen-review",
    docId: "",
    ts: "2026-05-30 08:05",
    actor: "Rule engine",
    action: "Routed",
    detail: "Routed to approval policy",
  },
];

export function auditForDoc(docId: string): AuditEvent[] {
  const specific = AUDIT_EVENTS.filter((e) => e.docId === docId);
  if (specific.length > 0) return specific;
  return GENERIC_AUDIT.map((e) => ({ ...e, docId, id: `${e.id}-${docId}` }));
}

function round2(n: number) {
  return Math.round(n * 100) / 100;
}

export function computeThreeWayMatch(po: PurchaseOrder): ThreeWayMatch {
  const poValue = round2(po.poQty * po.poUnitPrice);
  const invoiceValue = round2(po.invoiceQty * po.invoiceUnitPrice);
  const invoiceGst = round2(invoiceValue * po.gstRate);
  const invoiceTotal = round2(invoiceValue + invoiceGst);

  if (po.grnQty === null) {
    return {
      status: "No GRN",
      qtyVarianceValue: 0,
      priceVarianceValue: 0,
      totalDeviation: 0,
      poValue,
      invoiceValue,
      invoiceGst,
      invoiceTotal,
    };
  }

  const qtyVarianceValue = round2((po.invoiceQty - po.grnQty) * po.invoiceUnitPrice);
  const priceVarianceValue = round2((po.invoiceUnitPrice - po.poUnitPrice) * po.invoiceQty);
  const totalDeviation = round2(qtyVarianceValue + priceVarianceValue);

  let status: MatchStatus;
  if (po.routedForApproval) status = "Routed for Approval";
  else if (priceVarianceValue !== 0) status = "Price Variance";
  else if (po.grnQty !== po.invoiceQty) status = "Qty Variance";
  else status = "3-Way Match";

  return {
    status,
    qtyVarianceValue,
    priceVarianceValue,
    totalDeviation,
    poValue,
    invoiceValue,
    invoiceGst,
    invoiceTotal,
  };
}

export function fmtAud(amount: number) {
  return money(amount, "AUD");
}

export function expenseNavBadgeCount(expenses: ExpenseClaim[]) {
  return expenses.filter((e) => e.state === "New" || e.state === "In Review").length;
}

export function paymentNavBadgeCount(payments: PaymentRecord[]) {
  return payments.filter((p) => p.tab === "queue" || p.tab === "awaiting").length;
}

export const MOCK_NAV_BADGES = {
  expenses: expenseNavBadgeCount(INITIAL_EXPENSES),
  payments: paymentNavBadgeCount(INITIAL_PAYMENTS),
};

export function paymentTierLabel(amount: number) {
  if (amount < 1_000) return "< $1k · 1 approver";
  if (amount < 10_000) return "$1k–$10k · 2 approvers";
  if (amount < 50_000) return "$10k–$50k · 3 approvers";
  return "> $50k · 4 approvers";
}

export function paymentApproverCount(amount: number) {
  if (amount < 1_000) return 1;
  if (amount < 10_000) return 2;
  if (amount < 50_000) return 3;
  return 4;
}

export function allLedgerExportRows() {
  return [
    { group: "Invoices", rows: LEDGER_INVOICES },
    { group: "Bills", rows: LEDGER_BILLS },
    { group: "Expenses", rows: LEDGER_EXPENSES },
    { group: "Purchases", rows: LEDGER_PURCHASES },
    { group: "Payments", rows: LEDGER_PAYMENTS },
  ];
}
