import { api } from "@/api/client";
import type { Invoice } from "@/api/types";

const DEFAULT_PAGE_SIZE = "100";

/** Fetch every invoice page for the current org (newest first per API order). */
export async function fetchAllInvoices(
  fresh = false,
  params: Record<string, string> = {}
): Promise<Invoice[]> {
  const all: Invoice[] = [];
  let page = 1;
  let pages = 1;
  do {
    const res = await api.listInvoicesWithMeta(
      { page: String(page), page_size: DEFAULT_PAGE_SIZE, ...params },
      { fresh: fresh && page === 1 }
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
      { fresh: fresh && page === 1 }
    );
    all.push(...res.data);
    pages = res.meta.pages ?? 1;
    page += 1;
  } while (page <= pages);
  return all;
}
