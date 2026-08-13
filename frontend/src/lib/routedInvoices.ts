import { api } from "@/api/client";
import type { Invoice } from "@/api/types";

const ROUTED_PAGE_SIZE = "100";
const MAX_ROUTED_PAGES = 5;

/** Fetch routed invoices with a bounded page walk (lean list payloads). */
export async function fetchRoutedInvoices(
  routeTarget: string,
  extra: Record<string, string> = {}
): Promise<Invoice[]> {
  const first = await api.listInvoicesWithMeta({
    page: "1",
    page_size: ROUTED_PAGE_SIZE,
    route_target: routeTarget,
    ...extra,
  });
  const pages = Math.min(first.meta?.pages ?? 1, MAX_ROUTED_PAGES);
  if (pages <= 1) return first.data;

  const rest = await Promise.all(
    Array.from({ length: pages - 1 }, (_, i) =>
      api.listInvoicesWithMeta({
        page: String(i + 2),
        page_size: ROUTED_PAGE_SIZE,
        route_target: routeTarget,
        ...extra,
      })
    )
  );
  return [...first.data, ...rest.flatMap((r) => r.data)];
}
