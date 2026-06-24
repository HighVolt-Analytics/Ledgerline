/**
 * Build document-type classifier trees from user-friendly recognition signals.
 * Mirrors backend document_type_rule_engine evaluation fields.
 */

import type {
  DocumentRuleCondition,
  DocumentRuleConditionGroup,
  DocumentTypeClassifier,
} from "@/lib/v5DocumentTypes";

export type RecognitionSignalId =
  | "heading_po"
  | "text_po"
  | "filename_po"
  | "heading_grn"
  | "text_grn"
  | "filename_grn"
  | "heading_contract"
  | "text_contract"
  | "filename_contract"
  | "text_terms"
  | "text_governing_law"
  | "text_signed_behalf"
  | "heading_invoice"
  | "text_invoice"
  | "filename_invoice"
  | "text_credit_note"
  | "filename_credit_note"
  | "text_debit_note"
  | "filename_debit_note"
  | "text_proforma"
  | "filename_proforma"
  | "text_recurring"
  | "filename_recurring"
  | "text_utility"
  | "filename_utility"
  | "text_freight"
  | "filename_freight"
  | "text_import"
  | "filename_import"
  | "text_intercompany"
  | "filename_intercompany"
  | "text_claim"
  | "filename_claim"
  | "text_statement"
  | "filename_statement"
  | "text_timesheet"
  | "filename_timesheet"
  | "text_remittance"
  | "filename_remittance"
  | "text_rcti"
  | "filename_rcti"
  | "text_consignment"
  | "filename_consignment"
  | "text_dunning"
  | "filename_dunning"
  | "text_bank_change"
  | "filename_bank_change"
  | "text_quote"
  | "filename_quote"
  | "text_tax_notice"
  | "filename_tax_notice"
  | "channel_whatsapp"
  | "has_po_reference"
  | "has_invoice_number"
  | "has_total_amount";

export type ClassifierLayout = "any_signal" | "all_signals" | "supporting_doc";

const cond = (
  field: string,
  operator: DocumentRuleCondition["operator"],
  value: string
): DocumentRuleCondition => ({
  type: "condition",
  field,
  operator,
  value,
});

const orGroup = (children: DocumentRuleCondition[]): DocumentRuleConditionGroup => ({
  type: "group",
  operator: "OR",
  children,
});

const andGroup = (
  children: Array<DocumentRuleCondition | DocumentRuleConditionGroup>
): DocumentRuleConditionGroup => ({
  type: "group",
  operator: "AND",
  children,
});

