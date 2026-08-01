import type {
  ConditionOperator,
  EmailCaptureRule,
  EmailField,
  EvalDocument,
  ExpenseRule,
  EmployeeMaster,
  PurchaseRule,
  RuleConditionGroup,
  TeamExpenseRule,
  RuleBookConfigState,
  VendorMaster,
} from "./v4RuleBookTypes";
import { emptyOrgContextConfig } from "./v4RuleBookTypes";
export function ruleGroup(
  operator: "AND" | "OR",
  children: RuleConditionGroup["children"]
): RuleConditionGroup {
  return { type: "group", operator, children };
}

export function ruleCond(field: EmailField, operator: ConditionOperator, value: string) {
  return { type: "condition" as const, field, operator, value };
}

const and = ruleGroup;
const cond = ruleCond;

export const EVAL_DOCUMENTS: EvalDocument[] = [
  {
    id: "INV-001",
    docNumber: "DOC-2026-0001",
    invoice_no: "AWS-AU-204815",
    vendor: "Amazon Web Services",
    abn: "63 110 305 305",
    address: "Level 37, 2-26 Park Street, Sydney NSW 2000",
    po: "PO-CLOUD-2026-001",
    primaryAccount: "Cloud Hosting Expense",
    lines: [
      { description: "EC2 Compute - May 2026" },
      { description: "S3 Storage & Data Transfer" },
    ],
  },
  {
    id: "INV-002",
    docNumber: "DOC-2026-0002",
    invoice_no: "SYSCO-INV-88210",
    vendor: "Sysco Australia",
    abn: "11223344556",
    address: "100 Salmon Street, Port Melbourne VIC 3207",
    po: "PO-BEV-2026-014",
    primaryAccount: "Raw Materials",
    lines: [{ description: "Beverage wholesale delivery" }],
  },
  {
    id: "INV-003",
    docNumber: "DOC-2026-0003",
    invoice_no: "ATL-2026-55721",
    vendor: "Atlassian Pty Ltd",
    abn: "53102443916",
    primaryAccount: "Software Subscription Expense",
    lines: [{ description: "Jira Cloud subscription" }],
  },
  {
    id: "INV-004",
    docNumber: "DOC-2026-0004",
    invoice_no: "GOOG-AU-99102",
    vendor: "Google Australia Pty Ltd",
    po: "PO-MKT-2026-014",
    primaryAccount: "Marketing Expense",
    lines: [{ description: "Google Ads campaign spend" }],
  },
  {
    id: "INV-005",
    docNumber: "DOC-2026-0005",
    invoice_no: "UNKNOWN-001",
    vendor: "Sydney Office Florals",
    primaryAccount: "Suspense Account",
    lines: [{ description: "Office flowers" }],
  },
];

const EMAIL_CAPTURE_RULES: EmailCaptureRule[] = [
  {
    id: "ec-1",
    name: "AWS billing",
    enabled: true,
    priority: 1,
    mailbox: "accounts@acme-hospitality.com.au",
    root: and("AND", [
      cond("from", "contains", "billing@amazon"),
      cond("subject", "contains", "invoice"),
      cond("attachment_name", "ends_with", ".pdf"),
    ]),
    action: { saveAttachment: true, routeTo: "Purchase Management", tags: ["AWS", "Cloud"] },
    matchedCount: 24,
    lastMatched: "2h ago",
  },
  {
    id: "ec-2",
    name: "Supplier invoices (Sysco / Bidfood / PFD)",
    enabled: true,
    priority: 2,
    mailbox: "accounts@acme-hospitality.com.au",
    root: and("OR", [
      and("AND", [
        cond("from", "contains", "sysco"),
        cond("attachment_name", "contains", "INV"),
      ]),
      and("AND", [
        cond("from", "contains", "bidfood"),
        cond("attachment_name", "contains", "invoice"),
      ]),
      and("AND", [
        cond("from", "contains", "pfd"),
        cond("subject", "contains", "Tax Invoice"),
      ]),
    ]),
    action: { saveAttachment: true, routeTo: "Purchase Management", tags: ["Supplier", "F&B"] },
    matchedCount: 87,
    lastMatched: "14m ago",
  },
  {
    id: "ec-3",
    name: "Team expense receipts via email",
    enabled: true,
    priority: 3,
    mailbox: "expenses@acme-hospitality.com.au",
    root: and("AND", [
      and("OR", [
        cond("subject", "contains", "receipt"),
        cond("subject", "contains", "expense claim"),
        { type: "condition", field: "subject", operator: "regex", value: "^Fwd:" },
      ]),
      cond("attachment_mime", "contains", "image/"),
    ]),
    action: { saveAttachment: true, routeTo: "Team Expenses", tags: ["receipt"] },
    matchedCount: 15,
    lastMatched: "44m ago",
  },
];

