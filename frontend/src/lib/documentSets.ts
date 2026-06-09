import type { Invoice } from "@/api/types";

/** Match invoices to a vault document set pattern (PO or invoice number). */
export function invoiceMatchesDocSet(inv: Invoice, pattern: string): boolean {
  const needle = pattern.toLowerCase();
  const po = (inv.po_reference ?? "").toLowerCase();
  const docNo = (inv.invoice_no ?? "").toLowerCase();
  return po === needle || po.includes(needle) || docNo.includes(needle);
}
