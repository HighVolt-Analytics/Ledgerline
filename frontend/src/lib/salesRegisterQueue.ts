import type { Invoice, SalesOrderApi } from "@/api/types";
import { sortInvoicesNewestFirst } from "@/lib/invoices";

export type SalesRegisterCoverage = {
  invoiceIds: Set<number>;
  soDocumentIds: Set<number>;
  dnDocumentIds: Set<number>;
  soNumbers: Set<string>;
};

export function buildSalesRegisterCoverage(salesRows: SalesOrderApi[]): SalesRegisterCoverage {
  const invoiceIds = new Set<number>();
  const soDocumentIds = new Set<number>();
  const dnDocumentIds = new Set<number>();
  const soNumbers = new Set<string>();

  for (const row of salesRows) {
    if (row.so_number?.trim()) soNumbers.add(row.so_number.trim().toUpperCase());
    if (row.invoice_id != null) invoiceIds.add(row.invoice_id);
    if (row.so_document_id != null) soDocumentIds.add(row.so_document_id);
    if (row.dn_document_id != null) dnDocumentIds.add(row.dn_document_id);
  }

  return { invoiceIds, soDocumentIds, dnDocumentIds, soNumbers };
}

export function salesInvoiceNeedsAction(
  inv: Invoice,
  coverage: SalesRegisterCoverage
): boolean {
  const docType = (inv.sales_document_type ?? "").trim().toLowerCase();
  if (docType === "so") {
    return !coverage.soDocumentIds.has(inv.id);
  }
  if (docType === "dn") {
    return !coverage.dnDocumentIds.has(inv.id);
  }
  return !coverage.invoiceIds.has(inv.id);
}

export function salesActionIssue(inv: Invoice, coverage: SalesRegisterCoverage): string {
  const docType = (inv.sales_document_type ?? "").trim().toLowerCase();
  if (docType === "so") return "SO document not linked to register";
  if (docType === "dn") return "DN document not linked to register";

  const soRef = inv.so_reference?.trim().toUpperCase();
  if (!soRef) return "Missing SO reference";
  if (!coverage.soNumbers.has(soRef)) return `SO ${inv.so_reference?.trim()} not in register`;
  return "Awaiting register sync";
}

export function salesActionRequiredInvoices(
  routed: Invoice[],
  salesRows: SalesOrderApi[]
): Invoice[] {
  const coverage = buildSalesRegisterCoverage(salesRows);
  return sortInvoicesNewestFirst(
    routed.filter((inv) => salesInvoiceNeedsAction(inv, coverage))
  );
}
