import { api } from "@/api/client";
import type { Invoice } from "@/api/types";

const ROUTED_PAGE_SIZE = "100";
const MAX_ROUTED_PAGES = 5;

/** Fetch routed invoices with a bounded page walk (lean list payloads). */
export async function fetchRoutedInvoices(
  routeTarget: string,
  extra: Record<string, string> = {},
  options?: { pageSize?: number; maxPages?: number }
): Promise<Invoice[]> {
  const pageSize = String(options?.pageSize ?? Number(ROUTED_PAGE_SIZE));
  const maxPages = options?.maxPages ?? MAX_ROUTED_PAGES;
  const first = await api.listInvoicesWithMeta({
    page: "1",
    page_size: pageSize,
    route_target: routeTarget,
    ...(maxPages <= 1 ? { include_total: "false" } : {}),
    ...extra,
  });
  const pages = Math.min(first.meta?.pages ?? 1, maxPages);
  if (pages <= 1) return first.data;

  const rest = await Promise.all(
    Array.from({ length: pages - 1 }, (_, i) =>
      api.listInvoicesWithMeta({
        page: String(i + 2),
        page_size: pageSize,
        route_target: routeTarget,
        ...extra,
      })
    )
  );
  return [...first.data, ...rest.flatMap((r) => r.data)];
}
