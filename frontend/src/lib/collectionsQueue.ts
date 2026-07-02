import type { CollectionApi } from "@/api/types";
import type { CollectionRecord, CollectionTab } from "@/lib/v4MockData";

export function apiCollectionToRecord(row: CollectionApi): CollectionRecord {
  return {
    id: String(row.id),
    invoiceId: String(row.invoice_id),
    customer: row.customer ?? "—",
    amount: row.amount,
    currency: row.currency,
    dueDate: row.due_date ?? "—",
    tab: row.tab as CollectionTab,
    receivedDate: row.received_date ?? undefined,
    failureReason: row.failure_reason ?? undefined,
  };
}

export function collectionsOpenCount(rows: CollectionApi[]): number {
  return rows.filter((row) => row.tab === "queue" || row.tab === "awaiting").length;
}

export function collectionsByTab(rows: CollectionRecord[], tab: CollectionTab): CollectionRecord[] {
  return rows.filter((row) => row.tab === tab);
}
