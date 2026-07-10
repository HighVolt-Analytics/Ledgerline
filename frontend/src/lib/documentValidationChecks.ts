/** Validation check catalogue — align with backend validation_rule_catalog.py */

import { extractionFieldLabel } from "@/lib/documentExtractionFields";

export type ValidationSeverity = "block" | "warn";

export type ValidationRuleConfig = {
  code: string;
  enabled: boolean;
  severity: ValidationSeverity;
};

export type CustomValidationOperator =
  | "present"
  | "absent"
  | "contains"
  | "not_contains"
  | "gte"
  | "lte";

export type CustomValidationRule = {
  id: string;
  name: string;
  field: string;
  operator: CustomValidationOperator;
  value: string;
  enabled: boolean;
  severity: ValidationSeverity;
};

export const UNIVERSAL_VALIDATION_CODE = "VR02";

/** All checks configurable per document type in Rule Book → Validation. */
export const CONFIGURABLE_VALIDATION_CHECKS = [
  { code: "VR03", label: "Compulsory fields", group: "Completeness" },
  { code: "VR08", label: "GST rate check", group: "Tax" },
  { code: "VR01", label: "Total = subtotal + tax", group: "Arithmetic" },
  { code: "VR09", label: "Line arithmetic", group: "Arithmetic" },
  { code: "VR11", label: "Date sanity", group: "Dates" },
  { code: "VR12", label: "Vendor master", group: "Vendor" },
  { code: "VR-PB02", label: "Required supporting documents", group: "Playbook" },
] as const;

export const VALIDATION_CHECK_DESCRIPTIONS: Record<string, string> = {
  VR02: "Exact, normalized, and fuzzy duplicate detection. Always on for the organisation.",
  VR03: "Uses starred fields from Extraction fields. When enabled, blocks approve and posting when any are missing.",
  VR08: "GST must match extracted tax rate × subtotal within tolerance.",
  VR01: "Total must equal subtotal plus tax.",
  VR09: "Line amounts must reconcile to subtotal; qty × price per line.",
  VR11: "Invoice date cannot be future; over 12 months needs approval.",
  VR12: "Vendor must exist in master; tax ID must match when present.",
  "VR-PB02":
    "Required supporting documents must be on file on the same PO or SO reference before posting. Configured under Supporting document requirements.",
};

export const CUSTOM_VALIDATION_OPERATORS: Array<{
  value: CustomValidationOperator;
  label: string;
}> = [
  { value: "present", label: "Field must be present" },
  { value: "absent", label: "Field must be absent" },
  { value: "contains", label: "Text must contain" },
  { value: "not_contains", label: "Text must not contain" },
  { value: "gte", label: "Number must be ≥" },
  { value: "lte", label: "Number must be ≤" },
];

const LABEL_BY_CODE = Object.fromEntries(
  [
    { code: UNIVERSAL_VALIDATION_CODE, label: "Duplicate check (multi-layer)" },
    ...CONFIGURABLE_VALIDATION_CHECKS,
  ].map((row) => [row.code, row.label])
) as Record<string, string>;

const CONFIGURABLE_CODES = new Set<string>(
  CONFIGURABLE_VALIDATION_CHECKS.map((row) => row.code)
);

const STANDARD_VALIDATION_RULES: ValidationRuleConfig[] = [
  { code: "VR03", enabled: true, severity: "block" },
  { code: "VR08", enabled: true, severity: "block" },
  { code: "VR01", enabled: true, severity: "block" },
  { code: "VR09", enabled: true, severity: "block" },
  { code: "VR11", enabled: true, severity: "block" },
  { code: "VR12", enabled: true, severity: "block" },
  { code: "VR-PB02", enabled: false, severity: "block" },
];

const PO_GOODS_VALIDATION_RULES: ValidationRuleConfig[] = [
  { code: "VR03", enabled: true, severity: "block" },
  { code: "VR08", enabled: true, severity: "block" },
  { code: "VR01", enabled: true, severity: "block" },
  { code: "VR09", enabled: true, severity: "block" },
  { code: "VR11", enabled: true, severity: "block" },
  { code: "VR12", enabled: true, severity: "block" },
  { code: "VR-PB02", enabled: true, severity: "block" },
];

const DIRECT_EXPENSE_RULES: ValidationRuleConfig[] = [
  { code: "VR03", enabled: true, severity: "block" },
  { code: "VR09", enabled: true, severity: "warn" },
  { code: "VR11", enabled: true, severity: "warn" },
  { code: "VR-PB02", enabled: false, severity: "block" },
];

