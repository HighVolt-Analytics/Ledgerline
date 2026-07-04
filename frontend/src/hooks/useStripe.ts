import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "@/api/client";
import type { StripeAccount, StripeConnectResponse } from "@/api/types";
import { useTenantQuery } from "@/hooks/useTenantQuery";
import { queryKeys } from "@/lib/queryClient";

async function fetchStripeAccount(): Promise<StripeAccount | null> {
  try {
    return await api.getStripeAccount();
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) {
      return null;
    }
    throw err;
  }
}

async function invalidateStripeQueries(
  queryClient: ReturnType<typeof useQueryClient>
) {
  await queryClient.invalidateQueries({ queryKey: queryKeys.stripeAccount() });
  await queryClient.invalidateQueries({ queryKey: queryKeys.stripeBalance() });
  await queryClient.invalidateQueries({ queryKey: queryKeys.stripeReadiness() });
  await queryClient.invalidateQueries({
    predicate: (query) => query.queryKey.includes("stripeTransactions"),
  });
}

export function useStripeAccount(enabled = true) {
  return useTenantQuery({
    queryKey: queryKeys.stripeAccount(),
    queryFn: fetchStripeAccount,
    enabled,
  });
}

export function useStripeReadiness(enabled = true) {
  return useTenantQuery({
    queryKey: queryKeys.stripeReadiness(),
    queryFn: () => api.getStripeReadiness(),
    enabled,
  });
}

export function useConnectStripe() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (): Promise<StripeConnectResponse> => api.connectStripe(),
    onSuccess: async () => {
      await invalidateStripeQueries(queryClient);
    },
  });
}

export function useStripeOnboardingLink() {
  return useMutation({
    mutationFn: () => api.getStripeOnboardingLink(),
  });
}

export function useStripeOAuthUrl() {
  return useMutation({
    mutationFn: () => api.getStripeOAuthUrl(),
  });
}

export function useDisconnectStripe() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: () => api.deleteStripeAccount(),
    onSuccess: async () => {
      await invalidateStripeQueries(queryClient);
    },
  });
}

export function useRefreshStripeAccount() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: () => api.refreshStripeAccount(),
    onSuccess: async () => {
      await invalidateStripeQueries(queryClient);
    },
  });
}

export function useStripeGlobalPayoutsReadiness(enabled = true) {
  return useTenantQuery({
    queryKey: queryKeys.stripeGlobalPayoutsReadiness(),
    queryFn: () => api.getStripeGlobalPayoutsReadiness(),
    enabled,
  });
}

export function useStripeBalance(enabled = true) {
  return useTenantQuery({
    queryKey: queryKeys.stripeBalance(),
    queryFn: async () => {
      try {
        return await api.getStripeBalance();
      } catch (err) {
        if (err instanceof ApiError && err.status === 404) {
          return null;
        }
        throw err;
      }
    },
    enabled,
  });
}

export function useStripeTransactions(limit = 20, enabled = true) {
  return useTenantQuery({
    queryKey: queryKeys.stripeTransactions(limit),
    queryFn: async () => {
      try {
        return await api.listStripeTransactions(limit);
      } catch (err) {
        if (err instanceof ApiError && err.status === 404) {
          return [];
        }
        throw err;
      }
    },
    enabled,
  });
}
