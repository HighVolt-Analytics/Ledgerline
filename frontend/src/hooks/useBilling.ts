import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "@/api/client";
import type { BillingState } from "@/api/types";
import { normalizeBillingState } from "@/lib/billingUtils";
import { queryKeys } from "@/lib/queryClient";

export function useBilling(enabled = true) {
  return useQuery({
    queryKey: [...queryKeys.billing(), "v2"],
    queryFn: async () => {
      const raw = await api.getBilling({ fresh: true });
      return normalizeBillingState(raw) as BillingState;
    },
    enabled,
    staleTime: 0,
  });
}

export function useBillingUsage(page = 1, enabled = true) {
  return useQuery({
    queryKey: [...queryKeys.billing(), "usage", page, "v2"],
    queryFn: () => api.getBillingUsage(page, 50, { fresh: true }),
    enabled,
    staleTime: 0,
    retry: (failureCount, error) => {
      if (error instanceof ApiError && error.status === 404) return false;
      return failureCount < 2;
    },
  });
}

export function useBillingMutations() {
  const queryClient = useQueryClient();

  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: queryKeys.billing() });

  return {
    topUp: async (amount: number) => {
      const state = await api.topUpBilling(amount);
      await invalidate();
      return state;
    },
    upgradeToStudio: async () => {
      const state = await api.upgradeBillingPlan();
      await invalidate();
      return state;
    },
  };
}
