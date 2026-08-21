import { api, clearGetCache } from "@/api/client";
import type { ApiEnvelope, Invoice } from "@/api/types";
import { PIPELINE_STATUSES } from "@/lib/invoiceActions";

const DEFAULT_PAGE_SIZE = "100";

/** Statuses fetched for the approvals kanban beyond the /api/approvals queue. */
const BOARD_SUPPLEMENT_STATUSES = [...PIPELINE_STATUSES, "processed"] as const;

/** Newest ingested first; ties broken by higher invoice id. */
export function sortInvoicesNewestFirst(rows: Invoice[]): Invoice[] {
  return [...rows].sort((a, b) => {
    const byCreated =
      new Date(b.created_at).getTime() - new Date(a.created_at).getTime();
    if (byCreated !== 0) return byCreated;
    return b.id - a.id;
  });
}

/** Fetch every invoice page for the current org (newest first per API order). */
export async function fetchAllInvoices(
  fresh = false,
  params: Record<string, string> = {}
): Promise<Invoice[]> {
  if (fresh) clearGetCache();
  const first = await api.listInvoicesWithMeta(
    { page: "1", page_size: DEFAULT_PAGE_SIZE, ...params },
    { fresh }
  );
  const pages = first.meta.pages ?? 1;
  if (pages <= 1) return first.data;

  const rest = await Promise.all(
    Array.from({ length: pages - 1 }, (_, i) =>
      api.listInvoicesWithMeta({
        page: String(i + 2),
        page_size: DEFAULT_PAGE_SIZE,
        ...params,
      })
    )
  );
  return [...first.data, ...rest.flatMap((r) => r.data)];
}

/** Fetch all approval-queue invoices across pages. */
export async function fetchAllApprovals(fresh = false): Promise<Invoice[]> {
  const first = await api.listApprovalsWithMeta(
    { page: "1", page_size: DEFAULT_PAGE_SIZE },
    { fresh }
  );
  const pages = first.meta.pages ?? 1;
  if (pages <= 1) return first.data;

  const rest = await Promise.all(
    Array.from({ length: pages - 1 }, (_, i) =>
      api.listApprovalsWithMeta({
        page: String(i + 2),
        page_size: DEFAULT_PAGE_SIZE,
      })
    )
  );
  return [...first.data, ...rest.flatMap((r) => r.data)];
}

let boardFetchInflight: Promise<ApprovalsBoardResult> | null = null;

export type ApprovalsBoardResult = {
  rows: Invoice[];
  meta: ApiEnvelope<Invoice[]>["meta"];
};

export function clearInvoiceFetchDedupe(): void {
  boardFetchInflight = null;
}

/** Single-request payload for the approvals kanban board. */
export async function fetchApprovalsBoard(fresh = false): Promise<ApprovalsBoardResult> {
  if (fresh) {
    const payload = await api.listApprovalsBoard({ fresh: true });
    return { rows: payload.data, meta: payload.meta };
  }
  if (boardFetchInflight) {
    return boardFetchInflight;
  }
  boardFetchInflight = api.listApprovalsBoard().then((payload) => ({
    rows: payload.data,
    meta: payload.meta,
  })).finally(() => {
    boardFetchInflight = null;
  });
  return boardFetchInflight;
}

/**
 * Pipeline + recently processed rows for the approvals board (one page per status).
 * Prefer {@link fetchApprovalsBoard} — kept for backwards compatibility.
 */
export async function fetchBoardSupplementInvoices(fresh = false): Promise<Invoice[]> {
  const pages = await Promise.all(
    BOARD_SUPPLEMENT_STATUSES.map((status) =>
      api.listInvoicesWithMeta(
        { page: "1", page_size: DEFAULT_PAGE_SIZE, status },
        { fresh }
      )
    )
  );
  const byId = new Map<number, Invoice>();
  for (const page of pages) {
    for (const inv of page.data) {
      byId.set(inv.id, inv);
    }
  }
  return [...byId.values()];
}
