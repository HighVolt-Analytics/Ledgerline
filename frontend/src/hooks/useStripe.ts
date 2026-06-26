import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "@/api/client";
import type { StripeAccount, StripeConnectResponse } from "@/api/types";
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
  await queryClient.invalidateQueries({
    predicate: (query) => query.queryKey[0] === "stripeTransactions",
  });
}

export function useStripeAccount(enabled = true) {
  return useQuery({
    queryKey: queryKeys.stripeAccount(),
    queryFn: fetchStripeAccount,
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

export function useStripeBalance(enabled = true) {
  return useQuery({
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
  return useQuery({
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
