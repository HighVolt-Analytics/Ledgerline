/**
 * User-friendly match/exclude rules compiled to classifier.root (AND/OR tree).
 */

import type { ConditionOperator } from "@/lib/v4RuleBookTypes";
import type { ChartOfAccountRow } from "@/api/types";
import { hasValidPostTo } from "@/lib/documentTypePostToValidation";
import type {
  DocumentRuleCondition,
  DocumentRuleConditionGroup,
  DocumentTypePostTo,
} from "@/lib/v5DocumentTypes";
import { emptyDocumentTypePostTo } from "@/lib/v5DocumentTypes";
import { parseSignalsFromClassifier } from "@/lib/documentClassifierBuilder";
import {
  extractionFieldLabel,
  normalizeExtractionFieldKeys,
} from "@/lib/documentExtractionFields";
import { allRecognitionSignalOptions } from "@/lib/documentTypeTemplateMeta";
import {
  allRecognitionSignalIds,
  getRecognitionSignalCatalog,
} from "@/lib/recognitionSignalCatalog";

export type MatchRuleMode = "any" | "all";

export type MatchRuleRow = {
  field: string;
  operator: ConditionOperator;
  value: string;
};

export type MatchRulesForm = {
  matchMode: MatchRuleMode;
  matchRules: MatchRuleRow[];
  excludeMode: MatchRuleMode;
  excludeRules: MatchRuleRow[];
};

export type MatchRuleFieldDef = {
  key: string;
  label: string;
  description?: string;
};

export type MatchRuleFieldGroup = {
  id: string;
  label: string;
  fields: MatchRuleFieldDef[];
};

/** Sentinel value when user picks "Custom field name" in the field dropdown. */
export const CUSTOM_MATCH_RULE_FIELD = "__custom__";

/** Grouped fields for match/exclude rules — aligned with backend `_document_field`. */
export const MATCH_RULE_FIELD_GROUPS: MatchRuleFieldGroup[] = [
  {
    id: "document",
    label: "Document & OCR",
    fields: [
      { key: "document_heading", label: "Document heading", description: "Title at top of page" },
      { key: "document_text", label: "Document text (OCR)", description: "Full OCR body text" },
      { key: "line_text", label: "Line item text", description: "Combined line descriptions" },
      { key: "attachment_name", label: "Attachment name", description: "Uploaded file name" },
      { key: "attachment_extension", label: "File extension", description: "pdf, png, xlsx, …" },
    ],
  },
  {
    id: "email",
    label: "Email & channel",
    fields: [
      { key: "email_sender", label: "Email sender", description: "From address or phone" },
      { key: "email_subject", label: "Email subject" },
      {
        key: "capture_channel",
        label: "Capture channel",
        description: "email, mob, or unknown",
      },
    ],
  },
  {
    id: "extracted",
    label: "Extracted values",
    fields: [
      { key: "vendor", label: "Vendor" },
      { key: "abn", label: "Tax ID / ABN" },
      { key: "invoice_no", label: "Invoice number" },
      { key: "po_reference", label: "PO reference" },
      { key: "invoice_date", label: "Invoice date", description: "ISO date when extracted" },
      { key: "due_date", label: "Due date" },
      { key: "total", label: "Total amount" },
      { key: "subtotal", label: "Subtotal" },
      { key: "gst", label: "Tax (GST/VAT)" },
      { key: "currency", label: "Currency", description: "e.g. AUD, USD" },
    ],
  },
  {
    id: "address",
    label: "Address & account",
    fields: [
      { key: "billing_address", label: "Billing address" },
      { key: "cost_centre", label: "Cost centre" },
      { key: "account_code", label: "Account code" },
      { key: "account_name", label: "Account name" },
      { key: "bank_details", label: "Bank details", description: "BSB + account when present" },
    ],
  },
  {
    id: "checks",
    label: "Automatic checks",
    fields: [
      { key: "has_po_reference", label: "Has PO reference" },
      { key: "has_invoice_no", label: "Has invoice number" },
      { key: "has_total", label: "Has total amount" },
      { key: "has_abn", label: "Has tax ID / ABN" },
      { key: "has_vendor", label: "Has vendor" },
      { key: "has_invoice_date", label: "Has invoice date" },
      { key: "has_due_date", label: "Has due date" },
      { key: "has_subtotal", label: "Has subtotal" },
      { key: "has_gst", label: "Has tax amount" },
      { key: "has_billing_address", label: "Has billing address" },
      { key: "has_bank_details", label: "Has bank details" },
      { key: "has_line_items", label: "Has line items" },
      { key: "has_cost_centre", label: "Has cost centre" },
      { key: "has_heading_invoice", label: "Heading is tax invoice" },
      { key: "has_heading_grn", label: "Heading is GRN / delivery" },
      { key: "has_heading_po", label: "Heading is purchase order" },
      { key: "has_heading_so", label: "Heading is sales order" },
      { key: "has_heading_credit_note", label: "Heading is credit note" },
      { key: "has_heading_quote", label: "Heading is quote" },
      { key: "has_heading_contract", label: "Heading is contract" },
      { key: "is_commercial_invoice", label: "Is commercial invoice" },
    ],
  },
];

