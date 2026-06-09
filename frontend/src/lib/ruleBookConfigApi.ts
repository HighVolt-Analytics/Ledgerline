import type { RuleBookConfig, RuleBookRulesPayload } from "@/api/types";
import type {
  EmployeeMaster,
  ExpenseRule,
  PurchaseRule,
  RuleBookConfigState,
  RuleConditionGroup,
  TeamExpenseRule,
  VendorMaster,
} from "@/lib/v4RuleBookTypes";

function mapConditionGroup(root: Record<string, unknown>): RuleConditionGroup {
  return root as unknown as RuleConditionGroup;
}

function conditionGroupToApi(root: RuleConditionGroup): Record<string, unknown> {
  return root as unknown as Record<string, unknown>;
}

function mapPurchaseMatchOn(raw: Record<string, unknown>): PurchaseRule["matchOn"] {
  return {
    poPrefix: raw.po_prefix as string | undefined,
    poRegex: raw.po_regex as string | undefined,
    vendorContains: raw.vendor_contains as string | undefined,
    grnLinkedToPo: raw.grn_linked_to_po as boolean | undefined,
    invoiceReferencesPo: raw.invoice_references_po as boolean | undefined,
  };
}

function purchaseMatchOnToApi(matchOn: PurchaseRule["matchOn"]): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  if (matchOn.poPrefix != null) out.po_prefix = matchOn.poPrefix;
  if (matchOn.poRegex != null) out.po_regex = matchOn.poRegex;
  if (matchOn.vendorContains != null) out.vendor_contains = matchOn.vendorContains;
  if (matchOn.grnLinkedToPo != null) out.grn_linked_to_po = matchOn.grnLinkedToPo;
  if (matchOn.invoiceReferencesPo != null) {
    out.invoice_references_po = matchOn.invoiceReferencesPo;
  }
  return out;
}

function mapExpenseMatchOn(raw: Record<string, unknown>): ExpenseRule["matchOn"] {
  return {
    docNumberContains: raw.doc_number_contains as string | undefined,
    referenceContains: raw.reference_contains as string | undefined,
    descriptionContains: raw.description_contains as string | undefined,
    vendorContains: raw.vendor_contains as string | undefined,
  };
}

function expenseMatchOnToApi(matchOn: ExpenseRule["matchOn"]): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  if (matchOn.docNumberContains != null) out.doc_number_contains = matchOn.docNumberContains;
  if (matchOn.referenceContains != null) out.reference_contains = matchOn.referenceContains;
  if (matchOn.descriptionContains != null) {
    out.description_contains = matchOn.descriptionContains;
  }
  if (matchOn.vendorContains != null) out.vendor_contains = matchOn.vendorContains;
  return out;
}

function mapTeamMatchOn(raw: Record<string, unknown>): TeamExpenseRule["matchOn"] {
  return {
    descriptionContains: raw.description_contains as string | undefined,
    merchantContains: raw.merchant_contains as string | undefined,
    channelEquals: raw.channel_equals as string | undefined,
    amountMin: raw.amount_min as number | undefined,
    amountMax: raw.amount_max as number | undefined,
  };
}

function teamMatchOnToApi(matchOn: TeamExpenseRule["matchOn"]): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  if (matchOn.descriptionContains != null) {
    out.description_contains = matchOn.descriptionContains;
  }
  if (matchOn.merchantContains != null) out.merchant_contains = matchOn.merchantContains;
  if (matchOn.channelEquals != null) out.channel_equals = matchOn.channelEquals;
  if (matchOn.amountMin != null) out.amount_min = matchOn.amountMin;
  if (matchOn.amountMax != null) out.amount_max = matchOn.amountMax;
  return out;
}

function mapPostTo(raw: {
  ledger: string;
  sub_ledger: string;
  tax_account?: string;
  payable_account?: string;
}) {
  return {
    ledger: raw.ledger,
    subLedger: raw.sub_ledger ?? "",
    taxAccount: raw.tax_account,
    payableAccount: raw.payable_account,
  };
}

function postToToApi(postTo: PurchaseRule["postTo"]) {
  return {
    ledger: postTo.ledger,
    sub_ledger: postTo.subLedger,
    ...(postTo.taxAccount != null ? { tax_account: postTo.taxAccount } : {}),
    ...(postTo.payableAccount != null ? { payable_account: postTo.payableAccount } : {}),
  };
}

