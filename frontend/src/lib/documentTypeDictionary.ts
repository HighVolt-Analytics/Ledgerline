/**
 * Global document type dictionary (Industry Matrix) — adopt-time seed only.
 * Runtime must never read this file; org DT rows are self-contained after adopt.
 */

import dictionaryFile from "@/lib/document_type_dictionary.json";
import {
  resolveApprovalModeFromDictionary,
  resolveMatchModeFromDictionary,
  resolvePlaybookProfileFromDictionary,
  validateDictionaryEntries,
  type DictionaryValidationIssue,
} from "@/lib/documentDictionaryPolicyMapping";
import type { ApprovalMode, MatchMode, PlaybookProfile } from "@/lib/documentPlaybookConfig";
import type { ValidationRuleConfig, ValidationSeverity } from "@/lib/documentValidationChecks";
import type { DocumentTypeClass } from "@/lib/documentTypeKlass";
import type { CounterpartyType } from "@/lib/v5DocumentTypes";

export type DictionaryValidationCheckKey =
  | "gstRateCheck"
  | "totalReconciliation"
  | "lineArithmetic"
  | "dateSanity"
  | "vendorMaster"
  | "bankDetailsMatch"
  | "requiredSupportingDocs"
  | "customerMaster";

export type DictionaryValidationCheck = {
  check: DictionaryValidationCheckKey;
  label: string;
  enabled: boolean;
  severity: "Block" | "Warn" | "NA";
};

export type DictionaryEntry = {
  code: string;
  sourceRow: number;
  industry: string;
  masterClass: string;
  title: string;
  shortTitle: string;
  klass: DocumentTypeClass;
  posting: string;
  routeTarget: string;
  counterpartyType: CounterpartyType;
  enabled: boolean;
  recognitionMode: "prompt";
  llmPrompt: string;
  playbookProfile: string;
  matchMode: string;
  approvalMode: string;
  requireApprovalNoMatchEvidence: string;
  requireApprovalNewMaster: string;
  postTo: { ledger: string; subLedger: string };
  employeeSpendControls: { budgetControl: string; advanceControl: string };
  extractionFields: string[];
  compulsoryFields: { present: string; severity: "Block" | "Warn" | "NA" };
  validationChecks: DictionaryValidationCheck[];
  financeReview?: Record<string, unknown>;
  routingDecisionNote?: string;
  needsReview?: string[];
};

export type DocumentTypeDictionaryFile = {
  dictionaryVersion: number;
  entries: DictionaryEntry[];
};

const DICTIONARY = dictionaryFile as DocumentTypeDictionaryFile;

export const DICTIONARY_VERSION = DICTIONARY.dictionaryVersion ?? 1;

export const DICTIONARY_ENTRIES: DictionaryEntry[] = [...(DICTIONARY.entries ?? [])];

const DICTIONARY_VALIDATION_ISSUES = validateDictionaryEntries(DICTIONARY_ENTRIES);
if (DICTIONARY_VALIDATION_ISSUES.length > 0) {
  const preview = DICTIONARY_VALIDATION_ISSUES.slice(0, 5)
    .map((row) => `${row.code || "?"}: ${row.message}`)
    .join("; ");
  throw new Error(
    `Invalid document_type_dictionary.json (${DICTIONARY_VALIDATION_ISSUES.length} issues). ${preview}`
  );
}

export type { DictionaryValidationIssue };
export function getDictionaryValidationIssues(): DictionaryValidationIssue[] {
  return validateDictionaryEntries(DICTIONARY_ENTRIES);
}

export type DocumentTypeTemplateId = string | "custom";

export type DocumentTypeTemplate = {
  id: DocumentTypeTemplateId;
  label: string;
  description: string;
  dictionaryCode: string;
  industry: string;
  masterClass: string;
  routeTarget: string;
  klass: DocumentTypeClass;
  posting: string;
  playbookProfile: PlaybookProfile;
  counterpartyType: CounterpartyType;
  enabled: boolean;
  recognitionMode: "prompt";
  llmPrompt: string;
  matchMode: MatchMode;
  approvalMode: ApprovalMode;
  requireApprovalNoMatchEvidence: boolean;
  requireApprovalNewMaster: boolean;
  postTo: { ledger: string; subLedger: string };
  budgetControl: boolean;
  advanceControl: boolean;
  extractionFields: string[];
  compulsoryFieldsPresent: boolean;
  compulsoryFieldsSeverity: "Block" | "Warn" | "NA";
  validationRules: ValidationRuleConfig[];
};

const VR_BY_CHECK: Record<DictionaryValidationCheckKey, string> = {
  totalReconciliation: "VR01",
  gstRateCheck: "VR08",
  lineArithmetic: "VR09",
  dateSanity: "VR11",
  vendorMaster: "VR12",
  customerMaster: "VR12",
  bankDetailsMatch: "VR13",
  requiredSupportingDocs: "VR-PB02",
};

function yesNo(value: string | undefined): boolean {
  return (value ?? "").trim().toLowerCase() === "yes";
}

