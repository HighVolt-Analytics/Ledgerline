import type { Invoice, InvoiceDetails } from "@/api/types";

const VALIDATION_RULE_FIELDS: Record<string, readonly string[]> = {
  VR01: ["subtotal", "gst", "total"],
  VR02: ["invoice_no"],
  VR05: ["abn"],
  VR06: ["invoice_date", "due_date"],
  VR07: ["currency"],
  VR08: ["subtotal", "gst", "total"],
  VR09: ["line_items"],
  VR11: ["invoice_date"],
  VR12: ["vendor"],
  VR14: ["po_reference"],
  VR15: ["po_reference"],
};

const OPTIONAL_EXTRACTION_FIELDS = new Set([
  "po_reference",
  "cost_centre",
  "bank_details",
  "attachment_name",
  "document_text",
]);

function vr03MissingFields(message: string): string[] {
  const marker = "Missing:";
  const idx = message.indexOf(marker);
  if (idx < 0) return [];
  return message
    .slice(idx + marker.length)
    .split(",")
    .map((part) => part.trim())
    .filter(Boolean);
}

function vr03AppliesToField(token: string, fieldKey: string): boolean {
  if (token === fieldKey) return true;
  if (fieldKey === "line_items" && token.startsWith("line_items")) return true;
  return false;
}

function extractionFieldPopulated(inv: InvoiceDetails, fieldKey: string): boolean {
  if (fieldKey === "line_items") return inv.line_items.length > 0;
  if (fieldKey === "bank_details") {
    return Boolean(inv.bank_bsb?.trim() || inv.bank_account?.trim());
  }
  if (fieldKey === "attachment_name") {
    return Boolean(inv.email_attachment_name?.trim());
  }
  if (fieldKey === "document_text") {
    return Boolean(inv.document_text?.trim());
  }
  const record = inv as unknown as Record<string, unknown>;
  const value = record[fieldKey];
  if (value == null) return false;
  return String(value).trim().length > 0;
}

function validationFailedForField(inv: Invoice, fieldKey: string): boolean {
  for (const result of invoiceFailedValidations(inv)) {
    if (result.rule === "VR03") {
      if (vr03MissingFields(result.message).some((token) => vr03AppliesToField(token, fieldKey))) {
        return true;
      }
      continue;
    }
    const fields = VALIDATION_RULE_FIELDS[result.rule];
    if (fields?.includes(fieldKey)) return true;
  }
  return false;
}

function fallbackFieldConfidence(inv: InvoiceDetails, fieldKey: string): number {
  if (fieldKey === "attachment_name" && inv.email_attachment_name?.trim()) {
    return 97;
  }

  const populated = extractionFieldPopulated(inv, fieldKey);
  const failed = validationFailedForField(inv, fieldKey);

  if (!populated) {
    if (OPTIONAL_EXTRACTION_FIELDS.has(fieldKey)) return 52;
    return failed ? 16 : 18;
  }

  if (failed) return 48;
  return 86;
}

/** Per-field extraction confidence for invoice drawers (from API when available). */
export function invoiceFieldConfidence(inv: InvoiceDetails, fieldKey: string): number {
  const fromApi = inv.extraction_field_confidence?.[fieldKey];
  if (fromApi != null && Number.isFinite(fromApi)) {
    return Math.round(fromApi);
  }
  return fallbackFieldConfidence(inv, fieldKey);
}

/** Validation pass rate from API rules — null when not yet validated. */
export function invoiceValidationConfidence(inv: Invoice): number | null {
  const rules = inv.validation_results;
  if (!rules?.length) return null;
  const evaluated = rules.filter((r) => !r.skipped);
  if (evaluated.length === 0) return null;
  const passed = evaluated.filter((r) => r.passed).length;
  return Math.round((passed / evaluated.length) * 100);
}

/** Vendor match confidence from rule book evaluation — null before MAP step. */
export function invoiceVendorConfidence(inv: Invoice): number | null {
  if (inv.vendor_confidence == null) return null;
  return Math.round(inv.vendor_confidence);
}