const PURCHASE_RULES: PurchaseRule[] = [
  {
    id: "pr-1",
    name: "Cloud & Hosting POs",
    enabled: true,
    matchOn: { poPrefix: "PO-CLOUD-", grnLinkedToPo: true, invoiceReferencesPo: true },
    postTo: {
      ledger: "Cloud Hosting Expense",
      subLedger: "AWS Production",
      taxAccount: "GST Paid",
      payableAccount: "Accounts Payable",
    },
    matchedCount: 12,
  },
  {
    id: "pr-2",
    name: "Beverage supplier POs",
    enabled: true,
    matchOn: { poPrefix: "PO-BEV-", vendorContains: "Beverage" },
    postTo: {
      ledger: "Raw Materials",
      subLedger: "Beverages — Bar",
      taxAccount: "GST Paid",
      payableAccount: "Accounts Payable",
    },
    matchedCount: 23,
  },
  {
    id: "pr-3",
    name: "Marketing campaign POs",
    enabled: true,
    matchOn: { poRegex: "PO-MKT-2026" },
    postTo: {
      ledger: "Marketing Expense",
      subLedger: "Q2 Campaign",
      taxAccount: "GST Paid",
      payableAccount: "Accounts Payable",
    },
    matchedCount: 6,
  },
  {
    id: "pr-4",
    name: "Capex equipment POs",
    enabled: true,
    matchOn: { poPrefix: "PO-CAPEX-" },
    postTo: {
      ledger: "Plant & Equipment",
      subLedger: "Kitchen Refurbishment",
      taxAccount: "GST Paid",
      payableAccount: "Accounts Payable",
    },
    matchedCount: 3,
  },
];

const EXPENSE_RULES: ExpenseRule[] = [
  {
    id: "er-1",
    name: "AWS subscription",
    enabled: true,
    matchOn: { descriptionContains: "AWS" },
    postTo: { ledger: "Cloud Hosting Expense", subLedger: "Production" },
    matchedCount: 12,
  },
  {
    id: "er-2",
    name: "Microsoft 365",
    enabled: true,
    matchOn: { descriptionContains: "Microsoft 365", vendorContains: "Microsoft" },
    postTo: { ledger: "Software Subscription Expense", subLedger: "Office Suite" },
    matchedCount: 8,
  },
  {
    id: "er-3",
    name: "Telstra phones",
    enabled: true,
    matchOn: { vendorContains: "Telstra" },
    postTo: { ledger: "Software Subscription Expense", subLedger: "Telephony" },
    matchedCount: 6,
  },
  {
    id: "er-4",
    name: "Legal — Smith & Co",
    enabled: true,
    matchOn: { vendorContains: "Smith & Co" },
    postTo: { ledger: "Professional Services Expense", subLedger: "Legal" },
    matchedCount: 4,
  },
  {
    id: "er-5",
    name: "Uber business travel",
    enabled: true,
    matchOn: { vendorContains: "Uber" },
    postTo: { ledger: "Travel Expense", subLedger: "Ground Transport" },
    matchedCount: 9,
  },
  {
    id: "er-6",
    name: "Atlassian subscriptions",
    enabled: true,
    matchOn: { vendorContains: "Atlassian" },
    postTo: { ledger: "Software Subscription Expense", subLedger: "Dev Tools" },
    matchedCount: 5,
  },
  {
    id: "er-7",
    name: "Internal document series",
    enabled: true,
    matchOn: { docNumberContains: "DOC-2026" },
    postTo: { ledger: "Operating Expenses", subLedger: "General" },
    matchedCount: 18,
  },
];

