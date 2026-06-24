import type { Invoice, PurchaseOrderApi } from "@/api/types";
import { sortInvoicesNewestFirst } from "@/lib/invoices";

export type PurchaseRegisterCoverage = {
  invoiceIds: Set<number>;
  poDocumentIds: Set<number>;
  grnDocumentIds: Set<number>;
  poNumbers: Set<string>;
};

export function buildPurchaseRegisterCoverage(
  purchaseRows: PurchaseOrderApi[]
): PurchaseRegisterCoverage {
  const invoiceIds = new Set<number>();
  const poDocumentIds = new Set<number>();
  const grnDocumentIds = new Set<number>();
  const poNumbers = new Set<string>();

  for (const row of purchaseRows) {
    if (row.po_number?.trim()) poNumbers.add(row.po_number.trim());
    if (row.invoice_id != null) invoiceIds.add(row.invoice_id);
    if (row.po_document_id != null) poDocumentIds.add(row.po_document_id);
    if (row.grn_document_id != null) grnDocumentIds.add(row.grn_document_id);
  }

  return { invoiceIds, poDocumentIds, grnDocumentIds, poNumbers };
}

export function purchaseInvoiceNeedsAction(
  inv: Invoice,
  coverage: PurchaseRegisterCoverage
): boolean {
  const docType = (inv.purchase_document_type ?? "").trim().toLowerCase();
  if (docType === "po") {
    return !coverage.poDocumentIds.has(inv.id);
  }
  if (docType === "grn") {
    return !coverage.grnDocumentIds.has(inv.id);
  }
  return !coverage.invoiceIds.has(inv.id);
}

export function purchaseActionIssue(
  inv: Invoice,
  coverage: PurchaseRegisterCoverage
): string {
  const docType = (inv.purchase_document_type ?? "").trim().toLowerCase();
  if (docType === "po") return "PO document not linked to register";
  if (docType === "grn") return "GRN document not linked to register";

  const poRef = inv.po_reference?.trim();
  if (!poRef) return "Missing PO reference";
  if (!coverage.poNumbers.has(poRef)) return `PO ${poRef} not in register`;
  return "Awaiting register sync";
}

export function purchaseActionRequiredInvoices(
  routed: Invoice[],
  purchaseRows: PurchaseOrderApi[]
): Invoice[] {
  const coverage = buildPurchaseRegisterCoverage(purchaseRows);
  return sortInvoicesNewestFirst(
    routed.filter((inv) => purchaseInvoiceNeedsAction(inv, coverage))
  );
}