export function evaluationStatusLabel(
  status: Invoice["evaluation_status"]
): string {
  if (status === "auto_coded") return "Auto coded";
  if (status === "needs_review") return "Needs review";
  if (status === "pending_vendor") return "Pending vendor";
  if (status === "unmatched_expense_vendor") return "Unmatched vendor";
  if (status === "awaiting_po") return "Awaiting PO";
  return "—";
}

/** Short hint for inbox Evaluation column tooltips. */
export function evaluationStatusDescription(
  status: Invoice["evaluation_status"]
): string {
  if (status === "auto_coded") {
    return "Route and coding rules matched — no manual routing step needed.";
  }
  if (status === "needs_review") {
    return "Document type, route, or GL mapping needs a human check before posting.";
  }
  if (status === "pending_vendor") {
    return "Vendor is not in master (VR12 on) — register in Vendors before processing.";
  }
  if (status === "unmatched_expense_vendor") {
    return "Small expense from an unknown vendor — advisory only, not held.";
  }
  if (status === "awaiting_po") {
    return "Purchase invoice is waiting for a PO link.";
  }
  return "Not evaluated yet — still parsing or mapping.";
}

export function routeTargetShortLabel(route: string | null | undefined): string {
  if (!route) return "—";
  if (route === "Purchase Management") return "Purchase";
  if (route === "Expenses Management") return "Expenses";
  if (route === "Team Expenses") return "Team";
  if (route === "Vault") return "Vault";
  return route;
}

export function invoiceFailedValidations(inv: Invoice) {
  return (inv.validation_results ?? []).filter((r) => !r.skipped && !r.passed);
}

/** Processed invoices with journal lines that can be posted to the workbook. */
export function invoiceCanPublishToLedger(inv: Invoice): boolean {
  if (inv.status !== "processed") return false;
  if (inv.published_to_ledger) return false;
  const route = (inv.route_target ?? "").trim().toLowerCase();
  if (route === "vault") return false;
  const docType = (inv.purchase_document_type ?? "").trim().toLowerCase();
  if (docType === "po" || docType === "grn") return false;
  return Boolean(inv.invoice_date);
}

export type InvoiceSource = "email" | "upload" | "onedrive" | "vault";
export type InvoiceDocType = "invoice" | "credit_note" | "po" | "grn";

export function invoiceSourceKind(inv: Invoice): InvoiceSource {
  const sender = (inv.email_sender ?? "").toLowerCase();
  if (sender.includes("onedrive") || sender.includes("sharepoint")) {
    return "onedrive";
  }
  if (inv.storage_vendor_slug && !inv.email_sender && !inv.connected_mailbox_id) {
    return "vault";
  }
  if (inv.email_sender || inv.connected_mailbox_id) {
    return "email";
  }
  return "upload";
}

export function invoiceSourceLabel(source: InvoiceSource): string {
  if (source === "email") return "Email";
  if (source === "onedrive") return "OneDrive";
  if (source === "vault") return "Vault";
  return "Direct upload";
}

export function invoiceDocumentType(inv: Invoice): InvoiceDocType {
  const purchaseType = inv.purchase_document_type?.toLowerCase();
  if (purchaseType === "po") return "po";
  if (purchaseType === "grn") return "grn";

  const ref = (inv.invoice_no ?? inv.po_reference ?? "").toLowerCase();
  if (
    ref.includes("credit") ||
    ref.includes("cn-") ||
    ref.startsWith("cn") ||
    ref.includes("credit-note")
  ) {
    return "credit_note";
  }
  for (const amount of [inv.total, inv.subtotal]) {
    if (amount == null || amount === "") continue;
    const n = parseFloat(String(amount));
    if (!Number.isNaN(n) && n < 0) return "credit_note";
  }
  return "invoice";
}

export function invoiceDocumentTypeLabel(type: InvoiceDocType): string {
  if (type === "credit_note") return "Credit Note";
  if (type === "po") return "Purchase Order";
  if (type === "grn") return "GRN";
  return "Invoice";
}

export function mailboxDisplayName(email: string, displayName: string | null): string {
  const label = displayName?.trim();
  if (label && !label.includes("@")) return label;
  const local = email.split("@")[0] ?? "Mailbox";
  return local.charAt(0).toUpperCase() + local.slice(1);
}

export function invoiceMatchesMailbox(inv: Invoice, mailboxId: number): boolean {
  return inv.connected_mailbox_id === mailboxId;
}