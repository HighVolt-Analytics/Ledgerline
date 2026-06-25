import { api, clearGetCache } from "@/api/client";
import type { Invoice } from "@/api/types";
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
  const all: Invoice[] = [];
  let page = 1;
  let pages = 1;
  do {
    const res = await api.listInvoicesWithMeta(
      { page: String(page), page_size: DEFAULT_PAGE_SIZE, ...params },
      { fresh }
    );
    all.push(...res.data);
    pages = res.meta.pages ?? 1;
    page += 1;
  } while (page <= pages);
  return all;
}

/** Fetch all approval-queue invoices across pages. */
export async function fetchAllApprovals(fresh = false): Promise<Invoice[]> {
  const all: Invoice[] = [];
  let page = 1;
  let pages = 1;
  do {
    const res = await api.listApprovalsWithMeta(
      { page: String(page), page_size: DEFAULT_PAGE_SIZE },
      { fresh }
    );
    all.push(...res.data);
    pages = res.meta.pages ?? 1;
    page += 1;
  } while (page <= pages);
  return all;
}

let boardFetchInflight: Promise<Invoice[]> | null = null;

/** Single-request payload for the approvals kanban board. */
export async function fetchApprovalsBoard(fresh = false): Promise<Invoice[]> {
  if (fresh) {
    return api.listApprovalsBoard({ fresh: true });
  }
  if (boardFetchInflight) {
    return boardFetchInflight;
  }
  boardFetchInflight = api.listApprovalsBoard().finally(() => {
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
