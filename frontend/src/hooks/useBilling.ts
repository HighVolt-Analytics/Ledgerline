import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import { queryKeys } from "@/lib/queryClient";

export function useBilling(enabled = true) {
  return useQuery({
    queryKey: queryKeys.billing,
    queryFn: () => api.getBilling(),
    enabled,
  });
}

export function useBillingMutations() {
  const queryClient = useQueryClient();

  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: queryKeys.billing });

  return {
    updateSettings: async (body: { auto_recharge?: boolean; threshold?: number }) => {
      const state = await api.patchBilling(body);
      await invalidate();
      return state;
    },
    purchasePack: async (packId: string) => {
      const state = await api.purchaseBillingPack(packId);
      await invalidate();
      return state;
    },
  };
}
