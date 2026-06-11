import type { Invoice } from "@/api/types";

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
