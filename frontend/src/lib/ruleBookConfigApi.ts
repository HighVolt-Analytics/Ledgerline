import type { RuleBookConfig, RuleBookRulesPayload } from "@/api/types";
import type {
  EmployeeMaster,
  ExpenseRule,
  OrgContextConfig,
  PurchaseRule,
  SalesRule,
  RuleBookConfigState,
  RuleConditionGroup,
  TeamExpenseRule,
  CustomerMaster,
  VendorMaster,
} from "@/lib/v4RuleBookTypes";
import {
  emptyOrgContextConfig,
  INGEST_ACTION_ROUTE_PLACEHOLDER,
  ROUTE_TARGETS,
} from "@/lib/v4RuleBookTypes";
import { emptyDocumentClassifier, emptyDocumentTypePostTo, type DocumentTypeDefinition, type DocumentTypePostTo, type DocumentTypeSampleAnalysis } from "@/lib/v5DocumentTypes";
import {
  derivePostingFromKlassAndProfile,
  normalizeDocumentTypeIdentity,
  normalizeDocumentTypeKlass,
} from "@/lib/documentTypeKlass";
import type { ApprovalPolicy, PlaybookProfile } from "@/lib/documentPlaybookConfig";
import {
  inferPlaybookProfileFromDefinition,
  normalizeApprovalMode,
  normalizeMatchMode,
  playbookPresetForProfile,
  reconcileDocumentTypeDraft,
} from "@/lib/documentPlaybookConfig";
import { normalizeExtractionFieldKeys } from "@/lib/documentExtractionFields";
import {
  ensureExtractionSuperset,
  normalizeCompulsoryFields,
} from "@/lib/documentCompulsoryFields";
import type { PurchaseBundleRole, SalesBundleRole } from "@/lib/documentBundleConfig";
import { normalizeDtCodeList } from "@/lib/documentBundleConfig";
import { hydrateRecognitionFromClassifier } from "@/lib/documentTypeRecognition";
import {
  mergeConfigurableRules,
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

function mapSalesMatchOn(raw: Record<string, unknown>): SalesRule["matchOn"] {
  return {
    docNumberContains: raw.doc_number_contains as string | undefined,
    referenceContains: raw.reference_contains as string | undefined,
    descriptionContains: raw.description_contains as string | undefined,
    customerContains: raw.customer_contains as string | undefined,
  };
}

function salesMatchOnToApi(matchOn: SalesRule["matchOn"]): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  if (matchOn.docNumberContains != null) out.doc_number_contains = matchOn.docNumberContains;
  if (matchOn.referenceContains != null) out.reference_contains = matchOn.referenceContains;
  if (matchOn.descriptionContains != null) {
    out.description_contains = matchOn.descriptionContains;
  }
  if (matchOn.customerContains != null) out.customer_contains = matchOn.customerContains;
  return out;
}