const TEAM_EXPENSE_RULES: TeamExpenseRule[] = [
  {
    id: "tr-1",
    name: "Site supervisor meals",
    enabled: true,
    matchOn: { descriptionContains: "meal / lunch / dinner", channelEquals: "Any", amountMax: 80 },
    postTo: { ledger: "Travel Expense", subLedger: "Meals" },
    policy: { requireReceipt: true, receiptThreshold: 25, autoApproveBelow: 30 },
    matchedCount: 31,
  },
  {
    id: "tr-2",
    name: "Taxi & rideshare",
    enabled: true,
    matchOn: { merchantContains: "Uber / Ola / Didi", channelEquals: "Any" },
    postTo: { ledger: "Travel Expense", subLedger: "Ground Transport" },
    policy: { requireReceipt: true, receiptThreshold: 50, autoApproveBelow: 50 },
    matchedCount: 24,
  },
  {
    id: "tr-3",
    name: "Office consumables",
    enabled: true,
    matchOn: { descriptionContains: "stationery / milk / coffee", channelEquals: "Any" },
    postTo: { ledger: "Office", subLedger: "Pantry" },
    policy: { requireReceipt: true, receiptThreshold: 40, autoApproveBelow: 40 },
    matchedCount: 17,
  },
  {
    id: "tr-4",
    name: "Client entertainment",
    enabled: true,
    matchOn: { descriptionContains: "client", channelEquals: "Any" },
    postTo: { ledger: "Marketing Expense", subLedger: "Client Entertainment" },
    policy: { requireReceipt: true, receiptThreshold: 0, autoApproveBelow: 0 },
    matchedCount: 5,
  },
];

const VENDOR_MASTERS: VendorMaster[] = [
  {
    id: "vm-1",
    name: "Amazon Web Services",
    aliases: ["AWS", "Amazon Web Services Inc", "AMZ Cloud"],
    abn: "98765432101",
    billingAddress: {
      street: "Level 37, 2-26 Park Street",
      suburb: "Sydney NSW",
      postcode: "2000",
      country: "Australia",
    },
    bank: {
      bsb: "062-001",
      accountNumber: "12345678",
      accountName: "AWS Australia Pty Ltd",
      bankName: "Commonwealth Bank",
    },
    defaultLedger: "Cloud Hosting Expense",
    defaultSubLedger: "Production",
    paymentTerms: "Net 30",
    status: "Active",
    registeredOn: "2024-08-12",
    totalSpendYTD: 18420,
    invoiceCount: 12,
    matchConfidence: 99,
  },
  {
    id: "vm-2",
    name: "Sysco Australia",
    aliases: ["Sysco", "SYSCO AU"],
    abn: "11223344556",
    billingAddress: {
      street: "100 Salmon Street",
      suburb: "Port Melbourne VIC",
      postcode: "3207",
      country: "Australia",
    },
    bank: {
      bsb: "033-099",
      accountNumber: "98765432",
      accountName: "Sysco Australia Pty Ltd",
      bankName: "Westpac",
    },
    defaultLedger: "Raw Materials",
    defaultSubLedger: "F&B",
    paymentTerms: "Net 14",
    status: "Active",
    registeredOn: "2023-11-03",
    totalSpendYTD: 42180,
    invoiceCount: 23,
    matchConfidence: 97,
  },
  {
    id: "vm-3",
    name: "Telstra Corporation",
    aliases: ["Telstra"],
    abn: "33051775556",
    billingAddress: {
      street: "242 Exhibition Street",
      suburb: "Melbourne VIC",
      postcode: "3000",
      country: "Australia",
    },
    bank: {
      bsb: "084-004",
      accountNumber: "11220033",
      accountName: "Telstra Corporation Ltd",
      bankName: "NAB",
    },
    defaultLedger: "Software Subscription Expense",
    defaultSubLedger: "Telephony",
    paymentTerms: "Net 30",
    status: "Active",
    registeredOn: "2023-06-21",
    totalSpendYTD: 6840,
    invoiceCount: 6,
    matchConfidence: 99,
  },
  {
    id: "vm-4",
    name: "Smith & Co Legal",
    aliases: ["Smith and Co", "Smith & Co Lawyers"],
    abn: "55667788990",
    billingAddress: {
      street: "Suite 12, 88 Phillip Street",
      suburb: "Sydney NSW",
      postcode: "2000",
      country: "Australia",
    },
    bank: {
      bsb: "062-440",
      accountNumber: "33445566",
      accountName: "Smith & Co Legal Pty Ltd",
      bankName: "Commonwealth Bank",
    },
    defaultLedger: "Professional Services Expense",
    defaultSubLedger: "Legal",
    paymentTerms: "Net 14",
    status: "Active",
    registeredOn: "2024-02-14",
    totalSpendYTD: 12500,
    invoiceCount: 4,
    matchConfidence: 96,
  },
  {
    id: "vm-5",
    name: "Bidfood Australia",
    aliases: ["Bidfood", "BID FOOD"],
    abn: "77889900112",
    billingAddress: {
      street: "6 Eden Park Drive",
      suburb: "Macquarie Park NSW",
      postcode: "2113",
      country: "Australia",
    },
    bank: {
      bsb: "062-191",
      accountNumber: "77889911",
      accountName: "Bidfood Australia Ltd",
      bankName: "Commonwealth Bank",
    },
    defaultLedger: "Raw Materials",
    defaultSubLedger: "F&B Wholesale",
    paymentTerms: "Net 21",
    status: "Active",
    registeredOn: "2023-09-30",
    totalSpendYTD: 28940,
    invoiceCount: 18,
    matchConfidence: 98,
  },
  {
    id: "vm-6",
    name: "Sydney Office Florals",
    aliases: ["SOF", "Sydney Florals"],
    abn: "PENDING",
    billingAddress: {
      street: "12 Crown Street",
      suburb: "Surry Hills NSW",
      postcode: "2010",
      country: "Australia",
    },
    bank: { accountNumber: "", accountName: "", bankName: "" },
    defaultLedger: "—",
    defaultSubLedger: "",
    paymentTerms: "—",
    status: "Pending registration",
    registeredOn: "—",
    totalSpendYTD: 220,
    invoiceCount: 1,
    matchConfidence: 42,
  },
];