export const MATCH_RULE_FIELDS = MATCH_RULE_FIELD_GROUPS.flatMap((group) =>
  group.fields.map(({ key, label }) => ({ key, label }))
);

const KNOWN_MATCH_RULE_FIELD_KEYS = new Set(MATCH_RULE_FIELDS.map((field) => field.key));

export function isKnownMatchRuleField(key: string): boolean {
  return KNOWN_MATCH_RULE_FIELD_KEYS.has(key.trim());
}

/** Build dropdown groups, appending this document type's custom extraction fields. */
export function matchRuleFieldGroupsForDocumentType(
  extractionFields: string[] | undefined
): MatchRuleFieldGroup[] {
  const known = KNOWN_MATCH_RULE_FIELD_KEYS;
  const customKeys = normalizeExtractionFieldKeys(extractionFields).filter((key) => !known.has(key));
  if (!customKeys.length) return MATCH_RULE_FIELD_GROUPS;
  return [
    ...MATCH_RULE_FIELD_GROUPS,
    {
      id: "custom",
      label: "Your document fields",
      fields: customKeys.map((key) => ({
        key,
        label: extractionFieldLabel(key),
        description: "Custom field from extraction config",
      })),
    },
  ];
}

const MATCH_RULE_FIELD_BY_KEY = Object.fromEntries(
  MATCH_RULE_FIELD_GROUPS.flatMap((group) =>
    group.fields.map((field) => [field.key, field])
  )
) as Record<string, MatchRuleFieldDef>;

export function matchRuleFieldLabel(key: string): string {
  return MATCH_RULE_FIELD_BY_KEY[key]?.label ?? extractionFieldLabel(key);
}

export const BOOLEAN_FIELDS = new Set([
  "has_po_reference",
  "has_invoice_no",
  "has_total",
  "has_abn",
  "has_vendor",
  "has_invoice_date",
  "has_due_date",
  "has_subtotal",
  "has_gst",
  "has_billing_address",
  "has_bank_details",
  "has_line_items",
  "has_cost_centre",
  "has_heading_invoice",
  "has_heading_grn",
  "has_heading_po",
  "has_heading_so",
  "has_heading_credit_note",
  "has_heading_quote",
  "has_heading_contract",
  "is_commercial_invoice",
]);

/** Heading presence flags — exclude from absentFields derivation (not extraction scalars). */
const HEADING_PRESENCE_FIELDS = new Set([
  "has_heading_invoice",
  "has_heading_grn",
  "has_heading_po",
  "has_heading_so",
  "has_heading_credit_note",
  "has_heading_quote",
  "has_heading_contract",
  "is_commercial_invoice",
]);

/**
 * Map Recognition exclude rules (Has … is true) to post-OCR absent field keys.
 * Used when simple match/exclude rules are saved — advanced classifier trees keep seeded defaults.
 */
