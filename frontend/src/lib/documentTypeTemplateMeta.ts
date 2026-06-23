/**
 * Simple-mode recognition signals per shipped DT code (Excel / v5 matrix).
 */

import type { ClassifierLayout, RecognitionSignalId } from "@/lib/documentClassifierBuilder";
import type { PurchaseBundleRole } from "@/lib/documentBundleConfig";

export type RouteConfidencePreset = "flexible" | "standard" | "strict";

export type RecognitionSignalOption = {
  id: RecognitionSignalId;
  label: string;
  hint: string;
};

export type TemplateSignalMeta = {
  classifierLayout: ClassifierLayout;
  signals: RecognitionSignalOption[];
  defaultSignalIds: RecognitionSignalId[];
  purchaseBundleRole?: PurchaseBundleRole;
  routeConfidence?: RouteConfidencePreset;
  extractionFields?: string[];
};

const SIGNAL = (
  id: RecognitionSignalId,
  label: string,
  hint: string
): RecognitionSignalOption => ({ id, label, hint });

export const TEMPLATE_SIGNAL_META: Record<string, TemplateSignalMeta> = {
  "DT-01": {
    classifierLayout: "all_signals",
    signals: [
      SIGNAL("heading_invoice", "Page title is invoice / tax invoice", "OCR heading scan"),
      SIGNAL("has_po_reference", "PO number found on document", "Parsed PO reference"),
      SIGNAL("has_invoice_number", "Invoice number present", "Invoice no field or heading"),
      SIGNAL("has_total_amount", "Total amount present", "Parsed total"),
    ],
    defaultSignalIds: ["has_po_reference", "has_invoice_number", "has_total_amount"],
    extractionFields: ["vendor", "invoice_no", "po_reference", "total", "gst", "line_items"],
  },
  "DT-02": {
    classifierLayout: "supporting_doc",
    purchaseBundleRole: "po",
    signals: [
      SIGNAL("heading_po", "Page title is purchase order", "OCR heading scan"),
      SIGNAL("text_po", "Body contains “purchase order”", "Full document text"),
      SIGNAL("filename_po", "Filename contains PO / purchase order", "Attachment name"),
    ],
    defaultSignalIds: ["heading_po", "text_po", "filename_po"],
    extractionFields: ["vendor", "po_reference", "attachment_name"],
  },
  "DT-03": {
    classifierLayout: "supporting_doc",
    purchaseBundleRole: "grn",
    signals: [
      SIGNAL("heading_grn", "Page title is GRN / delivery note", "OCR heading scan"),
      SIGNAL("text_grn", "Body mentions goods receipt or GRN", "Full document text"),
      SIGNAL("filename_grn", "Filename contains GRN / delivery note", "Attachment name"),
    ],
    defaultSignalIds: ["heading_grn", "text_grn", "filename_grn"],
    extractionFields: ["vendor", "po_reference", "attachment_name"],
  },
  "DT-04": {
    classifierLayout: "any_signal",
    signals: [
      SIGNAL("text_credit_note", "Body mentions credit note", "Full document text"),
      SIGNAL("filename_credit_note", "Filename contains credit note", "Attachment name"),
    ],
    defaultSignalIds: ["text_credit_note", "filename_credit_note"],
    extractionFields: ["vendor", "invoice_no", "total"],
  },
  "DT-05": {
    classifierLayout: "any_signal",
    signals: [
      SIGNAL("text_debit_note", "Body mentions debit note", "Full document text"),
      SIGNAL("filename_debit_note", "Filename contains debit note", "Attachment name"),
    ],
    defaultSignalIds: ["text_debit_note", "filename_debit_note"],
    extractionFields: ["vendor", "invoice_no", "total"],
  },
  "DT-06": {
    classifierLayout: "any_signal",
    signals: [
      SIGNAL("text_proforma", "Body mentions proforma or advance request", "Full document text"),
      SIGNAL("filename_proforma", "Filename contains proforma / advance", "Attachment name"),
    ],
    defaultSignalIds: ["text_proforma", "filename_proforma"],
    extractionFields: ["vendor", "invoice_no", "total", "po_reference"],
  },
  "DT-07": {
    classifierLayout: "all_signals",
    signals: [
      SIGNAL("heading_invoice", "Page title is invoice / tax invoice", "OCR heading scan"),
      SIGNAL("text_recurring", "Body mentions rent, lease, subscription, or retainer", "Full document text"),
      SIGNAL("filename_recurring", "Filename contains rent / lease / subscription", "Attachment name"),
      SIGNAL("has_total_amount", "Total amount present", "Parsed total"),
    ],
    defaultSignalIds: ["heading_invoice", "text_recurring", "has_total_amount"],
    extractionFields: ["vendor", "invoice_no", "total", "document_text"],
  },
  "DT-08": {
    classifierLayout: "all_signals",
    signals: [
      SIGNAL("heading_invoice", "Page title is invoice / tax invoice", "OCR heading scan"),
      SIGNAL("text_utility", "Body mentions utility, electricity, water, gas, or telecom", "Full document text"),
      SIGNAL("filename_utility", "Filename contains utility / power / gas", "Attachment name"),
      SIGNAL("has_total_amount", "Total amount present", "Parsed total"),
    ],
    defaultSignalIds: ["text_utility", "has_total_amount"],
    extractionFields: ["vendor", "invoice_no", "total", "account_code"],
  },
  "DT-09": {
    classifierLayout: "any_signal",
    signals: [
      SIGNAL("text_freight", "Body mentions AWB, freight, customs broker, or demurrage", "Full document text"),
      SIGNAL("filename_freight", "Filename contains freight / AWB / broker", "Attachment name"),
      SIGNAL("has_invoice_number", "Invoice number present", "Parsed invoice no"),
    ],
    defaultSignalIds: ["text_freight", "filename_freight"],
    extractionFields: ["vendor", "invoice_no", "total", "line_items"],
  },
  "DT-10": {
    classifierLayout: "any_signal",
    signals: [
      SIGNAL("text_import", "Body mentions customs entry or import declaration", "Full document text"),
      SIGNAL("filename_import", "Filename contains customs / import entry", "Attachment name"),
      SIGNAL("heading_invoice", "Commercial invoice heading present", "OCR heading scan"),
    ],
    defaultSignalIds: ["text_import", "filename_import"],
    extractionFields: ["vendor", "invoice_no", "total", "line_items", "document_text"],
  },
  "DT-11": {
    classifierLayout: "any_signal",
    signals: [
      SIGNAL("text_intercompany", "Body mentions intercompany or transfer pricing", "Full document text"),
      SIGNAL("filename_intercompany", "Filename contains intercompany / IC invoice", "Attachment name"),
      SIGNAL("has_invoice_number", "Invoice number present", "Parsed invoice no"),
    ],
    defaultSignalIds: ["text_intercompany", "filename_intercompany"],
    extractionFields: ["vendor", "invoice_no", "total"],
  },
  "DT-12": {
    classifierLayout: "any_signal",
    signals: [
      SIGNAL("text_claim", "Body mentions meal, reimburse, or expense claim", "Line / body text"),
      SIGNAL("filename_claim", "Filename contains claim / meal / reimburse", "Attachment name"),
      SIGNAL("channel_whatsapp", "Submitted via WhatsApp", "Capture channel only"),
    ],
    defaultSignalIds: ["text_claim", "filename_claim"],
    extractionFields: ["vendor", "total", "invoice_date", "line_items"],
  },
  "DT-13": {
    classifierLayout: "any_signal",
    signals: [
      SIGNAL("text_statement", "Body mentions vendor statement or account summary", "Full document text"),
      SIGNAL("filename_statement", "Filename contains statement / account summary", "Attachment name"),
    ],
    defaultSignalIds: ["text_statement", "filename_statement"],
    extractionFields: ["vendor", "document_text", "attachment_name"],
  },
  "DT-16": {
    classifierLayout: "any_signal",
    routeConfidence: "flexible",
    signals: [
      SIGNAL("heading_contract", "Page title is contract / agreement", "OCR heading scan"),
      SIGNAL("text_contract", "Body mentions contract, DocuSign, or MSA", "Full document text"),
      SIGNAL("filename_contract", "Filename contains contract / SOW / lease", "Attachment name"),
      SIGNAL("text_terms", "Body contains “terms and conditions”", "Full document text"),
      SIGNAL("text_governing_law", "Body contains “governing law”", "Full document text"),
      SIGNAL("text_signed_behalf", "Body contains signature block language", "Full document text"),
    ],
    defaultSignalIds: ["heading_contract", "text_contract", "filename_contract", "text_terms"],
    extractionFields: ["vendor", "document_text", "attachment_name"],
  },
  "DT-17": {
    classifierLayout: "any_signal",
    signals: [
      SIGNAL("text_timesheet", "Body mentions timesheet or service entry", "Full document text"),
      SIGNAL("filename_timesheet", "Filename contains timesheet / SES", "Attachment name"),
    ],
    defaultSignalIds: ["text_timesheet", "filename_timesheet"],
    extractionFields: ["vendor", "document_text", "attachment_name"],
  },
  "DT-18": {
    classifierLayout: "any_signal",
    signals: [
      SIGNAL("text_remittance", "Body mentions remittance or payment advice", "Full document text"),
      SIGNAL("filename_remittance", "Filename contains remittance / payment advice", "Attachment name"),
    ],
    defaultSignalIds: ["text_remittance", "filename_remittance"],
    extractionFields: ["vendor", "document_text", "total"],
  },
  "DT-19": {
    classifierLayout: "any_signal",
    signals: [
      SIGNAL("text_rcti", "Body mentions RCTI or self-billing", "Full document text"),
      SIGNAL("filename_rcti", "Filename contains RCTI / self-bill", "Attachment name"),
      SIGNAL("has_invoice_number", "Invoice number present", "Parsed invoice no"),
    ],
    defaultSignalIds: ["text_rcti", "filename_rcti"],
    extractionFields: ["vendor", "invoice_no", "total", "document_text"],
  },
  "DT-20": {
    classifierLayout: "any_signal",
    signals: [
      SIGNAL("text_consignment", "Body mentions consignment or ERS settlement", "Full document text"),
      SIGNAL("filename_consignment", "Filename contains consignment / ERS", "Attachment name"),
    ],
    defaultSignalIds: ["text_consignment", "filename_consignment"],
    extractionFields: ["vendor", "invoice_no", "total", "po_reference"],
  },
  "DT-21": {
    classifierLayout: "all_signals",
    routeConfidence: "strict",
    signals: [
      SIGNAL("heading_invoice", "Page title is invoice / tax invoice", "OCR heading scan"),
      SIGNAL("has_invoice_number", "Invoice number present", "Parsed invoice no"),
      SIGNAL("has_total_amount", "Total amount present", "Parsed total"),
    ],
    defaultSignalIds: ["heading_invoice", "has_invoice_number", "has_total_amount"],
    extractionFields: ["vendor", "invoice_no", "total", "bank_details", "abn"],
  },
  "DT-22": {
    classifierLayout: "any_signal",
    routeConfidence: "strict",
    signals: [
      SIGNAL("text_dunning", "Body mentions dunning, overdue, or final demand", "Full document text"),
      SIGNAL("filename_dunning", "Filename contains dunning / overdue", "Attachment name"),
    ],
    defaultSignalIds: ["text_dunning", "filename_dunning"],
    extractionFields: ["vendor", "document_text", "attachment_name"],
  },
  "DT-23": {
    classifierLayout: "any_signal",
    signals: [
      SIGNAL("text_bank_change", "Body mentions bank detail change", "Full document text"),
      SIGNAL("filename_bank_change", "Filename contains bank detail / change of bank", "Attachment name"),
    ],
    defaultSignalIds: ["text_bank_change", "filename_bank_change"],
    extractionFields: ["vendor", "bank_details", "document_text"],
  },
  "DT-24": {
    classifierLayout: "any_signal",
    routeConfidence: "strict",
    signals: [
      SIGNAL("text_quote", "Body mentions quote, quotation, estimate, or proposal", "Full document text"),
      SIGNAL("filename_quote", "Filename contains quote / proposal", "Attachment name"),
    ],
    defaultSignalIds: ["text_quote", "filename_quote"],
    extractionFields: ["vendor", "document_text", "attachment_name"],
  },
  "DT-25": {
    classifierLayout: "any_signal",
    routeConfidence: "strict",
    signals: [
      SIGNAL("text_tax_notice", "Body mentions ATO or tax / compliance notice", "Full document text"),
      SIGNAL("filename_tax_notice", "Filename contains ATO / tax notice", "Attachment name"),
    ],
    defaultSignalIds: ["text_tax_notice", "filename_tax_notice"],
    extractionFields: ["vendor", "document_text", "attachment_name"],
  },
};

export function templateSignalMetaForCode(code: string): TemplateSignalMeta | null {
  return TEMPLATE_SIGNAL_META[code.trim().toUpperCase()] ?? null;
}
