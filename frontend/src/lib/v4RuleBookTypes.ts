import type { DocumentTypeDefinition } from "./v5DocumentTypes";

export type EmailField =
  | "from"
  | "to"
  | "subject"
  | "body"
  | "attachment_name"
  | "attachment_mime";

export type ConditionOperator =
  | "equals"
  | "not_equals"
  | "contains"
  | "not_contains"
  | "starts_with"
  | "ends_with"
  | "regex";

export type RuleCondition = {
  type: "condition";
  field: EmailField;
  operator: ConditionOperator;
  value: string;
  caseSensitive?: boolean;
};

export type RuleConditionGroup = {
  type: "group";
  operator: "AND" | "OR";
  children: Array<RuleCondition | RuleConditionGroup>;
};

export type EmailCaptureRule = {
  id: string;
  name: string;
  enabled: boolean;
  priority: number;
  mailbox: string;
  root: RuleConditionGroup;
  action: {
    saveAttachment: boolean;
    routeTo: string;
    tags: string[];
  };
  matchedCount: number;
  lastMatched: string;
};

export type PostToAccounts = {
  ledger: string;
  subLedger: string;
  taxAccount?: string;
  payableAccount?: string;
};

export type PurchaseRule = {
  id: string;
  name: string;
  enabled: boolean;
  priority?: number;
  matchOn: {
    poPrefix?: string;
    poRegex?: string;
    vendorContains?: string;
    grnLinkedToPo?: boolean;
    invoiceReferencesPo?: boolean;
  };
  postTo: PostToAccounts;
  matchedCount: number;
};

export type ExpenseRule = {
  id: string;
  name: string;
  enabled: boolean;
  priority?: number;
  matchOn: {
    docNumberContains?: string;
    referenceContains?: string;
    descriptionContains?: string;
    vendorContains?: string;
  };
  postTo: { ledger: string; subLedger: string };
  matchedCount: number;
};

export type SalesRule = {
  id: string;
  name: string;
  enabled: boolean;
  priority?: number;
  matchOn: {
    docNumberContains?: string;
    referenceContains?: string;
    descriptionContains?: string;
    customerContains?: string;
  };
  postTo: {
    ledger: string;
    subLedger: string;
    taxAccount?: string;
    receivableAccount?: string;
  };
  matchedCount: number;
};

export type TeamExpenseRule = {
  id: string;
  name: string;
  enabled: boolean;
  priority?: number;
  matchOn: {
    descriptionContains?: string;
    merchantContains?: string;
    channelEquals?: string;
    amountMin?: number;
    amountMax?: number;
  };
  postTo: { ledger: string; subLedger: string };
  policy: {
    requireReceipt: boolean;
    receiptThreshold: number;
    autoApproveBelow: number;
  };
  matchedCount: number;
};

export type CustomerMaster = {
  id: string;
  name: string;
  aliases: string[];
  abn: string;
  billingAddress: {
    street: string;
    suburb: string;
    postcode: string;
    country: string;
  };
  defaultLedger: string;
  defaultSubLedger: string;
  paymentTerms: string;
  status: string;
  registeredOn: string;
  totalRevenueYTD: number;
  invoiceCount: number;
  matchConfidence: number;
};

export type VendorMaster = {
  id: string;
  name: string;
  aliases: string[];
  abn: string;
  billingAddress: {
    street: string;
    suburb: string;
    postcode: string;
    country: string;
  };
  bank: {
    bsb?: string;
    accountNumber: string;
    accountName: string;
    bankName: string;
    swift?: string;
    iban?: string;
  };
  defaultLedger: string;
  defaultSubLedger: string;
  paymentTerms: string;
  status: string;
  registeredOn: string;
  totalSpendYTD: number;
  invoiceCount: number;
  matchConfidence: number;
};

export type VendorDetectionConfig = {
  weights: { name: number; abn: number; bank: number; address: number };
  threshold: number;
};