export function absentFieldsFromExcludeRules(rules: MatchRuleRow[]): string[] {
  const keys = new Set<string>();
  for (const row of rules) {
    const field = row.field.trim();
    if (!field || HEADING_PRESENCE_FIELDS.has(field)) continue;
    if (!isMatchRuleBooleanField(field)) continue;
    if (row.operator !== "equals" || row.value !== "true") continue;
    if (field.startsWith("has_")) {
      keys.add(field.slice(4));
    }
  }
  return [...keys].sort();
}

/** Presence checks: preset booleans or has_<custom_field>. */
export function isMatchRuleBooleanField(field: string): boolean {
  const key = field.trim();
  if (!key) return false;
  if (BOOLEAN_FIELDS.has(key)) return true;
  return /^has_[a-z][a-z0-9_]*$/.test(key);
}

export const TEXT_OPERATORS: { key: ConditionOperator; label: string }[] = [
  { key: "contains", label: "contains" },
  { key: "not_contains", label: "does not contain" },
  { key: "equals", label: "equals" },
  { key: "not_equals", label: "does not equal" },
  { key: "starts_with", label: "starts with" },
  { key: "ends_with", label: "ends with" },
];

export const BOOLEAN_OPERATORS: { key: ConditionOperator; label: string }[] = [
  { key: "equals", label: "is" },
];

export function emptyMatchRulesForm(): MatchRulesForm {
  return {
    matchMode: "any",
    matchRules: [],
    excludeMode: "any",
    excludeRules: [],
  };
}

function cond(field: string, operator: ConditionOperator, value: string): DocumentRuleCondition {
  return { type: "condition", field, operator, value };
}

function group(
  operator: "AND" | "OR",
  children: Array<DocumentRuleCondition | DocumentRuleConditionGroup>
): DocumentRuleConditionGroup {
  return { type: "group", operator, children };
}

function isBooleanField(field: string): boolean {
  return isMatchRuleBooleanField(field);
}

function normalizeRuleRow(row: MatchRuleRow): DocumentRuleCondition | null {
  const field = row.field.trim();
  if (!field) return null;
  if (isBooleanField(field)) {
    const truthy = row.value !== "false" && row.value !== "0";
    return cond(field, "equals", truthy ? "true" : "false");
  }
  const value = row.value.trim();
  if (!value && row.operator !== "equals" && row.operator !== "not_equals") {
    return null;
  }
  return cond(field, row.operator, value);
}

function compileRuleList(
  rules: MatchRuleRow[],
  mode: MatchRuleMode
): DocumentRuleConditionGroup | DocumentRuleCondition | null {
  const leaves = rules
    .map(normalizeRuleRow)
    .filter((c): c is DocumentRuleCondition => c !== null);
  if (leaves.length === 0) return null;
  if (leaves.length === 1) return leaves[0];
  return group(mode === "all" ? "AND" : "OR", leaves);
}

/** Exclusions: ANY exclusion match fails the type; ALL exclusions must match to fail. */
function compileExcludeGroup(
  rules: MatchRuleRow[],
  mode: MatchRuleMode
): DocumentRuleConditionGroup | null {
  const leaves = rules
    .map(normalizeRuleRow)
    .filter((c): c is DocumentRuleCondition => c !== null)
    .map((c) => invertCondition(c));
  if (leaves.length === 0) return null;
  if (mode === "any") {
    // NOT (A OR B) = (NOT A) AND (NOT B)
    return group("AND", leaves);
  }
  // NOT (A AND B) = (NOT A) OR (NOT B)
  if (leaves.length === 1) return group("AND", leaves);
  return group("OR", leaves);
}

function invertCondition(c: DocumentRuleCondition): DocumentRuleCondition {
  if (isBooleanField(c.field)) {
    const flipped = c.value === "true" ? "false" : "true";
    return cond(c.field, "equals", flipped);
  }
  const invertOp: Partial<Record<ConditionOperator, ConditionOperator>> = {
    equals: "not_equals",
    not_equals: "equals",
    contains: "not_contains",
    not_contains: "contains",
  };
  const op = invertOp[c.operator] ?? c.operator;
  return cond(c.field, op, c.value);
}

