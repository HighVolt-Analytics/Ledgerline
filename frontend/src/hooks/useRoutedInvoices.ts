import type { Invoice } from "@/api/types";
import { api } from "@/api/client";
import { useTenantQuery } from "@/hooks/useTenantQuery";
import { fetchRoutedInvoices } from "@/lib/routedInvoices";
import { queryKeys } from "@/lib/queryClient";

export function useRoutedInvoices(routeTarget: string, enabled = true) {
  return useTenantQuery({
    queryKey: queryKeys.routedInvoices(routeTarget),
    queryFn: () => fetchRoutedInvoices(routeTarget),
    enabled: enabled && Boolean(routeTarget),
  });
}

export function filterPayables(invoices: Invoice[]): Invoice[] {
  return invoices.filter(
    (inv) =>
      inv.status === "processed" &&
      inv.due_date != null &&
      inv.total != null &&
      Number(inv.total) > 0
  );
}

export function usePayablesQueue(enabled = true) {
  return useTenantQuery({
    queryKey: queryKeys.payablesQueue(),
    queryFn: async () => {
      const first = await api.listInvoicesWithMeta({
        page: "1",
        page_size: "100",
        status: "processed",
      });
      const pages = Math.min(first.meta?.pages ?? 1, 5);
      let rows = first.data;
      if (pages > 1) {
        const rest = await Promise.all(
          Array.from({ length: pages - 1 }, (_, i) =>
            api.listInvoicesWithMeta({
              page: String(i + 2),
              page_size: "100",
              status: "processed",
            })
          )
        );
        rows = [...rows, ...rest.flatMap((r) => r.data)];
      }
      return filterPayables(rows);
    },
    enabled,
  });
}
