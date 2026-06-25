import type { Invoice } from "@/api/types";
import { documentDisplayRef, vendorInvoiceNo } from "@/lib/format";

export function normalizeListSearchQuery(raw: string): string {
  return raw.trim().toLowerCase();
}

/** True when query is empty or any value contains the query (case-insensitive). */
export function matchesListSearch(
  query: string,
  ...values: Array<string | number | null | undefined>
): boolean {
  const q = normalizeListSearchQuery(query);
  if (!q) return true;
  return values.some((value) => {
    if (value == null || value === "") return false;
    return String(value).toLowerCase().includes(q);
  });
}

export function invoiceMatchesListSearch(inv: Invoice, query: string): boolean {
  return matchesListSearch(
    query,
    inv.id,
    inv.document_ref,
    inv.invoice_no,
    inv.vendor,
    inv.po_reference,
    inv.route_target,
    inv.account_name,
    inv.account_code,
    inv.cost_centre,
    inv.status,
    inv.purchase_document_type,
    inv.document_type_code,
    inv.evaluation_status,
    inv.email_attachment_name,
    inv.email_subject,
    documentDisplayRef(inv),
    vendorInvoiceNo(inv),
  );
}