const EMPLOYEE_MASTERS: EmployeeMaster[] = [
  {
    id: "em-1",
    name: "Marcus Webb",
    role: "Operations Manager",
    email: "marcus.webb@acme-hospitality.com.au",
    whatsappNumber: "+61 412 345 678",
    whatsappNumber2: "+61 412 345 679",
    dateOfJoining: "2021-04-12",
    department: "Operations",
    location: "Sydney",
    division: "Hospitality",
    supervisor1: "Alex Morgan",
    supervisor2: "Sam Rivera",
    bank: {
      bsb: "062-001",
      accountNumber: "11223344",
      accountName: "Marcus Webb",
      bankName: "Commonwealth Bank",
    },
    budget: {
      monthly: 2000,
      quarterly: 5500,
      annual: 20000,
      categories: [
        { ledger: "Travel Expense", cap: 800 },
        { ledger: "Travel Expense", cap: 400 },
        { ledger: "Office", cap: 300 },
      ],
    },
    advanceParentLedger: 'Staff Advance',
    advanceSubLedger: "",
    ytdSpent: 9840,
    mtdSpent: 1420,
    qtdSpent: 4180,
    claimCount: 23,
    lastClaim: "2h ago",
    status: "Active",
  },
  {
    id: "em-2",
    name: "Priya Sharma",
    role: "Site Supervisor",
    email: "priya@acme-hospitality.com.au",
    whatsappNumber: "+61 423 567 890",
    bank: {
      bsb: "032-002",
      accountNumber: "22334455",
      accountName: "Priya Sharma",
      bankName: "Westpac",
    },
    budget: {
      monthly: 1500,
      quarterly: 4000,
      annual: 14000,
      categories: [
        { ledger: "Travel Expense", cap: 600 },
        { ledger: "Travel Expense", cap: 300 },
      ],
    },
    advanceParentLedger: 'Staff Advance',
    advanceSubLedger: "",
    ytdSpent: 7210,
    mtdSpent: 980,
    qtdSpent: 2840,
    claimCount: 18,
    lastClaim: "44m ago",
    status: "Active",
  },
  {
    id: "em-3",
    name: "James Chen",
    role: "Marketing Lead",
    email: "james@acme-hospitality.com.au",
    whatsappNumber: "+61 434 678 901",
    bank: {
      bsb: "013-003",
      accountNumber: "33445566",
      accountName: "James Chen",
      bankName: "ANZ",
    },
    budget: {
      monthly: 3000,
      quarterly: 8000,
      annual: 30000,
      categories: [
        { ledger: "Marketing Expense", cap: 2000 },
        { ledger: "Travel Expense", cap: 800 },
      ],
    },
    advanceParentLedger: 'Staff Advance',
    advanceSubLedger: "",
    ytdSpent: 14520,
    mtdSpent: 2180,
    qtdSpent: 6420,
    claimCount: 31,
    lastClaim: "1d ago",
    status: "Active",
  },
  {
    id: "em-4",
    name: "Sofia Lopez",
    role: "Bookkeeper",
    email: "sofia@acme-hospitality.com.au",
    whatsappNumber: "+61 445 789 012",
    bank: {
      bsb: "082-004",
      accountNumber: "44556677",
      accountName: "Sofia Lopez",
      bankName: "NAB",
    },
    budget: {
      monthly: 800,
      quarterly: 2200,
      annual: 8000,
      categories: [
        { ledger: "Office", cap: 400 },
        { ledger: "Travel Expense", cap: 200 },
      ],
    },
    advanceParentLedger: 'Staff Advance',
    advanceSubLedger: "",
    ytdSpent: 3840,
    mtdSpent: 620,
    qtdSpent: 1840,
    claimCount: 12,
    lastClaim: "3d ago",
    status: "Active",
  },
  {
    id: "em-5",
    name: "Alex Tan",
    role: "Junior Developer",
    email: "alex@acme-hospitality.com.au",
    whatsappNumber: "+61 456 890 123",
    bank: { accountNumber: "", accountName: "", bankName: "" },
    budget: {
      monthly: 500,
      quarterly: 1200,
      annual: 4500,
      categories: [],
    },
    advanceParentLedger: 'Staff Advance',
    advanceSubLedger: "",
    ytdSpent: 0,
    mtdSpent: 0,
    qtdSpent: 0,
    claimCount: 0,
    lastClaim: "—",
    status: "Pending verification",
  },
];

