import type { MatchRuleRow } from "@/lib/documentMatchRules";

export type RuleBuilderAction = {
  id: string;
  label: string;
  hint: string;
  target: "match" | "exclude";
  rule: MatchRuleRow;
};

/** Primary actions — add editable rows; user supplies the phrase or value. */
export const RULE_BUILDER_ACTIONS: RuleBuilderAction[] = [
  {
    id: "match-heading",
    label: "Heading contains…",
    hint: "Match when the document title / heading includes your phrase",
    target: "match",
    rule: { field: "document_heading", operator: "contains", value: "" },
  },
  {
    id: "match-body",
    label: "Body text contains…",
    hint: "Search OCR body text for words your documents use",
    target: "match",
    rule: { field: "document_text", operator: "contains", value: "" },
  },
  {
    id: "match-filename",
    label: "Filename contains…",
    hint: "Match attachment names such as INV- or GRN-",
    target: "match",
    rule: { field: "attachment_name", operator: "contains", value: "" },
  },
  {
    id: "match-vendor",
    label: "Vendor name contains…",
    hint: "When OCR extracted a vendor line",
    target: "match",
    rule: { field: "vendor", operator: "contains", value: "" },
  },
  {
    id: "match-subject",
    label: "Email subject contains…",
    hint: "For email-captured documents",
    target: "match",
    rule: { field: "email_subject", operator: "contains", value: "" },
  },
  {
    id: "exclude-heading",
    label: "Exclude heading contains…",
    hint: "Reject when heading includes this phrase",
    target: "exclude",
    rule: { field: "document_heading", operator: "contains", value: "" },
  },
  {
    id: "exclude-body",
    label: "Exclude body contains…",
    hint: "Reject when OCR body includes this phrase",
    target: "exclude",
    rule: { field: "document_text", operator: "contains", value: "" },
  },
];

export type HeuristicFieldCheck = {
  id: string;
  label: string;
  hint: string;
  rule: MatchRuleRow;
};

/**
 * Optional OCR heuristics — layout-dependent; not suitable for every document.
 * Shown collapsed so users opt in explicitly.
 */
export const HEURISTIC_FIELD_CHECKS: HeuristicFieldCheck[] = [
  {
    id: "heuristic-invoice-heading",
    label: "Invoice-like heading (heuristic)",
    hint: "Best-effort flag from OCR headings — may miss non-standard layouts",
    rule: { field: "has_heading_invoice", operator: "equals", value: "true" },
  },
  {
    id: "heuristic-credit-heading",
    label: "Credit note heading (heuristic)",
    hint: "Heading pattern only; verify on your samples",
    rule: { field: "has_heading_credit_note", operator: "equals", value: "true" },
  },
  {
    id: "heuristic-grn-heading",
    label: "GRN / delivery heading (heuristic)",
    hint: "Heading pattern only; handwritten GRNs may not match",
    rule: { field: "has_heading_grn", operator: "equals", value: "true" },
  },
  {
    id: "heuristic-po-heading",
    label: "PO heading (heuristic)",
    hint: "Heading pattern only",
    rule: { field: "has_heading_po", operator: "equals", value: "true" },
  },
  {
    id: "heuristic-quote-heading",
    label: "Quote heading (heuristic)",
    hint: "Heading pattern only",
    rule: { field: "has_heading_quote", operator: "equals", value: "true" },
  },
  {
    id: "heuristic-has-invoice-no",
    label: "Has invoice number field (heuristic)",
    hint: "True when OCR found an invoice number — not all layouts expose this",
    rule: { field: "has_invoice_no", operator: "equals", value: "true" },
  },
  {
    id: "heuristic-has-total",
    label: "Has total amount field (heuristic)",
    hint: "True when OCR found a total — letters may not have totals",
    rule: { field: "has_total", operator: "equals", value: "true" },
  },
  {
    id: "heuristic-has-po",
    label: "Has PO reference (heuristic)",
    hint: "True when a PO reference was extracted",
    rule: { field: "has_po_reference", operator: "equals", value: "true" },
  },
];