/** Map each checkbox id to one classifier leaf condition. */
export function signalToCondition(signalId: RecognitionSignalId): DocumentRuleCondition {
  switch (signalId) {
    case "heading_po":
      return cond("has_heading_po", "equals", "true");
    case "text_po":
      return cond("document_text", "regex", "(?i)purchase order");
    case "filename_po":
      return cond("attachment_name", "regex", "(?i)purchase[_-]?order|(^|[-_/])po([-_.]|$)");
    case "heading_grn":
      return cond("has_heading_grn", "equals", "true");
    case "text_grn":
      return cond(
        "document_text",
        "regex",
        "(?i)(goods\\s+receipt|delivery\\s+(note|docket)|\\bGRN\\b)"
      );
    case "filename_grn":
      return cond("attachment_name", "regex", "(?i)grn|goods[_-]?receipt|delivery[_-]?note");
    case "heading_contract":
      return cond("has_heading_contract", "equals", "true");
    case "text_contract":
      return cond(
        "document_text",
        "regex",
        "(?i)(\\bcontract\\b|docusign|master service agreement|terms and conditions)"
      );
    case "filename_contract":
      return cond(
        "attachment_name",
        "regex",
        "(?i)(contract|lease|sow|statement[_-]?of[_-]?work|rate[_-]?card)"
      );
    case "text_terms":
      return cond("document_text", "contains", "terms and conditions");
    case "text_governing_law":
      return cond("document_text", "contains", "governing law");
    case "text_signed_behalf":
      return cond("document_text", "contains", "signed for and on behalf");
    case "heading_invoice":
      return cond("has_heading_invoice", "equals", "true");
    case "text_invoice":
      return cond(
        "document_text",
        "regex",
        "(?i)\\b(tax\\s+invoice|commercial\\s+invoice)\\b"
      );
    case "filename_invoice":
      return cond(
        "attachment_name",
        "regex",
        "(?i)(?:^|[-_/])(?:inv|invoice|tax[_-]?inv)(?:[-_.]|$)"
      );
    case "text_credit_note":
      return cond("document_text", "regex", "(?i)(credit\\s+note|creditmemo|credit_memo)");
    case "filename_credit_note":
      return cond("attachment_name", "regex", "(?i)(credit[_-]?note|creditmemo|credit_memo)");
    case "text_debit_note":
      return cond("document_text", "regex", "(?i)(debit\\s+note|debitmemo|debit_memo)");
    case "filename_debit_note":
      return cond("attachment_name", "regex", "(?i)(debit[_-]?note|debitmemo|debit_memo)");
    case "text_proforma":
      return cond("document_text", "regex", "(?i)(pro[\\s_-]?forma|advance[\\s_-]?request)");
    case "filename_proforma":
      return cond("attachment_name", "regex", "(?i)(pro[\\s_-]?forma|advance[\\s_-]?request)");
    case "text_recurring":
      return cond(
        "document_text",
        "regex",
        "(?i)(\\brent\\b|\\blease\\b|subscription|retainer|recurring)"
      );
    case "filename_recurring":
      return cond(
        "attachment_name",
        "regex",
        "(?i)(rent|lease|subscription|retainer|recurring)"
      );
    case "text_utility":
      return cond(
        "document_text",
        "regex",
        "(?i)(utility|electricity|water\\s+bill|gas\\s+bill|telecom|telco)"
      );
    case "filename_utility":
      return cond("attachment_name", "regex", "(?i)(utility|electric|water|gas|telco|telecom)");
    case "text_freight":
      return cond(
        "document_text",
        "regex",
        "(?i)(\\bawb\\b|bill\\s+of\\s+lading|\\bfreight\\b|customs\\s+broker|demurrage)"
      );
    case "filename_freight":
      return cond(
        "attachment_name",
        "regex",
        "(?i)(awb|bill[_-]?of[_-]?lading|freight|customs[_-]?broker|demurrage)"
      );
    case "text_import":
      return cond(
        "document_text",
        "regex",
        "(?i)(customs\\s+entry|import\\s+declaration|bill\\s+of\\s+entry)"
      );
    case "filename_import":
      return cond(
        "attachment_name",
        "regex",
        "(?i)(customs[_-]?entry|import[_-]?declaration|bill[_-]?of[_-]?entry)"
      );
    case "text_intercompany":
      return cond(
        "document_text",
        "regex",
        "(?i)(intercompany|inter-company|\\bIC\\s+invoice\\b|transfer\\s+pricing)"
      );
    case "filename_intercompany":
      return cond("attachment_name", "regex", "(?i)(intercompany|inter[_-]?company|ic[_-]?invoice)");
    case "text_claim":
      return cond(
        "document_text",
        "regex",
        "(?i)(expense[_-]?claim|reimburse|team\\s+lunch|\\bmeal\\b)"
      );
    case "filename_claim":
      return cond(
        "attachment_name",
        "regex",
        "(?i)(expense[_-]?claim|claim[_-]?receipt|team[_-]?meal|reimburse)"
      );
    case "text_statement":
      return cond("document_text", "regex", "(?i)(vendor statement|account summary)");
    case "filename_statement":
      return cond(
        "attachment_name",
        "regex",
        "(?i)(statement|acct[_-]?summary|account[_-]?summary)"
      );
    case "text_timesheet":
      return cond("document_text", "regex", "(?i)(timesheet|time[_-]?sheet|service[_-]?entry)");
    case "filename_timesheet":
      return cond(
        "attachment_name",
        "regex",
        "(?i)(timesheet|time[_-]?sheet|service[_-]?entry|ses[_-])"
      );
    case "text_remittance":
      return cond("document_text", "regex", "(?i)(remittance|payment[_-]?advice)");
    case "filename_remittance":
      return cond("attachment_name", "regex", "(?i)(remittance|payment[_-]?advice)");
    case "text_rcti":
      return cond(
        "document_text",
        "regex",
        "(?i)(\\bRCTI\\b|recipient[- ]created|self[- ]bill)"
      );
    case "filename_rcti":
      return cond("attachment_name", "regex", "(?i)(rcti|self[_-]?bill|recipient[_-]?created)");
    case "text_consignment":
      return cond(
        "document_text",
        "regex",
        "(?i)(consignment|evaluated\\s+receipt|\\bERS\\b)"
      );
    case "filename_consignment":
      return cond("attachment_name", "regex", "(?i)(consignment|evaluated[_-]?receipt|ers[_-])");
    case "text_dunning":
      return cond("document_text", "regex", "(?i)(dunning|overdue|final[_-]?demand)");
    case "filename_dunning":
      return cond("attachment_name", "regex", "(?i)(dunning|overdue|final[_-]?demand)");
    case "text_bank_change":
      return cond("document_text", "regex", "(?i)(bank[_-]?detail|change[_-]?of[_-]?bank)");
    case "filename_bank_change":
      return cond("attachment_name", "regex", "(?i)(bank[_-]?detail|change[_-]?of[_-]?bank)");
    case "text_quote":
      return cond("document_text", "regex", "(?i)\\b(quote|quotation|estimate|proposal)\\b");
    case "filename_quote":
      return cond("attachment_name", "regex", "(?i)(quote|quotation|estimate|proposal)");
    case "text_tax_notice":
      return cond(
        "document_text",
        "regex",
        "(?i)\\b(ato|tax[_-]?office|tax[_-]?notice|compliance[_-]?notice)\\b"
      );
    case "filename_tax_notice":
      return cond(
        "attachment_name",
        "regex",
        "(?i)(ato|tax[_-]?office|tax[_-]?notice|compliance[_-]?notice)"
      );
    case "channel_whatsapp":
      return cond("capture_channel", "equals", "whatsapp");
    case "has_po_reference":
      return cond("has_po_reference", "equals", "true");
    case "has_invoice_number":
      return cond("has_invoice_no", "equals", "true");
    case "has_total_amount":
      return cond("has_total", "equals", "true");
    default:
      return cond("document_text", "contains", "");
  }
}

