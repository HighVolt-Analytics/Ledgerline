import { useQuery } from "@tanstack/react-query";
import type { Invoice } from "@/api/types";
import { fetchAllInvoices } from "@/lib/invoices";
import { queryKeys } from "@/lib/queryClient";

export function useRoutedInvoices(routeTarget: string, enabled = true) {
  return useQuery({
    queryKey: queryKeys.routedInvoices(routeTarget),
    queryFn: () => fetchAllInvoices(true, { route_target: routeTarget }),
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
  return useQuery({
    queryKey: queryKeys.payablesQueue(),
    queryFn: async () => {
      const rows = await fetchAllInvoices(true, { status: "processed" });
      return filterPayables(rows);
    },
    enabled,
  });
}
