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
import { INGEST_ACTION_ROUTE_PLACEHOLDER, ROUTE_TARGETS } from "@/lib/v4RuleBookTypes";
import { emptyDocumentClassifier, type DocumentTypeDefinition, type DocumentTypeSampleAnalysis } from "@/lib/v5DocumentTypes";
import type { ApprovalMode, MatchMode, PlaybookProfile } from "@/lib/documentPlaybookConfig";
import {
  inferPlaybookProfileFromDefinition,
  playbookPresetForProfile,
} from "@/lib/documentPlaybookConfig";
import { normalizeExtractionFieldKeys } from "@/lib/documentExtractionFields";
import type { PurchaseBundleRole } from "@/lib/documentBundleConfig";
import { normalizeDtCodeList } from "@/lib/documentBundleConfig";
import {
  normalizeValidationRules,
  normalizeCustomValidationRules,
  type CustomValidationRule,
  type ValidationRuleConfig,
} from "@/lib/documentValidationChecks";

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

function mapClassifier(raw: Record<string, unknown> | undefined) {
  if (!raw) return emptyDocumentClassifier();
  return {
    enabled: raw.enabled === true,
    priority: Number(raw.priority ?? 100),
    confidence: Number(raw.confidence ?? 0.85),
    root: mapConditionGroup((raw.root ?? emptyDocumentClassifier().root) as Record<string, unknown>),
  };
}

function mapPurchaseBundleRole(raw: Record<string, unknown>): PurchaseBundleRole {
  const token = String(raw.purchase_bundle_role ?? raw.purchaseBundleRole ?? "")
    .trim()
    .toLowerCase();
  return (token === "po" || token === "grn" ? token : "") as PurchaseBundleRole;
}

function inferPlaybookProfileFromRaw(raw: Record<string, unknown>): PlaybookProfile {
  const explicit = String(raw.playbook_profile ?? raw.playbookProfile ?? "").trim().toLowerCase();
  if (explicit) return explicit as PlaybookProfile;
  return inferPlaybookProfileFromDefinition({
    klass: raw.klass as DocumentTypeDefinition["klass"],
    posting: String(raw.posting ?? "No"),
    purchaseBundleRole: mapPurchaseBundleRole(raw),
    playbookProfile: "",
  });
}

function mapSampleAnalysis(
  raw: Record<string, unknown> | undefined
): DocumentTypeSampleAnalysis | undefined {
  const row = (raw?.sample_analysis ?? raw?.sampleAnalysis) as Record<string, unknown> | undefined;
  if (!row || typeof row !== "object") return undefined;
  const analyzedAt = String(row.analyzed_at ?? row.analyzedAt ?? "").trim();
  if (!analyzedAt) return undefined;
  const filenames = (row.filenames ?? []) as string[];
  return {
    analyzedAt,
    filenames: Array.isArray(filenames) ? filenames.map(String) : [],
    fileCount: Number(row.file_count ?? row.fileCount ?? filenames.length) || 0,
    appliedAt: row.applied_at
      ? String(row.applied_at)
      : row.appliedAt
        ? String(row.appliedAt)
        : undefined,
    recognitionSignals: (
      (row.recognition_signals ?? row.recognitionSignals ?? []) as string[]
    ).map(String),
  };
}