const SUPPORTING_GUARDS: DocumentRuleCondition[] = [
  cond("has_invoice_no", "equals", "false"),
  cond("is_commercial_invoice", "equals", "false"),
];

export function buildClassifierRoot(
  signalIds: RecognitionSignalId[],
  layout: ClassifierLayout
): DocumentRuleConditionGroup {
  const leaves = signalIds.map(signalToCondition);
  if (leaves.length === 0) {
    return { type: "group", operator: "AND", children: [] };
  }

  if (layout === "all_signals") {
    return andGroup(leaves);
  }

  if (layout === "supporting_doc") {
    return andGroup([orGroup(leaves), ...SUPPORTING_GUARDS]);
  }

  return orGroup(leaves);
}

export function buildClassifierFromSignals(
  signalIds: RecognitionSignalId[],
  layout: ClassifierLayout,
  options: { priority: number; confidence?: number; enabled?: boolean }
): DocumentTypeClassifier {
  return {
    enabled: options.enabled ?? true,
    priority: options.priority,
    confidence: options.confidence ?? 0.85,
    root: buildClassifierRoot(signalIds, layout),
  };
}

function conditionMatchesSignal(
  condition: DocumentRuleCondition,
  signalId: RecognitionSignalId
): boolean {
  const expected = signalToCondition(signalId);
  return (
    condition.field === expected.field &&
    condition.operator === expected.operator &&
    condition.value === expected.value
  );
}

function collectConditions(
  node: DocumentRuleCondition | DocumentRuleConditionGroup
): DocumentRuleCondition[] {
  if (node.type === "condition") return [node];
  return node.children.flatMap((child) => collectConditions(child));
}

/** Best-effort: recover simple-mode checkboxes from a stored classifier tree. */
export function parseSignalsFromClassifier(
  root: DocumentRuleConditionGroup,
  allowed: RecognitionSignalId[]
): RecognitionSignalId[] {
  const leaves = collectConditions(root);
  const found: RecognitionSignalId[] = [];
  for (const signalId of allowed) {
    if (leaves.some((leaf) => conditionMatchesSignal(leaf, signalId))) {
      found.push(signalId);
    }
  }
  return found;
}

export function isSupportingDocClassifier(root: DocumentRuleConditionGroup): boolean {
  const leaves = collectConditions(root);
  return (
    leaves.some((l) => l.field === "has_invoice_no" && l.value === "false") &&
    leaves.some((l) => l.field === "is_commercial_invoice" && l.value === "false")
  );
}

export function inferClassifierLayout(root: DocumentRuleConditionGroup): ClassifierLayout {
  if (root.operator === "AND" && isSupportingDocClassifier(root)) {
    return "supporting_doc";
  }
  if (root.operator === "AND" && root.children.every((c) => c.type === "condition")) {
    return "all_signals";
  }
  return "any_signal";
}
