import type { ConditionOperator } from "./v4RuleBookTypes";
import {
  inferPlaybookProfileFromDefinition,
  playbookPresetForProfile,
} from "./documentPlaybookConfig";
import {
  DOCUMENT_TYPE_CLASSES,
  KLASS_NON_TRANSACTIONAL,
  derivePostingFromKlassAndProfile,
  type DocumentTypeClass,
} from "./documentTypeKlass";

export type { DocumentTypeClass };
export { DOCUMENT_TYPE_CLASSES };

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

/** Persisted metadata when sample files were analyzed in the Rule Book editor. */
export type DocumentTypeSampleAnalysis = {
  analyzedAt: string;
  filenames: string[];
  fileCount: number;
  appliedAt?: string;
  recognitionSignals: string[];
};

export type DocumentTypePostTo = {
  ledger: string;
  subLedger: string;
  taxAccount?: string;
  payableAccount?: string;
  receivableAccount?: string;
};

export function emptyDocumentTypePostTo(): DocumentTypePostTo {
  return {
    ledger: "",
    subLedger: "",
    taxAccount: "",
    payableAccount: "",
    receivableAccount: "",
  };
}

export type RecognitionMode = "signals" | "prompt";

/** Empty means auto: expense claim unless a catalogue DT pins advance requisition. */
export type DocumentTypeTeamExpenseKind =
  | ""
  | import("@/lib/v4RuleBookTypes").TeamExpenseKind;

export type V5DocumentType = {
  code: string;
  title: string;
  shortTitle: string;
  klass: DocumentTypeClass;
  posting: string;
  recognitionMode: RecognitionMode;
  recognitionSignals: string[];
  llmPrompt: string;
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
  salesBundleRole: import("@/lib/documentBundleConfig").SalesBundleRole;
  sampleAnalysis?: DocumentTypeSampleAnalysis;
  /** Shipped matrix template this org type was created from (e.g. DT-07). Org code is separate. */
  matrixTemplateCode?: string;
  teamExpenseKind: DocumentTypeTeamExpenseKind;
  /** When true, enforce employee-level budget availability for this DT. */
  budgetControl: boolean;
  /** When true, enforce employee-level advance availability for this DT. */
  advanceControl: boolean;
  postTo: DocumentTypePostTo;
};

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
    klass: KLASS_NON_TRANSACTIONAL,
    posting: "No",
    purchaseBundleRole: "",
    salesBundleRole: "",
    playbookProfile: "",
  } as DocumentTypeDefinition);
  const preset = playbookPresetForProfile(profile);
  const posting = derivePostingFromKlassAndProfile(KLASS_NON_TRANSACTIONAL, profile);
  return {
    code,
    title: "",
    shortTitle: "",
    klass: KLASS_NON_TRANSACTIONAL,
    posting,
    recognitionMode: "signals",
    recognitionSignals: [],
    llmPrompt: "",
    routeTarget: "Vault",
    enabled: false,
    classifier: {
      ...emptyDocumentClassifier(),
      enabled: false,
    },
    requiredFields: [],
    absentFields: [],
    minRouteConfidence: 0.75,
    validationProfile: "non_actionable",
    playbookProfile: profile,
    matchPolicy: { mode: preset.matchMode },
    approvalPolicy: { mode: preset.approvalMode },
    validationRules: [],
    customValidationRules: [],
    extractionFields: ["document_heading", "document_text"],
    extraction: [],
    checks: [],
    match: [],
    approval: [],
    accounting: [],
    special: [],
    bundleMandatory: [],
    bundleConditional: [],
    purchaseBundleRole: "",
    salesBundleRole: "",
    teamExpenseKind: "",
    budgetControl: false,
    advanceControl: false,
    postTo: emptyDocumentTypePostTo(),
  };
}