function mapDocumentType(raw: Record<string, unknown>): DocumentTypeDefinition {
  const extractionFields = normalizeExtractionFieldKeys(
    (raw.extraction_fields ?? raw.extractionFields ?? []) as string[]
  );
  const playbookProfile = inferPlaybookProfileFromRaw(raw);
  const preset = playbookPresetForProfile(playbookProfile);
  const rawMatchMode = (raw.match_policy as { mode?: string } | undefined)?.mode;
  const rawApprovalMode = (raw.approval_policy as { mode?: string } | undefined)?.mode;
  return {
    code: String(raw.code),
    title: String(raw.title),
    shortTitle: String(raw.short_title ?? raw.shortTitle ?? ""),
    klass: raw.klass as DocumentTypeDefinition["klass"],
    posting: String(raw.posting ?? "No"),
    fraudRisk: (raw.fraud_risk ?? raw.fraudRisk ?? "low") as DocumentTypeDefinition["fraudRisk"],
    oneLine: String(raw.one_line ?? raw.oneLine ?? ""),
    routeTarget: String(raw.route_target ?? raw.routeTarget ?? ROUTE_TARGETS[3]),
    enabled: raw.enabled !== false,
    classifier: mapClassifier(raw.classifier as Record<string, unknown> | undefined),
    classifierCustomized: Boolean(raw.classifier_customized ?? raw.classifierCustomized),
    requiredFields: extractionFields,
    absentFields: (raw.absent_fields ?? raw.absentFields ?? []) as string[],
    minRouteConfidence: Number(raw.min_route_confidence ?? raw.minRouteConfidence ?? 0.65),
    validationProfile: String(raw.validation_profile ?? raw.validationProfile ?? ""),
    playbookProfile: String(raw.playbook_profile ?? raw.playbookProfile ?? "") || playbookProfile,
    matchPolicy: {
      mode: (rawMatchMode ? String(rawMatchMode) : preset.matchMode) as MatchMode,
    },
    approvalPolicy: {
      mode: (rawApprovalMode ? String(rawApprovalMode) : preset.approvalMode) as ApprovalMode,
    },
    validationRules: normalizeValidationRules(
      (raw.validation_rules ?? raw.validationRules ?? []) as ValidationRuleConfig[]
    ),
    customValidationRules: normalizeCustomValidationRules(
      (raw.custom_validation_rules ?? raw.customValidationRules ?? []) as CustomValidationRule[]
    ),
    extractionFields,
    extraction: [],
    checks: [],
    match: [],
    approval: [],
    accounting: [],
    special: [],
    bundleMandatory: normalizeDtCodeList(
      (raw.bundle_mandatory ?? raw.bundleMandatory ?? []) as string[]
    ),
    bundleConditional: (raw.bundle_conditional ?? raw.bundleConditional ?? []) as string[],
    purchaseBundleRole: mapPurchaseBundleRole(raw),
    sampleAnalysis: mapSampleAnalysis(raw),
  };
}

function documentTypeToApi(
  docType: DocumentTypeDefinition
): RuleBookRulesPayload["document_types"][number] {
  return {
    code: docType.code,
    title: docType.title,
    short_title: docType.shortTitle,
    klass: docType.klass,
    posting: docType.posting,
    fraud_risk: docType.fraudRisk,
    one_line: docType.oneLine,
    route_target: docType.routeTarget,
    enabled: docType.enabled,
    classifier: {
      enabled: docType.classifier.enabled,
      priority: docType.classifier.priority,
      confidence: docType.classifier.confidence,
      root: conditionGroupToApi(
        docType.classifier.root as unknown as RuleConditionGroup
      ),
    },
    ...(docType.classifierCustomized ? { classifier_customized: true } : {}),
    required_fields: docType.extractionFields,
    absent_fields: docType.absentFields,
    ...(docType.minRouteConfidence != null
      ? { min_route_confidence: docType.minRouteConfidence }
      : {}),
    validation_profile: docType.validationProfile || undefined,
    playbook_profile: docType.playbookProfile || undefined,
    match_policy: { mode: docType.matchPolicy.mode },
    approval_policy: { mode: docType.approvalPolicy.mode },
    validation_rules: docType.validationRules.map((row) => ({
      code: row.code,
      enabled: row.enabled,
      severity: row.severity,
    })),
    custom_validation_rules: docType.customValidationRules.map((row) => ({
      id: row.id,
      name: row.name,
      field: row.field,
      operator: row.operator,
      value: row.value,
      enabled: row.enabled,
      severity: row.severity,
    })),
    extraction_fields: docType.extractionFields,
    extraction: [],
    checks: [],
    match: [],
    approval: [],
    accounting: [],
    special: [],
    bundle_mandatory: normalizeDtCodeList(docType.bundleMandatory),
    bundle_conditional: docType.bundleConditional,
    ...(docType.purchaseBundleRole
      ? { purchase_bundle_role: docType.purchaseBundleRole }
      : {}),
    ...(docType.sampleAnalysis
      ? {
          sample_analysis: {
            analyzed_at: docType.sampleAnalysis.analyzedAt,
            filenames: docType.sampleAnalysis.filenames,
            file_count: docType.sampleAnalysis.fileCount,
            ...(docType.sampleAnalysis.appliedAt
              ? { applied_at: docType.sampleAnalysis.appliedAt }
              : {}),
            recognition_signals: docType.sampleAnalysis.recognitionSignals,
          },
        }
      : {}),
  };
}