export type ContextualPhraseHint = {
  id: string;
  label: string;
  matchRules: MatchRuleRow[];
  excludeRules?: MatchRuleRow[];
};

type HintContext = {
  title?: string;
  llmPrompt?: string;
};

function haystack(ctx: HintContext): string {
  return `${ctx.title ?? ""} ${ctx.llmPrompt ?? ""}`.trim().toLowerCase();
}

/** Optional phrase bundles inferred from the type name — user edits values after adding. */
export function contextualPhraseHints(ctx: HintContext): ContextualPhraseHint[] {
  const text = haystack(ctx);
  const hints: ContextualPhraseHint[] = [];

  const push = (hint: ContextualPhraseHint) => {
    if (hints.some((row) => row.id === hint.id)) return;
    hints.push(hint);
  };

  if (/invoice|tax inv|ap\b|payable|bill/.test(text)) {
    push({
      id: "ctx-invoice-phrases",
      label: "Invoice phrases",
      matchRules: [
        { field: "document_heading", operator: "contains", value: "tax invoice" },
        { field: "document_text", operator: "contains", value: "invoice no" },
      ],
      excludeRules: [
        { field: "document_heading", operator: "contains", value: "quote" },
        { field: "document_heading", operator: "contains", value: "proforma" },
      ],
    });
  }

  if (/grn|goods received|delivery|docket|receipt note/.test(text)) {
    push({
      id: "ctx-grn-phrases",
      label: "GRN / delivery phrases",
      matchRules: [
        { field: "document_heading", operator: "contains", value: "goods received" },
        { field: "document_text", operator: "contains", value: "delivery docket" },
      ],
      excludeRules: [
        { field: "document_heading", operator: "contains", value: "tax invoice" },
      ],
    });
  }

  if (/credit|adjustment/.test(text)) {
    push({
      id: "ctx-credit-phrases",
      label: "Credit note phrases",
      matchRules: [
        { field: "document_heading", operator: "contains", value: "credit note" },
        { field: "document_text", operator: "contains", value: "credit" },
      ],
    });
  }

  if (/purchase order|\bpo\b|order confirmation/.test(text)) {
    push({
      id: "ctx-po-phrases",
      label: "PO phrases",
      matchRules: [
        { field: "document_heading", operator: "contains", value: "purchase order" },
        { field: "document_text", operator: "contains", value: "po number" },
      ],
    });
  }

  if (/quote|quotation|estimate/.test(text)) {
    push({
      id: "ctx-quote-phrases",
      label: "Quote phrases",
      matchRules: [
        { field: "document_heading", operator: "contains", value: "quotation" },
        { field: "document_text", operator: "contains", value: "quote" },
      ],
      excludeRules: [
        { field: "document_heading", operator: "contains", value: "tax invoice" },
      ],
    });
  }

  if (/bank|statement|remittance|payment advice/.test(text)) {
    push({
      id: "ctx-bank-phrases",
      label: "Bank / payment phrases",
      matchRules: [
        { field: "document_text", operator: "contains", value: "bank statement" },
        { field: "document_text", operator: "contains", value: "remittance" },
      ],
    });
  }

  if (/contract|agreement|sow|rate card/.test(text)) {
    push({
      id: "ctx-contract-phrases",
      label: "Contract phrases",
      matchRules: [
        { field: "document_heading", operator: "contains", value: "agreement" },
        { field: "document_text", operator: "contains", value: "contract" },
      ],
    });
  }

  return hints;
}

/** @deprecated Use RULE_BUILDER_ACTIONS — kept for tests importing old symbols. */
export const MATCH_RULE_PRESET_CATEGORIES = ["Build rules", "Heuristic OCR flags"] as const;

/** @deprecated */
export const MATCH_RULE_PRESETS = HEURISTIC_FIELD_CHECKS.map((row) => ({
  id: row.id,
  label: row.label,
  kind: "match" as const,
  category: "Heuristic OCR flags",
  rule: row.rule,
}));