function naYes(value: string | undefined): boolean {
  const token = (value ?? "").trim().toLowerCase();
  return token === "yes";
}

function mapSeverity(value: string | undefined): ValidationSeverity {
  return (value ?? "").trim().toLowerCase() === "warn" ? "warn" : "block";
}

export function validationRulesFromDictionaryChecks(
  checks: DictionaryValidationCheck[] | undefined,
  entry: Pick<DictionaryEntry, "counterpartyType" | "routeTarget">
): ValidationRuleConfig[] {
  const byCode = new Map<string, ValidationRuleConfig>();
  for (const row of checks ?? []) {
    const checkKey = row.check;
    const code = VR_BY_CHECK[checkKey];
    if (!code) continue;
    if (checkKey === "vendorMaster" && entry.counterpartyType === "customer") continue;
    if (checkKey === "customerMaster" && entry.counterpartyType === "vendor") continue;
    if (checkKey === "customerMaster" && entry.counterpartyType === "none") continue;
    if (checkKey === "vendorMaster" && entry.counterpartyType === "none") continue;
    if (checkKey === "customerMaster" && entry.counterpartyType === "employee") continue;
    if (checkKey === "vendorMaster" && entry.counterpartyType === "employee") continue;
    const severity = row.severity === "NA" ? "block" : mapSeverity(row.severity);
    byCode.set(code, {
      code,
      enabled: row.enabled && row.severity !== "NA",
      severity,
    });
  }
  return [...byCode.values()];
}

function templateFromEntry(entry: DictionaryEntry): DocumentTypeTemplate {
  const code = entry.code.trim().toUpperCase();
  return {
    id: code,
    label: entry.title || entry.shortTitle,
    description: entry.title || entry.shortTitle,
    dictionaryCode: code,
    industry: entry.industry,
    masterClass: entry.masterClass,
    routeTarget: entry.routeTarget,
    klass: entry.klass,
    posting: entry.posting,
    playbookProfile: resolvePlaybookProfileFromDictionary(entry),
    counterpartyType: entry.counterpartyType,
    enabled: entry.enabled,
    recognitionMode: "prompt",
    llmPrompt: entry.llmPrompt,
    matchMode: resolveMatchModeFromDictionary(entry),
    approvalMode: resolveApprovalModeFromDictionary(entry),
    requireApprovalNoMatchEvidence: yesNo(entry.requireApprovalNoMatchEvidence),
    requireApprovalNewMaster: yesNo(entry.requireApprovalNewMaster),
    postTo: {
      ledger: entry.postTo?.ledger ?? "",
      subLedger: entry.postTo?.subLedger ?? "",
    },
    budgetControl: naYes(entry.employeeSpendControls?.budgetControl),
    advanceControl: naYes(entry.employeeSpendControls?.advanceControl),
    extractionFields: [...(entry.extractionFields ?? [])],
    compulsoryFieldsPresent: yesNo(entry.compulsoryFields?.present),
    compulsoryFieldsSeverity: entry.compulsoryFields?.severity ?? "NA",
    validationRules: validationRulesFromDictionaryChecks(entry.validationChecks, entry),
  };
}

export const DOCUMENT_TYPE_TEMPLATES: DocumentTypeTemplate[] = [
  ...DICTIONARY_ENTRIES.map(templateFromEntry),
  {
    id: "custom",
    label: "Custom type",
    description: "Blank type with recognition signals or prompt and processing sections.",
    dictionaryCode: "",
    industry: "",
    masterClass: "",
    routeTarget: "Vault",
    klass: "Non-transactional",
    posting: "No",
    playbookProfile: "standard_transactional",
    counterpartyType: "vendor",
    enabled: false,
    recognitionMode: "prompt",
    llmPrompt: "",
    matchMode: "none",
    approvalMode: "no_posting",
    requireApprovalNoMatchEvidence: false,
    requireApprovalNewMaster: false,
    postTo: { ledger: "", subLedger: "" },
    budgetControl: false,
    advanceControl: false,
    extractionFields: [],
    compulsoryFieldsPresent: false,
    compulsoryFieldsSeverity: "NA",
    validationRules: [],
  },
];

export function getDocumentTypeTemplate(id: DocumentTypeTemplateId): DocumentTypeTemplate {
  return DOCUMENT_TYPE_TEMPLATES.find((row) => row.id === id) ?? DOCUMENT_TYPE_TEMPLATES.at(-1)!;
}

export function dictionaryIndustries(): string[] {
  const values = new Set<string>();
  for (const entry of DICTIONARY_ENTRIES) {
    const token = entry.industry.trim();
    if (token) values.add(token);
  }
  return [...values].sort((a, b) => a.localeCompare(b));
}

export function dictionaryMasterClasses(): string[] {
  const values = new Set<string>();
  for (const entry of DICTIONARY_ENTRIES) {
    const token = entry.masterClass.trim();
    if (token) values.add(token);
  }
  return [...values].sort((a, b) => a.localeCompare(b));
}
