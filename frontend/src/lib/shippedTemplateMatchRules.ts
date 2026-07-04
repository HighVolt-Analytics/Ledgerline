/**
 * Simple match / exclude rules for shipped document-type templates.
 * Replaces legacy signal trees and regex classifiers in the rule-book editor.
 */

import type { MatchRuleRow, MatchRulesForm } from "@/lib/documentMatchRules";
import type { DocumentTypeTemplate } from "@/lib/documentTypeTemplates";

const SUPPORTING_DOC_EXCLUDE_RULES: MatchRuleRow[] = [
  { field: "has_invoice_no", operator: "equals", value: "true" },
  { field: "has_heading_invoice", operator: "equals", value: "true" },
];

/** Map recognition signal ids → editable match-rule rows (contains / is checks). */
const SIGNAL_TO_MATCH_RULE: Record<string, MatchRuleRow> = {
  heading_po: { field: "has_heading_po", operator: "equals", value: "true" },
  text_po: { field: "document_text", operator: "contains", value: "purchase order" },
  filename_po: { field: "attachment_name", operator: "contains", value: "po" },
  heading_so: { field: "has_heading_so", operator: "equals", value: "true" },
  text_so: { field: "document_text", operator: "contains", value: "sales order" },
  filename_so: { field: "attachment_name", operator: "contains", value: "so" },
  heading_grn: { field: "has_heading_grn", operator: "equals", value: "true" },
  text_grn: { field: "document_text", operator: "contains", value: "goods received" },
  filename_grn: { field: "attachment_name", operator: "contains", value: "grn" },
  heading_contract: { field: "has_heading_contract", operator: "equals", value: "true" },
  text_contract: { field: "document_text", operator: "contains", value: "agreement" },
  filename_contract: { field: "attachment_name", operator: "contains", value: "contract" },
  text_terms: { field: "document_text", operator: "contains", value: "terms and conditions" },
  text_governing_law: { field: "document_text", operator: "contains", value: "governing law" },
  text_signed_behalf: {
    field: "document_text",
    operator: "contains",
    value: "signed for and on behalf",
  },
  heading_invoice: { field: "has_heading_invoice", operator: "equals", value: "true" },
  text_invoice: { field: "document_text", operator: "contains", value: "tax invoice" },
  filename_invoice: { field: "attachment_name", operator: "contains", value: "invoice" },
  text_credit_note: { field: "document_heading", operator: "contains", value: "credit note" },
  filename_credit_note: { field: "attachment_name", operator: "contains", value: "credit" },
  text_debit_note: { field: "document_heading", operator: "contains", value: "debit note" },
  filename_debit_note: { field: "attachment_name", operator: "contains", value: "debit" },
  text_proforma: { field: "document_text", operator: "contains", value: "proforma" },
  filename_proforma: { field: "attachment_name", operator: "contains", value: "proforma" },
  text_claim: { field: "document_text", operator: "contains", value: "expense claim" },
  filename_claim: { field: "attachment_name", operator: "contains", value: "claim" },
  text_quote: { field: "document_text", operator: "contains", value: "quotation" },
  filename_quote: { field: "attachment_name", operator: "contains", value: "quote" },
  text_tax_notice: { field: "document_text", operator: "contains", value: "tax notice" },
  filename_tax_notice: { field: "attachment_name", operator: "contains", value: "ato" },
  text_bank_change: { field: "document_text", operator: "contains", value: "bank detail" },
  filename_bank_change: { field: "attachment_name", operator: "contains", value: "bank" },
  text_freight: { field: "document_text", operator: "contains", value: "freight" },
  filename_freight: { field: "attachment_name", operator: "contains", value: "freight" },
  text_import: { field: "document_text", operator: "contains", value: "customs" },
  filename_import: { field: "attachment_name", operator: "contains", value: "customs" },
  text_intercompany: { field: "document_text", operator: "contains", value: "intercompany" },
  filename_intercompany: { field: "attachment_name", operator: "contains", value: "intercompany" },
  text_recurring: { field: "document_text", operator: "contains", value: "subscription" },
  filename_recurring: { field: "attachment_name", operator: "contains", value: "subscription" },
  text_utility: { field: "document_text", operator: "contains", value: "utility" },
  filename_utility: { field: "attachment_name", operator: "contains", value: "utility" },
  text_statement: { field: "document_text", operator: "contains", value: "statement" },
  filename_statement: { field: "attachment_name", operator: "contains", value: "statement" },
  text_timesheet: { field: "document_text", operator: "contains", value: "timesheet" },
  filename_timesheet: { field: "attachment_name", operator: "contains", value: "timesheet" },
  text_remittance: { field: "document_text", operator: "contains", value: "remittance" },
  filename_remittance: { field: "attachment_name", operator: "contains", value: "remittance" },
  text_rcti: { field: "document_text", operator: "contains", value: "rcti" },
  filename_rcti: { field: "attachment_name", operator: "contains", value: "rcti" },
  text_consignment: { field: "document_text", operator: "contains", value: "consignment" },
  filename_consignment: { field: "attachment_name", operator: "contains", value: "consignment" },
  text_dunning: { field: "document_text", operator: "contains", value: "payment reminder" },
  filename_dunning: { field: "attachment_name", operator: "contains", value: "dunning" },
  channel_whatsapp: { field: "capture_channel", operator: "equals", value: "whatsapp" },
  has_po_reference: { field: "has_po_reference", operator: "equals", value: "true" },
  has_invoice_number: { field: "has_invoice_no", operator: "equals", value: "true" },
  has_total_amount: { field: "has_total", operator: "equals", value: "true" },
};

const EXTRA_EXCLUDE_BY_SHIPPED_CODE: Record<string, MatchRuleRow[]> = {
  "DT-24": [{ field: "has_invoice_no", operator: "equals", value: "true" }],
};

function uniqueRules(rows: MatchRuleRow[]): MatchRuleRow[] {
  const seen = new Set<string>();
  const out: MatchRuleRow[] = [];
  for (const row of rows) {
    const key = `${row.field}|${row.operator}|${row.value}`;
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(row);
  }
  return out;
}

/** Build the simple-mode match / exclude form for a shipped template. */
export function matchRulesFormForTemplate(template: DocumentTypeTemplate): MatchRulesForm {
  const matchRules = uniqueRules(
    template.defaultSignalIds
      .map((id) => SIGNAL_TO_MATCH_RULE[id])
      .filter((row): row is MatchRuleRow => Boolean(row))
  );

  let excludeRules: MatchRuleRow[] = [];
  if (template.classifierLayout === "supporting_doc") {
    excludeRules = [...SUPPORTING_DOC_EXCLUDE_RULES];
  }
  const code = template.shippedCode.trim().toUpperCase();
  if (code && EXTRA_EXCLUDE_BY_SHIPPED_CODE[code]) {
    excludeRules = uniqueRules([...excludeRules, ...EXTRA_EXCLUDE_BY_SHIPPED_CODE[code]]);
  }

  const matchMode = template.classifierLayout === "all_signals" ? "all" : "any";

  return {
    matchMode,
    matchRules,
    excludeMode: "any",
    excludeRules,
  };
}