export function compileMatchRulesToClassifier(form: MatchRulesForm): DocumentRuleConditionGroup {
  const matchPart = compileRuleList(form.matchRules, form.matchMode);
  const excludePart = compileExcludeGroup(form.excludeRules, form.excludeMode);

  if (matchPart && excludePart) {
    return group("AND", [matchPart, excludePart]);
  }
  if (matchPart) {
    return matchPart.type === "group" ? matchPart : group("AND", [matchPart]);
  }
  if (excludePart) {
    return excludePart;
  }
  return { type: "group", operator: "AND", children: [] };
}

/** Merge editable UI form into a document type for save / recognition test. */
export function documentTypeWithMatchRulesForm(
  draft: import("@/lib/v5DocumentTypes").DocumentTypeDefinition,
  form: MatchRulesForm
) {
  return {
    ...draft,
    enabled: true,
    classifierCustomized: false,
    absentFields: absentFieldsFromExcludeRules(form.excludeRules),
    classifier: {
      ...draft.classifier,
      enabled: true,
      root: compileMatchRulesToClassifier(form),
    },
  };
}

export function defaultMatchRulesForm(): MatchRulesForm {
  return {
    ...emptyMatchRulesForm(),
    matchRules: [{ field: "document_heading", operator: "contains", value: "" }],
  };
}

export function matchRulesFormFromClassifier(
  root: DocumentRuleConditionGroup
): MatchRulesForm {
  const parsed = parseClassifierToMatchRules(root);
  if (parsed.form.matchRules.length || parsed.form.excludeRules.length) {
    return parsed.form;
  }
  return defaultMatchRulesForm();
}

function collectLeaves(
  node: DocumentRuleCondition | DocumentRuleConditionGroup
): DocumentRuleCondition[] {
  if (node.type === "condition") return [node];
  return node.children.flatMap(collectLeaves);
}

function isAllConditionChildren(group: DocumentRuleConditionGroup): boolean {
  return group.children.every((c) => c.type === "condition");
}

function leafToRow(c: DocumentRuleCondition): MatchRuleRow {
  return {
    field: c.field,
    operator: c.operator,
    value: c.value,
  };
}

function simpleConditionChildren(
  group: DocumentRuleConditionGroup
): DocumentRuleCondition[] {
  return group.children.filter((c): c is DocumentRuleCondition => c.type === "condition");
}

export type ParseMatchRulesResult = {
  form: MatchRulesForm;
  parseable: boolean;
};

/**
 * Best-effort reverse of compileMatchRulesToClassifier.
 * Returns parseable=false when tree is too complex for simple editor.
 */
export function parseClassifierToMatchRules(
  root: DocumentRuleConditionGroup
): ParseMatchRulesResult {
  const empty = emptyMatchRulesForm();

  if (!root.children.length) {
    return { form: empty, parseable: true };
  }

  // Simple OR/AND of conditions only
  if (root.operator === "OR" && isAllConditionChildren(root)) {
    return {
      form: {
        ...empty,
        matchMode: "any",
        matchRules: simpleConditionChildren(root).map(leafToRow),
      },
      parseable: true,
    };
  }
  if (root.operator === "AND" && isAllConditionChildren(root)) {
    return {
      form: {
        ...empty,
        matchMode: "all",
        matchRules: simpleConditionChildren(root).map(leafToRow),
      },
      parseable: true,
    };
  }

  // AND(matchGroup, excludeGroup) pattern from compileMatchRulesToClassifier
  if (root.operator === "AND" && root.children.length === 2) {
    const [first, second] = root.children;
    if (first.type === "group" && second.type === "group") {
      if (
        first.operator === "OR" &&
        isAllConditionChildren(first) &&
        second.operator === "AND" &&
        isAllConditionChildren(second)
      ) {
        return {
          form: {
            matchMode: "any",
            matchRules: simpleConditionChildren(first).map(leafToRow),
            excludeMode: "any",
            excludeRules: simpleConditionChildren(second).map((c) =>
              leafToRow(invertCondition(c))
            ),
          },
          parseable: true,
        };
      }
      if (
        first.operator === "AND" &&
        isAllConditionChildren(first) &&
        second.operator === "AND" &&
        isAllConditionChildren(second)
      ) {
        return {
          form: {
            matchMode: "all",
            matchRules: simpleConditionChildren(first).map(leafToRow),
            excludeMode: "any",
            excludeRules: simpleConditionChildren(second).map((c) =>
              leafToRow(invertCondition(c))
            ),
          },
          parseable: true,
        };
      }
    }
    if (
      (first.type === "condition" ||
        (first.type === "group" &&
          (first.operator === "OR" || first.operator === "AND") &&
          isAllConditionChildren(first))) &&
      second.type === "group"
    ) {
      const matchRules =
        first.type === "condition"
          ? [leafToRow(first)]
          : simpleConditionChildren(first).map(leafToRow);
      const matchMode = first.type === "group" && first.operator === "AND" ? "all" : "any";
      if (second.operator === "AND" && isAllConditionChildren(second)) {
        return {
          form: {
            matchMode,
            matchRules,
            excludeMode: "any",
            excludeRules: simpleConditionChildren(second).map((c) =>
              leafToRow(invertCondition(c))
            ),
          },
          parseable: true,
        };
      }
    }
  }

  // Single match group with exclude absent — treat all leaves as match any
  const leaves = collectLeaves(root);
  if (leaves.length > 0 && leaves.length <= 12) {
    return {
      form: {
        ...empty,
        matchMode: "any",
        matchRules: leaves.map(leafToRow),
      },
      parseable: true,
    };
  }

  return { form: empty, parseable: false };
}

