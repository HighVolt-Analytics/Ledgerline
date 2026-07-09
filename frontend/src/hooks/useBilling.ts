import { useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "@/api/client";
import type { BillingState, CheckoutSessionResult } from "@/api/types";
import { useTenantQuery } from "@/hooks/useTenantQuery";
import { normalizeBillingState } from "@/lib/billingUtils";
import { queryKeys } from "@/lib/queryClient";

function isCheckoutSession(
  value: BillingState | CheckoutSessionResult
): value is CheckoutSessionResult {
  return "session_id" in value || "checkout_url" in value || "completed_without_checkout" in value;
}

export function useBilling(enabled = true) {
  return useTenantQuery({
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
  return useTenantQuery({
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
    createTopUpCheckout: async (amount: number) => {
      const session = await api.createTopUpCheckout(amount);
      return session;
    },
    upgradeToStudio: async () => {
      const result = await api.upgradeBillingPlan();
      if (isCheckoutSession(result)) {
        return result;
      }
      await invalidate();
      return result;
    },
  };
}