function salesPostToToApi(postTo: SalesRule["postTo"]) {
  return {
    ledger: postTo.ledger,
    sub_ledger: postTo.subLedger,
    ...(postTo.taxAccount != null ? { tax_account: postTo.taxAccount } : {}),
    ...(postTo.receivableAccount != null
      ? { receivable_account: postTo.receivableAccount }
      : {}),
  };
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
  receivable_account?: string;
}) {
  return {
    ledger: raw.ledger,
    subLedger: raw.sub_ledger ?? "",
    taxAccount: raw.tax_account,
    payableAccount: raw.payable_account,
    receivableAccount: raw.receivable_account,
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

function mapDocumentTypePostTo(raw: Record<string, unknown> | undefined): DocumentTypePostTo {
  if (!raw) return emptyDocumentTypePostTo();
  return {
    ledger: String(raw.ledger ?? ""),
    subLedger: String(raw.sub_ledger ?? raw.subLedger ?? ""),
    taxAccount: raw.tax_account != null ? String(raw.tax_account) : raw.taxAccount != null ? String(raw.taxAccount) : "",
    payableAccount:
      raw.payable_account != null
        ? String(raw.payable_account)
        : raw.payableAccount != null
          ? String(raw.payableAccount)
          : "",
    receivableAccount:
      raw.receivable_account != null
        ? String(raw.receivable_account)
        : raw.receivableAccount != null
          ? String(raw.receivableAccount)
          : "",
  };
}

function documentTypePostToToApi(
  postTo: DocumentTypePostTo
): NonNullable<RuleBookRulesPayload["document_types"][number]["post_to"]> {
  const out: NonNullable<RuleBookRulesPayload["document_types"][number]["post_to"]> = {
    ledger: postTo.ledger,
    sub_ledger: postTo.subLedger,
  };
  if (postTo.taxAccount?.trim()) out.tax_account = postTo.taxAccount.trim();
  if (postTo.payableAccount?.trim()) out.payable_account = postTo.payableAccount.trim();
  if (postTo.receivableAccount?.trim()) out.receivable_account = postTo.receivableAccount.trim();
  return out;
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

export function mapCustomer(raw: Record<string, unknown>): CustomerMaster {
  const billing = (raw.billing_address ?? {}) as Record<string, string>;
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
    defaultLedger: String(raw.default_ledger ?? ""),
    defaultSubLedger: String(raw.default_sub_ledger ?? ""),
    paymentTerms: String(raw.payment_terms ?? ""),
    status: String(raw.status ?? ""),
    registeredOn: String(raw.registered_on ?? ""),
    totalRevenueYTD: Number(raw.total_revenue_ytd ?? 0),
    invoiceCount: Number(raw.invoice_count ?? 0),
    matchConfidence: Number(raw.match_confidence ?? 0),
  };
}

export function customerToApi(customer: CustomerMaster): Record<string, unknown> {
  return {
    id: customer.id,
    name: customer.name,
    aliases: customer.aliases,
    abn: customer.abn,
    billing_address: {
      street: customer.billingAddress.street,
      suburb: customer.billingAddress.suburb,
      postcode: customer.billingAddress.postcode,
      country: customer.billingAddress.country,
    },
    default_ledger: customer.defaultLedger,
    default_sub_ledger: customer.defaultSubLedger,
    payment_terms: customer.paymentTerms,
    status: customer.status,
    registered_on: customer.registeredOn,
    total_revenue_ytd: customer.totalRevenueYTD,
    invoice_count: customer.invoiceCount,
    match_confidence: customer.matchConfidence,
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

function mapSalesBundleRole(raw: Record<string, unknown>): SalesBundleRole {
  const token = String(raw.sales_bundle_role ?? raw.salesBundleRole ?? "")
    .trim()
    .toLowerCase();
  return (token === "so" || token === "dn" ? token : "") as SalesBundleRole;
}

function inferPlaybookProfileFromRaw(raw: Record<string, unknown>): PlaybookProfile {
  const explicit = String(raw.playbook_profile ?? raw.playbookProfile ?? "").trim().toLowerCase();
  if (explicit) return explicit as PlaybookProfile;
  return inferPlaybookProfileFromDefinition({
    code: String(raw.code ?? raw.dt_code ?? ""),
    klass: raw.klass as DocumentTypeDefinition["klass"],
    posting: String(raw.posting ?? "No"),
    purchaseBundleRole: mapPurchaseBundleRole(raw),
    salesBundleRole: mapSalesBundleRole(raw),
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

function approvalPolicyFromApi(
  raw: Record<string, unknown> | undefined,
  defaultMode: ApprovalPolicy["mode"]
): ApprovalPolicy {
  const mode = normalizeApprovalMode(
    raw?.mode ? String(raw.mode) : undefined,
    defaultMode
  );
  const autoRaw = raw?.auto_approve_below ?? raw?.autoApproveBelow;
  const autoApproveBelow =
    autoRaw === null || autoRaw === undefined || autoRaw === ""
      ? null
      : Number(autoRaw);
  return {
    mode,
    autoApproveBelow: Number.isFinite(autoApproveBelow) ? autoApproveBelow : null,
    requireApprovalForUnmatched: Boolean(
      raw?.require_approval_for_unmatched ?? raw?.requireApprovalForUnmatched ?? false
    ),
    requireApprovalForUnverifiedCounterparty: Boolean(
      raw?.require_approval_for_unverified_counterparty ??
        raw?.requireApprovalForUnverifiedCounterparty ??
        false
    ),
  };
}

function approvalPolicyToApi(policy: ApprovalPolicy): {
  mode: string;
  auto_approve_below?: number;
  require_approval_for_unmatched?: boolean;
  require_approval_for_unverified_counterparty?: boolean;
} {
  const payload: {
    mode: string;
    auto_approve_below?: number;
    require_approval_for_unmatched?: boolean;
    require_approval_for_unverified_counterparty?: boolean;
  } = { mode: policy.mode };
  if (policy.autoApproveBelow != null && Number.isFinite(policy.autoApproveBelow)) {
    payload.auto_approve_below = policy.autoApproveBelow;
  }
  if (policy.requireApprovalForUnmatched) {
    payload.require_approval_for_unmatched = true;
  }
  if (policy.requireApprovalForUnverifiedCounterparty) {
    payload.require_approval_for_unverified_counterparty = true;
  }
  return payload;
}

function mapDocumentType(raw: Record<string, unknown>): DocumentTypeDefinition {
  const extractionFields = normalizeExtractionFieldKeys(
    (raw.extraction_fields ?? raw.extractionFields ?? []) as string[]
  );
  const requiredFields = normalizeCompulsoryFields(
    (raw.required_fields ?? raw.requiredFields ?? []) as string[],
    extractionFields
  );
  const playbookProfile = inferPlaybookProfileFromRaw(raw);
  const preset = playbookPresetForProfile(playbookProfile);
  const rawApproval = (raw.approval_policy ?? raw.approvalPolicy) as
    | Record<string, unknown>
    | undefined;
  const rawMatchMode = (raw.match_policy as { mode?: string } | undefined)?.mode;
  const klass = normalizeDocumentTypeKlass(String(raw.klass ?? ""));
  const posting = derivePostingFromKlassAndProfile(
    klass,
    String(raw.playbook_profile ?? raw.playbookProfile ?? playbookProfile),
    String(raw.posting ?? "No")
  );
  return reconcileDocumentTypeDraft(
    hydrateRecognitionFromClassifier({
      code: String(raw.code),
      title: String(raw.title),
      shortTitle: String(raw.short_title ?? raw.shortTitle ?? ""),
      klass,
      posting,
      recognitionMode:
        String(raw.recognition_mode ?? raw.recognitionMode ?? "signals").toLowerCase() === "prompt"
          ? "prompt"
          : "signals",
      recognitionSignals: (() => {
        const rawSignals = raw.recognition_signals ?? raw.recognitionSignals;
        return Array.isArray(rawSignals)
          ? rawSignals.map((item: unknown) => String(item))
          : [];
      })(),
      llmPrompt: String(
        raw.llm_prompt ??
          raw.llmPrompt ??
          raw.llm_hint ??
          raw.llmHint ??
          raw.one_line ??
          raw.oneLine ??
          ""
      ),
      routeTarget: String(raw.route_target ?? raw.routeTarget ?? ROUTE_TARGETS[3]),
      enabled: raw.enabled !== false,
      classifier: mapClassifier(raw.classifier as Record<string, unknown> | undefined),
      requiredFields,
      absentFields: (raw.absent_fields ?? raw.absentFields ?? []) as string[],
      minRouteConfidence: Number(raw.min_route_confidence ?? raw.minRouteConfidence ?? 0.65),
      validationProfile: String(raw.validation_profile ?? raw.validationProfile ?? ""),
      playbookProfile: String(raw.playbook_profile ?? raw.playbookProfile ?? "") || playbookProfile,
      matchPolicy: {
        mode: normalizeMatchMode(rawMatchMode ? String(rawMatchMode) : undefined, preset.matchMode),
      },
      approvalPolicy: approvalPolicyFromApi(rawApproval, preset.approvalMode),
      validationRules: mergeConfigurableRules(
        String(raw.code),
        String(raw.validation_profile ?? raw.validationProfile ?? ""),
        normalizeValidationRules(
          (raw.validation_rules ?? raw.validationRules ?? []) as ValidationRuleConfig[]
        )
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
      salesBundleRole: mapSalesBundleRole(raw),
      sampleAnalysis: mapSampleAnalysis(raw),
      matrixTemplateCode: String(raw.matrix_template_code ?? raw.matrixTemplateCode ?? ""),
      postTo: mapDocumentTypePostTo(
        (raw.post_to ?? raw.postTo) as Record<string, unknown> | undefined
      ),
    })
  );
}

function documentTypeToApi(
  docType: DocumentTypeDefinition
): RuleBookRulesPayload["document_types"][number] {
  const reconciled = reconcileDocumentTypeDraft(docType);
  const extractionFields = ensureExtractionSuperset(
    reconciled.requiredFields,
    reconciled.extractionFields
  );
  const requiredFields = normalizeCompulsoryFields(reconciled.requiredFields, extractionFields);
  const identity = normalizeDocumentTypeIdentity(reconciled);
  return {
    code: reconciled.code,
    title: reconciled.title,
    short_title: reconciled.shortTitle,
    klass: identity.klass,
    posting: identity.posting,
    recognition_mode: reconciled.recognitionMode,
    recognition_signals: reconciled.recognitionSignals,
    llm_prompt: reconciled.llmPrompt,
    route_target: reconciled.routeTarget,
    enabled: reconciled.enabled,
    classifier: {
      enabled: reconciled.classifier.enabled,
      priority: reconciled.classifier.priority,
      confidence: reconciled.classifier.confidence,
      root: conditionGroupToApi(
        reconciled.classifier.root as unknown as RuleConditionGroup
      ),
    },
    required_fields: requiredFields,
    absent_fields: reconciled.absentFields,
    ...(reconciled.minRouteConfidence != null
      ? { min_route_confidence: reconciled.minRouteConfidence }
      : {}),
    validation_profile: reconciled.validationProfile || undefined,
    playbook_profile: reconciled.playbookProfile || undefined,
    match_policy: { mode: reconciled.matchPolicy.mode },
    approval_policy: approvalPolicyToApi(reconciled.approvalPolicy),
    validation_rules: reconciled.validationRules.map((row) => ({
      code: row.code,
      enabled: row.enabled,
      severity: row.severity,
    })),
    custom_validation_rules: reconciled.customValidationRules.map((row) => ({
      id: row.id,
      name: row.name,
      field: row.field,
      operator: row.operator,
      value: row.value,
      enabled: row.enabled,
      severity: row.severity,
    })),
    extraction_fields: extractionFields,
    extraction: [],
    checks: [],
    match: [],
    approval: [],
    accounting: [],
    special: [],
    bundle_mandatory: normalizeDtCodeList(reconciled.bundleMandatory),
    bundle_conditional: reconciled.bundleConditional,
    ...(reconciled.purchaseBundleRole
      ? { purchase_bundle_role: reconciled.purchaseBundleRole }
      : {}),
    ...(reconciled.salesBundleRole ? { sales_bundle_role: reconciled.salesBundleRole } : {}),
    ...(reconciled.matrixTemplateCode
      ? { matrix_template_code: reconciled.matrixTemplateCode }
      : {}),
    ...(reconciled.sampleAnalysis
      ? {
          sample_analysis: {
            analyzed_at: reconciled.sampleAnalysis.analyzedAt,
            filenames: reconciled.sampleAnalysis.filenames,
            file_count: reconciled.sampleAnalysis.fileCount,
            ...(reconciled.sampleAnalysis.appliedAt
              ? { applied_at: reconciled.sampleAnalysis.appliedAt }
              : {}),
            recognition_signals: reconciled.sampleAnalysis.recognitionSignals,
          },
        }
      : {}),
    post_to: documentTypePostToToApi(reconciled.postTo),
  };
}

export function documentTypeDefinitionToApi(
  docType: DocumentTypeDefinition
): RuleBookRulesPayload["document_types"][number] {
  return documentTypeToApi(docType);
}

function normalizeOrgPerspective(value: string | undefined): OrgContextConfig["defaultPerspective"] {
  const token = (value ?? "buyer").trim().toLowerCase();
  if (token === "seller" || token === "mixed") return token;
  return "buyer";
}

function mapOrgContextFromApi(raw: RuleBookConfig["org_context"] | undefined): OrgContextConfig {
  if (!raw) return emptyOrgContextConfig();
  return {
    legalName: raw.legal_name ?? "",
    abn: raw.abn ?? "",
    aliases: [...(raw.aliases ?? [])],
    defaultPerspective: normalizeOrgPerspective(raw.default_perspective),
    intakeSummary: raw.intake_summary ?? "",
    classificationHints: raw.classification_hints ?? "",
  };
}

function orgContextToApi(org: OrgContextConfig | undefined): RuleBookRulesPayload["org_context"] {
  const value = org ?? emptyOrgContextConfig();
  return {
    legal_name: value.legalName,
    abn: value.abn,
    aliases: [...value.aliases],
    default_perspective: value.defaultPerspective,
    intake_summary: value.intakeSummary,
    classification_hints: value.classificationHints,
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
    aiClassification: {
      documentAiProvider:
        (api.ai_classification?.document_ai_provider as
          | "azure_di"
          | "azure_foundry_vision"
          | "gemini_vision") ?? "azure_di",
      autoRouteMinConfidence: api.ai_classification?.auto_route_min_confidence ?? 0.85,
    },
    orgContext: mapOrgContextFromApi(api.org_context),
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
    salesRules: (api.sales_rules ?? []).map((rule, index) => ({
      id: rule.id,
      name: rule.name,
      enabled: rule.enabled,
      priority: rule.priority ?? 100 + index * 10,
      matchOn: mapSalesMatchOn(rule.match_on),
      postTo: {
        ledger: rule.post_to.ledger,
        subLedger: rule.post_to.sub_ledger,
        taxAccount: rule.post_to.tax_account,
        receivableAccount: rule.post_to.receivable_account,
      },
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
      receivableAccount: api.posting_defaults?.receivable_account ?? "Accounts Receivable",
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
    ai_classification: {
      document_ai_provider: state.aiClassification?.documentAiProvider ?? "azure_di",
      auto_route_min_confidence: state.aiClassification?.autoRouteMinConfidence ?? 0.85,
    },
    org_context: orgContextToApi(state.orgContext),
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
    sales_rules: state.salesRules.map((rule) => ({
      id: rule.id,
      name: rule.name,
      enabled: rule.enabled,
      priority: rule.priority ?? 100,
      match_on: salesMatchOnToApi(rule.matchOn),
      post_to: salesPostToToApi(rule.postTo),
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
      receivable_account: state.postingDefaults.receivableAccount,
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