export function hasActionableMatchRules(form: MatchRulesForm): boolean {
  return form.matchRules.some((r) => r.field.trim()) || form.excludeRules.some((r) => r.field.trim());
}

function ruleRowIsCompilable(row: MatchRuleRow): boolean {
  const field = row.field.trim();
  if (!field) return false;
  if (isBooleanField(field)) return true;
  const value = row.value.trim();
  if (!value && row.operator !== "equals" && row.operator !== "not_equals") {
    return false;
  }
  return true;
}

/** At least one match/exclude row has enough data to compile and run. */
export function hasCompilableMatchRules(form: MatchRulesForm): boolean {
  return form.matchRules.some(ruleRowIsCompilable) || form.excludeRules.some(ruleRowIsCompilable);
}

export function isGenericDocumentTypeTitle(title: string): boolean {
  const t = title.trim().toLowerCase();
  return t === "custom type" || t === "new document type" || t === "new type" || t === "";
}

export function documentTypeReadiness(
  draft: {
    title: string;
    oneLine: string;
    code: string;
    posting: string;
    postTo?: DocumentTypePostTo;
    classifier: { root: DocumentRuleConditionGroup };
  },
  matchRulesForm?: MatchRulesForm,
  options?: { coaAccounts?: ChartOfAccountRow[] }
): { ready: boolean; items: { label: string; done: boolean }[] } {
  const { form } = matchRulesForm
    ? { form: matchRulesForm }
    : parseClassifierToMatchRules(draft.classifier.root);
  const hasRules = hasCompilableMatchRules(form);
  const hasPartialRules = hasActionableMatchRules(form);
  const hasSignals =
    parseSignalsFromClassifier(
      draft.classifier.root,
      allRecognitionSignalIds(getRecognitionSignalCatalog()).length > 0
        ? allRecognitionSignalIds(getRecognitionSignalCatalog())
        : allRecognitionSignalOptions().map((row) => row.id)
    ).length > 0;
  const hasDescription = draft.oneLine.trim().length >= 20;
  const hasName = !isGenericDocumentTypeTitle(draft.title);
  const hasCode = Boolean(draft.code.trim());
  const accounts = options?.coaAccounts ?? [];
  const hasPostTo = hasValidPostTo(
    { posting: draft.posting, postTo: draft.postTo ?? emptyDocumentTypePostTo() },
    accounts
  );

  const items = [
    { label: "Specific document name", done: hasName },
    {
      label: hasPartialRules
        ? "Complete match or exclude rules"
        : "Match / exclude rules, signals, or description (20+ chars)",
      done: hasRules || hasSignals || hasDescription,
    },
    { label: "Unique code", done: hasCode },
    { label: "Post to ledger (from chart of accounts)", done: hasPostTo },
  ];
  return { ready: items.every((i) => i.done), items };
}
