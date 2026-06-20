import type { ConditionOperator } from "./v4RuleBookTypes";
import {
  emptyApprovalPolicy,
  emptyMatchPolicy,
  inferPlaybookProfileFromDefinition,
  playbookPresetForProfile,
} from "./documentPlaybookConfig";
export type DocumentTypeFraudRisk = "low" | "medium" | "high" | "critical";

export type DocumentTypeClass =
  | "Transactional"
  | "Pre-transactional"
  | "Supporting"
  | "Reconciliation"
  | "Master-data"
  | "Compliance"
  | "Informational"
  | "Non-actionable";

export type DocumentRuleCondition = {
  type: "condition";
  field: string;
  operator: ConditionOperator;
  value: string;
  caseSensitive?: boolean;
};

export type DocumentRuleConditionGroup = {
  type: "group";
  operator: "AND" | "OR";
  children: Array<DocumentRuleCondition | DocumentRuleConditionGroup>;
};

export type DocumentTypeClassifier = {
  enabled: boolean;
  priority: number;
  confidence: number;
  root: DocumentRuleConditionGroup;
};

export type V5DocumentType = {
  code: string;
  title: string;
  shortTitle: string;
  klass: DocumentTypeClass;
  posting: string;
  fraudRisk: DocumentTypeFraudRisk;
  oneLine: string;
  routeTarget: string;
  enabled: boolean;
  classifier: DocumentTypeClassifier;
  requiredFields: string[];
  absentFields: string[];
  minRouteConfidence: number;
  validationProfile: string;
  playbookProfile: string;
  matchPolicy: import("@/lib/documentPlaybookConfig").MatchPolicy;
  approvalPolicy: import("@/lib/documentPlaybookConfig").ApprovalPolicy;
  validationRules: import("@/lib/documentValidationChecks").ValidationRuleConfig[];
  customValidationRules: import("@/lib/documentValidationChecks").CustomValidationRule[];
  extractionFields: string[];
  extraction: string[];
  checks: string[];
  match: string[];
  approval: string[];
  accounting: string[];
  special: string[];
  bundleMandatory: string[];
  bundleConditional: string[];
  purchaseBundleRole: import("@/lib/documentBundleConfig").PurchaseBundleRole;
  classifierCustomized?: boolean;
  /** Shipped matrix template this org type was created from (e.g. DT-07). Org code is separate. */
  matrixTemplateCode?: string;
};

export const DOCUMENT_TYPE_CLASSES: Array<"all" | DocumentTypeClass> = [
  "all",
  "Transactional",
  "Pre-transactional",
  "Supporting",
  "Reconciliation",
  "Master-data",
  "Compliance",
  "Informational",
  "Non-actionable",
];

export type DocumentTypeDefinition = V5DocumentType;

export function emptyDocumentClassifier(): DocumentTypeClassifier {
  return {
    enabled: false,
    priority: 100,
    confidence: 0.85,
    root: { type: "group", operator: "AND", children: [] },
  };
}

/** Next org catalogue code (DT-01, DT-02, …) based on existing org types only. */
export function nextOrgDocumentTypeCode(existing: DocumentTypeDefinition[]): string {
  const numbers = existing
    .map((row) => Number.parseInt(row.code.replace(/\D/g, ""), 10))
    .filter((value) => Number.isFinite(value));
  const next = numbers.length ? Math.max(...numbers) + 1 : 1;
  return `DT-${String(next).padStart(2, "0")}`;
}

/** Blank card template for the Rule Book editor (org catalogue is API-backed). */
export function createBlankDocumentType(existing: DocumentTypeDefinition[]): DocumentTypeDefinition {
  const code = nextOrgDocumentTypeCode(existing);
  const profile = inferPlaybookProfileFromDefinition({
    klass: "Transactional",
    posting: "No",
    purchaseBundleRole: "",
  } as DocumentTypeDefinition);
  const preset = playbookPresetForProfile(profile);
  return {
    code,
    title: "New document type",
    shortTitle: "New type",
    klass: "Transactional",
    posting: "No",
    fraudRisk: "low",
    oneLine: "Describe how this document type is identified and processed.",
    routeTarget: "Vault",
    enabled: true,
    classifier: emptyDocumentClassifier(),
    requiredFields: [],
    absentFields: [],
    minRouteConfidence: 0.65,
    validationProfile: "",
    playbookProfile: profile,
    matchPolicy: { mode: preset.matchMode },
    approvalPolicy: { mode: preset.approvalMode },
    validationRules: [],
    customValidationRules: [],
    extractionFields: [],
    extraction: [],
    checks: [],
    match: [],
    approval: [],
    accounting: [],
    special: [],
    bundleMandatory: [],
    bundleConditional: [],
    purchaseBundleRole: "",
  };
}
