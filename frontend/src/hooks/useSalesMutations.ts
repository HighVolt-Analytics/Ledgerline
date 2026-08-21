import { useCallback, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import { queryKeys } from "@/lib/queryClient";

const ROUTE_TARGET = "Sales Management";

export function useSalesMutations() {
  const queryClient = useQueryClient();
  const [busyId, setBusyId] = useState<number | null>(null);
  const [toast, setToast] = useState<string | null>(null);

  const invalidate = useCallback(async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: queryKeys.sales() }),
      queryClient.invalidateQueries({ queryKey: queryKeys.salesWorkspaceKpis() }),
      queryClient.invalidateQueries({ queryKey: queryKeys.salesTwoWay() }),
      queryClient.invalidateQueries({ queryKey: queryKeys.routedInvoices(ROUTE_TARGET) }),
      queryClient.invalidateQueries({ queryKey: queryKeys.collections() }),
      queryClient.invalidateQueries({ queryKey: queryKeys.navBadges() }),
    ]);
  }, [queryClient]);

  const approveVariance = useCallback(
    async (salesOrderId: number) => {
      setBusyId(salesOrderId);
      try {
        const row = await api.approveSalesVariance(salesOrderId);
        await invalidate();
        setToast(`Variance approved for ${row.so_number}`);
        return row;
      } catch (e) {
        setToast(e instanceof Error ? e.message : "Approve variance failed");
        return null;
      } finally {
        setBusyId(null);
      }
    },
    [invalidate]
  );

  const recordDeliveryNote = useCallback(
    async (
      salesOrderId: number,
      body: { dn_qty: number; dn_date?: string; shipper?: string; condition_note?: string }
    ) => {
      setBusyId(salesOrderId);
      try {
        const row = await api.recordDeliveryNote(salesOrderId, body);
        await invalidate();
        setToast(`Delivery note recorded for ${row.so_number}`);
        return row;
      } catch (e) {
        setToast(e instanceof Error ? e.message : "Delivery note recording failed");
        return null;
      } finally {
        setBusyId(null);
      }
    },
    [invalidate]
  );

  return {
    approveVariance,
    recordDeliveryNote,
    busyId,
    toast,
    setToast,
    invalidate,
  };
}