export function validationCheckLabel(code: string): string {
  return LABEL_BY_CODE[code] ?? code;
}

export function validationCheckDescription(code: string): string {
  return VALIDATION_CHECK_DESCRIPTIONS[code] ?? "";
}

export function normalizeValidationRules(
  values: ValidationRuleConfig[] | null | undefined
): ValidationRuleConfig[] {
  const seen = new Set<string>();
  const out: ValidationRuleConfig[] = [];
  for (const row of values ?? []) {
    const code = row.code.trim().toUpperCase();
    if (!code || seen.has(code) || code === UNIVERSAL_VALIDATION_CODE) continue;
    if (!CONFIGURABLE_CODES.has(code)) continue;
    seen.add(code);
    out.push({
      code,
      enabled: row.enabled !== false,
      severity: row.severity === "warn" ? "warn" : "block",
    });
  }
  return out;
}

export function normalizeCustomValidationRules(
  values: CustomValidationRule[] | null | undefined
): CustomValidationRule[] {
  const seen = new Set<string>();
  const out: CustomValidationRule[] = [];
  for (const row of values ?? []) {
    const id = row.id?.trim();
    if (!id || seen.has(id)) continue;
    seen.add(id);
    out.push({
      id,
      name: row.name.trim() || "Custom rule",
      field: row.field.trim().toLowerCase(),
      operator: row.operator,
      value: row.value ?? "",
      enabled: row.enabled !== false,
      severity: row.severity === "warn" ? "warn" : "block",
    });
  }
  return out;
}

export function defaultValidationRulesForProfile(
  profile: string,
  _documentTypeCode = ""
): ValidationRuleConfig[] {
  const token = (profile || "").trim().toLowerCase();
  if (token === "po_goods") {
    return PO_GOODS_VALIDATION_RULES.map((row) => ({ ...row }));
  }
  if (profile === "direct_expense" || token === "direct_expense") {
    return DIRECT_EXPENSE_RULES.map((row) => ({ ...row }));
  }
  if (profile === "non_actionable" || token === "non_actionable") return [];
  return STANDARD_VALIDATION_RULES.map((row) => ({ ...row }));
}

export function mergeConfigurableRules(
  documentTypeCode: string,
  validationProfile: string,
  value: ValidationRuleConfig[]
): ValidationRuleConfig[] {
  const defaults = defaultValidationRulesForProfile(validationProfile, documentTypeCode);
  const byCode = new Map(value.map((row) => [row.code, row]));
  return CONFIGURABLE_VALIDATION_CHECKS.map(({ code }) => {
    const existing = byCode.get(code);
    const fallback = defaults.find((row) => row.code === code);
    return (
      existing ??
      fallback ?? {
        code,
        enabled: false,
        severity: "block" as const,
      }
    );
  });
}

export function effectiveValidationRules(docType: {
  code: string;
  validationProfile?: string;
  validationRules?: ValidationRuleConfig[];
}): ValidationRuleConfig[] {
  const explicit = normalizeValidationRules(docType.validationRules);
  if (explicit.length) {
    return mergeConfigurableRules(docType.code, docType.validationProfile ?? "", explicit);
  }
  return defaultValidationRulesForProfile(docType.validationProfile ?? "", docType.code);
}

export function customRuleSummary(rule: CustomValidationRule): string {
  const fieldLabel = extractionFieldLabel(rule.field);
  switch (rule.operator) {
    case "present":
      return `${fieldLabel} must be present`;
    case "absent":
      return `${fieldLabel} must be absent`;
    case "contains":
      return `${fieldLabel} must contain "${rule.value}"`;
    case "not_contains":
      return `${fieldLabel} must not contain "${rule.value}"`;
    case "gte":
      return `${fieldLabel} must be ≥ ${rule.value}`;
    case "lte":
      return `${fieldLabel} must be ≤ ${rule.value}`;
    default:
      return rule.name;
  }
}

export function newCustomValidationRule(): CustomValidationRule {
  return {
    id: `cv-${Date.now()}`,
    name: "Custom rule",
    field: "vendor",
    operator: "present",
    value: "",
    enabled: true,
    severity: "block",
  };
}

export function validationSummary(docType: {
  code: string;
  validationProfile?: string;
  validationRules?: ValidationRuleConfig[];
  customValidationRules?: CustomValidationRule[];
}): { standardActive: number; customActive: number } {
  const standardActive = effectiveValidationRules(docType).filter((row) => row.enabled).length;
  const customActive = normalizeCustomValidationRules(docType.customValidationRules).filter(
    (row) => row.enabled
  ).length;
  return { standardActive, customActive };
}
