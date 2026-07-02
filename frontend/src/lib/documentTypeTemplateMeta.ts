/**
 * Simple-mode recognition signals per shipped DT code (Excel / v5 matrix).
 */

import type { PurchaseBundleRole, SalesBundleRole } from "@/lib/documentBundleConfig";

export type ClassifierLayout = "any_signal" | "all_signals" | "supporting_doc";
export type RecognitionSignalId = string;

export type RouteConfidencePreset = "flexible" | "standard" | "strict";

export type RecognitionSignalOption = {
  id: RecognitionSignalId;
  label: string;
  hint: string;
};

export type TemplateSignalMeta = {
  classifierLayout: ClassifierLayout;
  signalIds: RecognitionSignalId[];
  defaultSignalIds: RecognitionSignalId[];
  purchaseBundleRole?: PurchaseBundleRole;
  salesBundleRole?: SalesBundleRole;
  routeConfidence?: RouteConfidencePreset;
  extractionFields?: string[];
};

type TemplateSignalMetaRaw = TemplateSignalMeta;

export const TEMPLATE_SIGNAL_META: Record<string, TemplateSignalMetaRaw> = {
  "DT-01": {
    classifierLayout: "all_signals",
    signalIds: ["heading_invoice", "has_po_reference", "has_invoice_number", "has_total_amount"],
    defaultSignalIds: ["has_po_reference", "has_invoice_number", "has_total_amount"],
    extractionFields: ["vendor", "invoice_no", "po_reference", "total", "gst", "line_items"],
  },
  "DT-02": {
    classifierLayout: "supporting_doc",
    purchaseBundleRole: "po",
    signalIds: ["heading_po", "text_po", "filename_po"],
    defaultSignalIds: ["heading_po", "text_po", "filename_po"],
    extractionFields: [
      "vendor",
      "permit_no",
      "consignment_ref",
      "document_heading",
      "attachment_name",
      "document_text",
    ],
  },
  "DT-03": {
    classifierLayout: "supporting_doc",
    purchaseBundleRole: "grn",
    signalIds: ["heading_grn", "text_grn", "filename_grn"],
    defaultSignalIds: ["heading_grn", "text_grn", "filename_grn"],
    extractionFields: ["vendor", "po_reference", "attachment_name"],
  },
  "DT-04": {
    classifierLayout: "any_signal",
    signalIds: ["text_credit_note", "filename_credit_note"],
    defaultSignalIds: ["text_credit_note", "filename_credit_note"],
    extractionFields: ["vendor", "invoice_no", "total"],
  },
  "DT-05": {
    classifierLayout: "any_signal",
    signalIds: ["text_debit_note", "filename_debit_note"],
    defaultSignalIds: ["text_debit_note", "filename_debit_note"],
    extractionFields: ["vendor", "invoice_no", "total"],
  },
  "DT-06": {
    classifierLayout: "any_signal",
    signalIds: ["text_proforma", "filename_proforma"],
    defaultSignalIds: ["text_proforma", "filename_proforma"],
    extractionFields: ["vendor", "invoice_no", "total", "po_reference"],
  },
  "DT-07": {
    classifierLayout: "all_signals",
    signalIds: ["heading_invoice", "text_recurring", "filename_recurring", "has_total_amount"],
    defaultSignalIds: ["heading_invoice", "text_recurring", "has_total_amount"],
    extractionFields: ["vendor", "invoice_no", "total", "document_text"],
  },
  "DT-08": {
    classifierLayout: "all_signals",
    signalIds: ["heading_invoice", "text_utility", "filename_utility", "has_total_amount"],
    defaultSignalIds: ["text_utility", "has_total_amount"],
    extractionFields: ["vendor", "invoice_no", "total", "account_code"],
  },
  "DT-09": {
    classifierLayout: "any_signal",
    signalIds: ["text_freight", "filename_freight"],
    defaultSignalIds: ["text_freight", "filename_freight"],
    extractionFields: ["vendor", "invoice_no", "total", "line_items"],
  },
  "DT-10": {
    classifierLayout: "any_signal",
    signalIds: ["text_import", "filename_import", "heading_invoice"],
    defaultSignalIds: ["text_import", "filename_import"],
    extractionFields: ["vendor", "invoice_no", "total", "line_items", "document_text"],
  },
  "DT-11": {
    classifierLayout: "any_signal",
    signalIds: ["text_intercompany", "filename_intercompany"],
    defaultSignalIds: ["text_intercompany", "filename_intercompany"],
    extractionFields: ["vendor", "invoice_no", "total"],
  },
  "DT-12": {
    classifierLayout: "any_signal",
    signalIds: ["text_claim", "filename_claim", "channel_whatsapp"],
    defaultSignalIds: ["text_claim", "filename_claim"],
    extractionFields: ["vendor", "total", "invoice_date", "line_items"],
  },
  "DT-13": {
    classifierLayout: "any_signal",
    signalIds: ["text_statement", "filename_statement"],
    defaultSignalIds: ["text_statement", "filename_statement"],
    extractionFields: ["vendor", "document_text", "attachment_name"],
  },
  "DT-16": {
    classifierLayout: "any_signal",
    routeConfidence: "flexible",
    signalIds: [
      "heading_contract",
      "text_contract",
      "filename_contract",
      "text_terms",
      "text_governing_law",
      "text_signed_behalf",
    ],
    defaultSignalIds: ["heading_contract", "text_contract", "filename_contract", "text_terms"],
    extractionFields: ["vendor", "document_text", "attachment_name"],
  },
  "DT-17": {
    classifierLayout: "any_signal",
    signalIds: ["text_timesheet", "filename_timesheet"],
    defaultSignalIds: ["text_timesheet", "filename_timesheet"],
    extractionFields: ["vendor", "document_text", "attachment_name"],
  },
  "DT-18": {
    classifierLayout: "any_signal",
    signalIds: ["text_remittance", "filename_remittance"],
    defaultSignalIds: ["text_remittance", "filename_remittance"],
    extractionFields: ["vendor", "document_text", "total"],
  },
  "DT-19": {
    classifierLayout: "any_signal",
    signalIds: ["text_rcti", "filename_rcti"],
    defaultSignalIds: ["text_rcti", "filename_rcti"],
    extractionFields: ["vendor", "invoice_no", "total", "document_text"],
  },
  "DT-20": {
    classifierLayout: "any_signal",
    signalIds: ["text_consignment", "filename_consignment"],
    defaultSignalIds: ["text_consignment", "filename_consignment"],
    extractionFields: ["vendor", "invoice_no", "total", "po_reference"],
  },
  "DT-21": {
    classifierLayout: "all_signals",
    routeConfidence: "strict",
    signalIds: ["heading_invoice", "has_invoice_number", "has_total_amount"],
    defaultSignalIds: ["heading_invoice", "has_invoice_number", "has_total_amount"],
    extractionFields: ["vendor", "invoice_no", "total", "bank_details", "abn"],
  },
  "DT-22": {
    classifierLayout: "any_signal",
    routeConfidence: "strict",
    signalIds: ["text_dunning", "filename_dunning"],
    defaultSignalIds: ["text_dunning", "filename_dunning"],
    extractionFields: ["vendor", "document_text", "attachment_name"],
  },
  "DT-23": {
    classifierLayout: "any_signal",
    signalIds: ["text_bank_change", "filename_bank_change"],
    defaultSignalIds: ["text_bank_change", "filename_bank_change"],
    extractionFields: ["vendor", "bank_details", "document_text"],
  },
  "DT-24": {
    classifierLayout: "any_signal",
    routeConfidence: "strict",
    signalIds: ["text_quote", "filename_quote"],
    defaultSignalIds: ["text_quote", "filename_quote"],
    extractionFields: ["vendor", "document_text", "attachment_name"],
  },
  "DT-25": {
    classifierLayout: "any_signal",
    routeConfidence: "strict",
    signalIds: ["text_tax_notice", "filename_tax_notice"],
    defaultSignalIds: ["text_tax_notice", "filename_tax_notice"],
    extractionFields: ["vendor", "document_text", "attachment_name"],
  },
  "DT-26": {
    classifierLayout: "all_signals",
    routeConfidence: "standard",
    signalIds: ["heading_invoice", "has_invoice_number", "has_total_amount"],
    defaultSignalIds: ["heading_invoice", "has_invoice_number", "has_total_amount"],
    extractionFields: ["vendor", "invoice_no", "total", "due_date", "line_items"],
  },
  "DT-27": {
    classifierLayout: "supporting_doc",
    routeConfidence: "standard",
    salesBundleRole: "so",
    signalIds: ["heading_so", "text_so", "filename_so"],
    defaultSignalIds: ["heading_so", "text_so", "filename_so"],
    extractionFields: ["vendor", "so_reference", "attachment_name", "document_text"],
  },
  "DT-28": {
    classifierLayout: "supporting_doc",
    routeConfidence: "standard",
    salesBundleRole: "dn",
    signalIds: ["heading_grn", "text_grn", "filename_grn", "text_so", "filename_so"],
    defaultSignalIds: ["filename_grn", "text_so", "filename_so"],
    extractionFields: ["vendor", "so_reference", "attachment_name"],
  },
};

function hydrateSignalOptions(ids: RecognitionSignalId[]): RecognitionSignalOption[] {
  return ids.map((id) => ({
    id,
    label: id.replace(/_/g, " "),
    hint: "",
  }));
}

export type TemplateSignalMetaHydrated = TemplateSignalMeta & {
  signals: RecognitionSignalOption[];
};

export function templateSignalMetaForCode(code: string): TemplateSignalMetaHydrated | null {
  const raw = TEMPLATE_SIGNAL_META[code.trim().toUpperCase()];
  if (!raw) return null;
  return {
    ...raw,
    signals: hydrateSignalOptions(raw.signalIds),
  };
}

/** Union of every shipped-template recognition signal (for custom types). */
export function allRecognitionSignalOptions(): RecognitionSignalOption[] {
  const byId = new Map<string, RecognitionSignalOption>();
  for (const meta of Object.values(TEMPLATE_SIGNAL_META)) {
    for (const signal of hydrateSignalOptions(meta.signalIds)) {
      if (!byId.has(signal.id)) {
        byId.set(signal.id, signal);
      }
    }
  }
  return [...byId.values()];
}