export function mapVendor(raw: Record<string, unknown>): VendorMaster {
  const billing = (raw.billing_address ?? {}) as Record<string, string>;
  const bank = (raw.bank ?? {}) as Record<string, string | undefined>;
  return {
    id: String(raw.id),
    name: String(raw.name),
    aliases: (raw.aliases as string[]) ?? [],
    abn: String(raw.abn ?? ""),
    billingAddress: {
      street: billing.street ?? "",
      suburb: billing.suburb ?? "",
      postcode: billing.postcode ?? "",
      country: billing.country ?? "",
    },
    bank: {
      bsb: bank.bsb,
      accountNumber: bank.account_number ?? "",
      accountName: bank.account_name ?? "",
      bankName: bank.bank_name ?? "",
      swift: bank.swift,
      iban: bank.iban,
    },
    defaultLedger: String(raw.default_ledger ?? ""),
    defaultSubLedger: String(raw.default_sub_ledger ?? ""),
    paymentTerms: String(raw.payment_terms ?? ""),
    status: String(raw.status ?? ""),
    registeredOn: String(raw.registered_on ?? ""),
    totalSpendYTD: Number(raw.total_spend_ytd ?? 0),
    invoiceCount: Number(raw.invoice_count ?? 0),
    matchConfidence: Number(raw.match_confidence ?? 0),
  };
}

export function vendorToApi(vendor: VendorMaster): Record<string, unknown> {
  return {
    id: vendor.id,
    name: vendor.name,
    aliases: vendor.aliases,
    abn: vendor.abn,
    billing_address: {
      street: vendor.billingAddress.street,
      suburb: vendor.billingAddress.suburb,
      postcode: vendor.billingAddress.postcode,
      country: vendor.billingAddress.country,
    },
    bank: {
      ...(vendor.bank.bsb != null ? { bsb: vendor.bank.bsb } : {}),
      account_number: vendor.bank.accountNumber,
      account_name: vendor.bank.accountName,
      bank_name: vendor.bank.bankName,
      ...(vendor.bank.swift != null ? { swift: vendor.bank.swift } : {}),
      ...(vendor.bank.iban != null ? { iban: vendor.bank.iban } : {}),
    },
    default_ledger: vendor.defaultLedger,
    default_sub_ledger: vendor.defaultSubLedger,
    payment_terms: vendor.paymentTerms,
    status: vendor.status,
    registered_on: vendor.registeredOn,
    total_spend_ytd: vendor.totalSpendYTD,
    invoice_count: vendor.invoiceCount,
    match_confidence: vendor.matchConfidence,
  };
}

export function mapEmployee(raw: Record<string, unknown>): EmployeeMaster {
  const bank = (raw.bank ?? {}) as Record<string, string | undefined>;
  const budget = (raw.budget ?? {}) as {
    monthly?: number;
    quarterly?: number;
    annual?: number;
    categories?: Array<{ ledger: string; cap: number }>;
  };
  return {
    id: String(raw.id),
    name: String(raw.name),
    role: String(raw.role ?? ""),
    email: String(raw.email ?? ""),
    whatsappNumber: String(raw.whatsapp_number ?? ""),
    viberNumber: raw.viber_number as string | undefined,
    bank: {
      bsb: bank.bsb,
      accountNumber: bank.account_number ?? "",
      accountName: bank.account_name ?? "",
      bankName: bank.bank_name ?? "",
      swift: bank.swift,
      iban: bank.iban,
    },
    budget: {
      monthly: Number(budget.monthly ?? 0),
      quarterly: Number(budget.quarterly ?? 0),
      annual: Number(budget.annual ?? 0),
      categories: budget.categories ?? [],
    },
    ytdSpent: Number(raw.ytd_spent ?? 0),
    mtdSpent: Number(raw.mtd_spent ?? 0),
    qtdSpent: Number(raw.qtd_spent ?? 0),
    claimCount: Number(raw.claim_count ?? 0),
    lastClaim: String(raw.last_claim ?? ""),
    status: String(raw.status ?? ""),
  };
}

export function employeeToApi(employee: EmployeeMaster): Record<string, unknown> {
  return {
    id: employee.id,
    name: employee.name,
    role: employee.role,
    email: employee.email,
    whatsapp_number: employee.whatsappNumber,
    ...(employee.viberNumber != null ? { viber_number: employee.viberNumber } : {}),
    bank: {
      ...(employee.bank.bsb != null ? { bsb: employee.bank.bsb } : {}),
      account_number: employee.bank.accountNumber,
      account_name: employee.bank.accountName,
      bank_name: employee.bank.bankName,
      ...(employee.bank.swift != null ? { swift: employee.bank.swift } : {}),
      ...(employee.bank.iban != null ? { iban: employee.bank.iban } : {}),
    },
    budget: employee.budget,
    ytd_spent: employee.ytdSpent,
    mtd_spent: employee.mtdSpent,
    qtd_spent: employee.qtdSpent,
    claim_count: employee.claimCount,
    last_claim: employee.lastClaim,
    status: employee.status,
  };
}