export type RecentClaimValidation = {
  id: string;
  employee: string;
  amount: number;
  channel: string;
  outcome: "approved" | "warning" | "rejected";
  reason: string;
};

export const RECENT_CLAIM_VALIDATIONS: RecentClaimValidation[] = [
  {
    id: "cv-1",
    employee: "Priya Sharma",
    amount: 42,
    channel: "WhatsApp",
    outcome: "approved",
    reason: "Within monthly budget · receipt attached",
  },
  {
    id: "cv-2",
    employee: "Sofia Lopez",
    amount: 28,
    channel: "WhatsApp",
    outcome: "approved",
    reason: "Auto-approved (below $40 threshold)",
  },
  {
    id: "cv-3",
    employee: "James Chen",
    amount: 310,
    channel: "Web",
    outcome: "approved",
    reason: "Client entertainment · receipt verified",
  },
  {
    id: "cv-4",
    employee: "Marcus Webb",
    amount: 180,
    channel: "WhatsApp",
    outcome: "warning",
    reason: "At 71% of monthly budget — review recommended",
  },
  {
    id: "cv-5",
    employee: "Alex Tan",
    amount: 35,
    channel: "Mobile",
    outcome: "rejected",
    reason: "Sender pending verification · no bank details",
  },
];

/** Wildcard — ingestion rules apply to every connected mailbox for the org. */
export const DEFAULT_MAILBOX = "*";
/** Legacy demo placeholder kept for sample rule fixtures only. */
export const DEMO_MAILBOX = "accounts@acme-hospitality.com.au";

export const DEFAULT_POSTING_DEFAULTS = {
  taxAccount: "GST Paid",
  payableAccount: "Accounts Payable",
  receivableAccount: "Accounts Receivable",
  fallbackAccount: "Suspense Account",
} as const;

export const DEFAULT_TEAM_EXPENSE_POSTING = {
  defaultAdvanceParentLedger: "Staff Advance",
  settlementAccount: "Bank Account",
} as const;

export const DEFAULT_DOCUMENT_SETS = [
  {
    id: "ds1",
    pattern: "PO-MKT-2026-014",
    setName: "PO-MKT-2026-014 bundle",
    isolated: false,
  },
] as const;

export function createDefaultRuleBookConfig(): RuleBookConfigState {
  return {
    documentTypes: [],
    documentClassification: {
      unclassifiedDocumentTypeCode: "",
      unclassifiedMinConfidence: 0.45,
    },
    aiClassification: {
      documentAiProvider: "azure_di",
      autoRouteMinConfidence: 0.85,
    },
    orgContext: emptyOrgContextConfig(),
    emailCaptureRules: EMAIL_CAPTURE_RULES,
    purchaseRules: PURCHASE_RULES,
    salesRules: [],
    expenseRules: EXPENSE_RULES,
    teamExpenseRules: TEAM_EXPENSE_RULES,
    vendorMasters: VENDOR_MASTERS,
    vendorDetectionConfig: {
      weights: { name: 30, abn: 40, bank: 20, address: 10 },
      threshold: 70,
    },
    employeeMasters: EMPLOYEE_MASTERS,
    postingDefaults: { ...DEFAULT_POSTING_DEFAULTS },
    teamExpensePosting: { ...DEFAULT_TEAM_EXPENSE_POSTING },
    documentSets: DEFAULT_DOCUMENT_SETS.map((set) => ({ ...set })),
  };
}

/** @deprecated Use createDefaultRuleBookConfig */
export const createInitialV4RuleBook = createDefaultRuleBookConfig;
