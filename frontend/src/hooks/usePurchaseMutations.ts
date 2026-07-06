import { useCallback, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import { queryKeys } from "@/lib/queryClient";

const ROUTE_TARGET = "Purchase Management";

export function usePurchaseMutations() {
  const queryClient = useQueryClient();
  const [busyId, setBusyId] = useState<number | null>(null);
  const [toast, setToast] = useState<string | null>(null);

  const invalidate = useCallback(async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: queryKeys.purchases() }),
      queryClient.invalidateQueries({ queryKey: queryKeys.purchasesTwoWay() }),
      queryClient.invalidateQueries({ queryKey: queryKeys.routedInvoices(ROUTE_TARGET) }),
      queryClient.invalidateQueries({ queryKey: queryKeys.navBadges() }),
    ]);
  }, [queryClient]);

  const approveVariance = useCallback(
    async (purchaseOrderId: number) => {
      setBusyId(purchaseOrderId);
      try {
        const row = await api.approvePurchaseVariance(purchaseOrderId);
        await invalidate();
        setToast(`Variance approved for ${row.po_number}`);
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

  const recordGrn = useCallback(
    async (
      purchaseOrderId: number,
      body: { grn_qty: number; grn_date?: string; receiver?: string; condition_note?: string }
    ) => {
      setBusyId(purchaseOrderId);
      try {
        const row = await api.recordGoodsReceipt(purchaseOrderId, body);
        await invalidate();
        setToast(`GRN recorded for ${row.po_number}`);
        return row;
      } catch (e) {
        setToast(e instanceof Error ? e.message : "GRN recording failed");
        return null;
      } finally {
        setBusyId(null);
      }
    },
    [invalidate]
  );

  return {
    approveVariance,
    recordGrn,
    busyId,
    toast,
    setToast,
    invalidate,
  };
}