export function ruleBookConfigFromApi(api: RuleBookConfig): RuleBookConfigState {
  return {
    emailCaptureRules: api.email_capture_rules.map((rule) => ({
      id: rule.id,
      name: rule.name,
      enabled: rule.enabled,
      priority: rule.priority,
      mailbox: rule.mailbox,
      root: mapConditionGroup(rule.root),
      action: {
        saveAttachment: rule.action.save_attachment,
        routeTo: rule.action.route_to,
        tags: rule.action.tags,
      },
      matchedCount: rule.matched_count,
      lastMatched: rule.last_matched,
    })),
    purchaseRules: api.purchase_rules.map((rule) => ({
      id: rule.id,
      name: rule.name,
      enabled: rule.enabled,
      matchOn: mapPurchaseMatchOn(rule.match_on),
      postTo: mapPostTo(rule.post_to),
      matchedCount: rule.matched_count,
    })),
    expenseRules: api.expense_rules.map((rule) => ({
      id: rule.id,
      name: rule.name,
      enabled: rule.enabled,
      matchOn: mapExpenseMatchOn(rule.match_on),
      postTo: {
        ledger: rule.post_to.ledger,
        subLedger: rule.post_to.sub_ledger,
      },
      matchedCount: rule.matched_count,
    })),
    teamExpenseRules: api.team_expense_rules.map((rule) => ({
      id: rule.id,
      name: rule.name,
      enabled: rule.enabled,
      matchOn: mapTeamMatchOn(rule.match_on),
      postTo: {
        ledger: rule.post_to.ledger,
        subLedger: rule.post_to.sub_ledger,
      },
      policy: {
        requireReceipt: rule.policy.require_receipt,
        receiptThreshold: rule.policy.receipt_threshold,
        autoApproveBelow: rule.policy.auto_approve_below,
      },
      matchedCount: rule.matched_count,
    })),
    vendorMasters: api.vendor_masters.map(mapVendor),
    vendorDetectionConfig: {
      weights: api.vendor_detection_config.weights,
      threshold: api.vendor_detection_config.threshold,
    },
    employeeMasters: api.employee_masters.map(mapEmployee),
    postingDefaults: {
      taxAccount: api.posting_defaults?.tax_account ?? "GST Paid",
      payableAccount: api.posting_defaults?.payable_account ?? "Accounts Payable",
      fallbackAccount: api.posting_defaults?.fallback_account ?? "Suspense Account",
    },
    documentSets: (api.document_sets ?? []).map((set) => ({
      id: set.id,
      pattern: set.pattern,
      setName: set.set_name,
      isolated: set.isolated,
    })),
  };
}

export function ruleBookConfigToApi(state: RuleBookConfigState): RuleBookRulesPayload {
  return {
    schema_version: 1,
    email_capture_rules: state.emailCaptureRules.map((rule) => ({
      id: rule.id,
      name: rule.name,
      enabled: rule.enabled,
      priority: rule.priority,
      mailbox: rule.mailbox,
      root: conditionGroupToApi(rule.root),
      action: {
        save_attachment: rule.action.saveAttachment,
        route_to: rule.action.routeTo,
        tags: rule.action.tags,
      },
      matched_count: rule.matchedCount,
      last_matched: rule.lastMatched,
    })),
    purchase_rules: state.purchaseRules.map((rule) => ({
      id: rule.id,
      name: rule.name,
      enabled: rule.enabled,
      match_on: purchaseMatchOnToApi(rule.matchOn),
      post_to: postToToApi(rule.postTo),
      matched_count: rule.matchedCount,
    })),
    expense_rules: state.expenseRules.map((rule) => ({
      id: rule.id,
      name: rule.name,
      enabled: rule.enabled,
      match_on: expenseMatchOnToApi(rule.matchOn),
      post_to: {
        ledger: rule.postTo.ledger,
        sub_ledger: rule.postTo.subLedger,
      },
      matched_count: rule.matchedCount,
    })),
    team_expense_rules: state.teamExpenseRules.map((rule) => ({
      id: rule.id,
      name: rule.name,
      enabled: rule.enabled,
      match_on: teamMatchOnToApi(rule.matchOn),
      post_to: {
        ledger: rule.postTo.ledger,
        sub_ledger: rule.postTo.subLedger,
      },
      policy: {
        require_receipt: rule.policy.requireReceipt,
        receipt_threshold: rule.policy.receiptThreshold,
        auto_approve_below: rule.policy.autoApproveBelow,
      },
      matched_count: rule.matchedCount,
    })),
    vendor_detection_config: {
      weights: state.vendorDetectionConfig.weights,
      threshold: state.vendorDetectionConfig.threshold,
    },
    posting_defaults: {
      tax_account: state.postingDefaults.taxAccount,
      payable_account: state.postingDefaults.payableAccount,
      fallback_account: state.postingDefaults.fallbackAccount,
    },
    document_sets: state.documentSets.map((set) => ({
      id: set.id,
      pattern: set.pattern,
      set_name: set.setName,
      ...(set.isolated != null ? { isolated: set.isolated } : {}),
    })),
  };
}