export function ruleBookConfigFromApi(api: RuleBookConfig): RuleBookConfigState {
  return {
    documentTypes: (api.document_types ?? []).map((row) =>
      mapDocumentType(row as unknown as Record<string, unknown>)
    ),
    documentClassification: {
      unclassifiedDocumentTypeCode:
        api.document_classification?.unclassified_document_type_code ?? "",
      unclassifiedMinConfidence:
        api.document_classification?.unclassified_min_confidence ?? 0.45,
    },
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
      matchedCount: rule.matched_count ?? 0,
      lastMatched: rule.last_matched ?? "—",
    })),
    purchaseRules: api.purchase_rules.map((rule, index) => ({
      id: rule.id,
      name: rule.name,
      enabled: rule.enabled,
      priority: rule.priority ?? 100 + index * 10,
      matchOn: mapPurchaseMatchOn(rule.match_on),
      postTo: mapPostTo(rule.post_to),
      matchedCount: rule.matched_count,
    })),
    expenseRules: api.expense_rules.map((rule, index) => ({
      id: rule.id,
      name: rule.name,
      enabled: rule.enabled,
      priority: rule.priority ?? 100 + index * 10,
      matchOn: mapExpenseMatchOn(rule.match_on),
      postTo: {
        ledger: rule.post_to.ledger,
        subLedger: rule.post_to.sub_ledger,
      },
      matchedCount: rule.matched_count,
    })),
    teamExpenseRules: api.team_expense_rules.map((rule, index) => ({
      id: rule.id,
      name: rule.name,
      enabled: rule.enabled,
      priority: rule.priority ?? 100 + index * 10,
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
    document_classification: {
      unclassified_document_type_code:
        state.documentClassification?.unclassifiedDocumentTypeCode ?? "",
      unclassified_min_confidence:
        state.documentClassification?.unclassifiedMinConfidence ?? 0.45,
    },
    document_types: state.documentTypes.map(documentTypeToApi),
    email_capture_rules: state.emailCaptureRules.map((rule) => ({
      id: rule.id,
      name: rule.name,
      enabled: rule.enabled,
      priority: rule.priority,
      mailbox: rule.mailbox,
      root: conditionGroupToApi(rule.root),
      action: {
        save_attachment: rule.action.saveAttachment,
        route_to: rule.action.routeTo || INGEST_ACTION_ROUTE_PLACEHOLDER,
        tags: rule.action.tags,
      },
    })),
    purchase_rules: state.purchaseRules.map((rule) => ({
      id: rule.id,
      name: rule.name,
      enabled: rule.enabled,
      priority: rule.priority ?? 100,
      match_on: purchaseMatchOnToApi(rule.matchOn),
      post_to: postToToApi(rule.postTo),
      matched_count: rule.matchedCount,
    })),
    expense_rules: state.expenseRules.map((rule) => ({
      id: rule.id,
      name: rule.name,
      enabled: rule.enabled,
      priority: rule.priority ?? 100,
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
      priority: rule.priority ?? 100,
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