export type EmployeeMaster = {
  id: string;
  name: string;
  role: string;
  email: string;
  whatsappNumber: string;
  whatsappNumber2?: string;
  viberNumber?: string;
  dateOfJoining?: string;
  department?: string;
  location?: string;
  division?: string;
  supervisor1?: string;
  supervisor2?: string;
  bank: {
    bsb?: string;
    accountNumber: string;
    accountName: string;
    bankName: string;
    swift?: string;
    iban?: string;
  };
  budget: {
    monthly: number;
    quarterly: number;
    annual: number;
    categories: Array<{ ledger: string; cap: number }>;
  };
  advanceParentLedger: string;
  advanceSubLedger: string;
  /** Live Staff Advance child balance from journals (read-only). */
  advanceBalance?: number;
  ytdSpent: number;
  mtdSpent: number;
  qtdSpent: number;
  claimCount: number;
  lastClaim: string;
  status: string;
};

export type SampleEmail = {
  id: string;
  from: string;
  to: string;
  subject: string;
  body: string;
  attachment_name: string;
  attachment_mime: string;
};

export type PurchaseDocumentType = "po" | "grn" | "invoice";

export type EvalDocument = {
  id: string;
  docNumber: string;
  invoice_no: string;
  vendor: string;
  abn?: string;
  address?: string;
  bankBsb?: string;
  bankAccount?: string;
  po?: string;
  primaryAccount: string;
  lines: Array<{ description: string }>;
  documentType?: PurchaseDocumentType;
};

export type DocumentSetRule = {
  id: string;
  pattern: string;
  setName: string;
  isolated?: boolean;
};

export type PostingDefaults = {
  taxAccount: string;
  payableAccount: string;
  receivableAccount: string;
  fallbackAccount: string;
};

export type TeamExpensePostingDefaults = {
  defaultAdvanceParentLedger: string;
  settlementAccount: string;
};

export const TEAM_EXPENSE_KINDS = [
  "expense_claim",
  "advance_requisition",
  "expense_against_advance",
] as const;

export type TeamExpenseKind = (typeof TEAM_EXPENSE_KINDS)[number];

export const TEAM_EXPENSE_KIND_LABELS: Record<TeamExpenseKind, string> = {
  expense_claim: "Expense claim",
  advance_requisition: "Advance requisition",
  expense_against_advance: "Expense against advance",
};

export type { DocumentTypeDefinition } from "./v5DocumentTypes";

export type DocumentClassificationConfig = {
  unclassifiedDocumentTypeCode: string;
  unclassifiedMinConfidence: number;
};

export type AiClassificationConfig = {
  documentAiProvider: "azure_di" | "azure_foundry_vision" | "gemini_vision" | "claude_vision";
  autoRouteMinConfidence: number;
};

export type OrgContextConfig = {
  legalName: string;
  abn: string;
  aliases: string[];
  defaultPerspective: "buyer" | "seller" | "mixed";
  intakeSummary: string;
  classificationHints: string;
};

export const emptyOrgContextConfig = (): OrgContextConfig => ({
  legalName: "",
  abn: "",
  aliases: [],
  defaultPerspective: "buyer",
  intakeSummary: "",
  classificationHints: "",
});

/** In-app rule book state (camelCase). Persisted via /api/rule-book/config. */
export type RuleBookConfigState = {
  documentTypes: DocumentTypeDefinition[];
  documentClassification: DocumentClassificationConfig;
  aiClassification: AiClassificationConfig;
  orgContext: OrgContextConfig;
  emailCaptureRules: EmailCaptureRule[];
  purchaseRules: PurchaseRule[];
  salesRules: SalesRule[];
  expenseRules: ExpenseRule[];
  teamExpenseRules: TeamExpenseRule[];
  vendorMasters: VendorMaster[];
  vendorDetectionConfig: VendorDetectionConfig;
  employeeMasters: EmployeeMaster[];
  postingDefaults: PostingDefaults;
  teamExpensePosting: TeamExpensePostingDefaults;
  documentSets: DocumentSetRule[];
};

/** @deprecated Use RuleBookConfigState */
export type V4RuleBookState = RuleBookConfigState;

export const ROUTE_TARGETS = [
  "Purchase Management",
  "Sales Management",
  "Expenses Management",
  "Team Expenses",
  "Vault",
] as const;

export const TEAM_CHANNELS = ["Any", "WhatsApp", "Viber", "Mobile", "Web"] as const;

export const INGEST_ACTION_ROUTE_PLACEHOLDER = "Purchase Management";
