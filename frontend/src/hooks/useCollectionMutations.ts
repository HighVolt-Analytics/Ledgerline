import { useCallback, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import { queryKeys } from "@/lib/queryClient";

export function useCollectionMutations() {
  const queryClient = useQueryClient();
  const [busyId, setBusyId] = useState<number | null>(null);
  const [toast, setToast] = useState<string | null>(null);

  const invalidate = useCallback(async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: queryKeys.collections() }),
      queryClient.invalidateQueries({ queryKey: queryKeys.collectionsWorkspaceKpis() }),
      queryClient.invalidateQueries({ queryKey: queryKeys.navBadges() }),
    ]);
  }, [queryClient]);

  const markReceived = useCallback(
    async (collectionId: number, body?: { received_date?: string; note?: string }) => {
      setBusyId(collectionId);
      try {
        const row = await api.markCollectionReceived(collectionId, body);
        await invalidate();
        setToast(`Payment received from ${row.customer ?? "customer"}`);
        return row;
      } catch (e) {
        setToast(e instanceof Error ? e.message : "Mark received failed");
        return null;
      } finally {
        setBusyId(null);
      }
    },
    [invalidate]
  );

  return {
    markReceived,
    busyId,
    toast,
    setToast,
    invalidate,
  };
}
