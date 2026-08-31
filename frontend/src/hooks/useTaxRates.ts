import { useMutation, useQueryClient } from "@tanstack/react-query";

import { api } from "@/api/client";
import type { OrgTaxRateWrite, TaxRatesPayload } from "@/api/types";
import { useTenantQuery } from "@/hooks/useTenantQuery";
import { queryKeys } from "@/lib/queryClient";

async function applyTaxRatesCache(
  queryClient: ReturnType<typeof useQueryClient>,
  payload: TaxRatesPayload
) {
  queryClient.setQueryData(queryKeys.taxRates(), payload);
  await queryClient.refetchQueries({ queryKey: queryKeys.taxRates() });
  void queryClient.invalidateQueries({ queryKey: queryKeys.ruleBookConfig() });
}

export function useTaxRates(enabled = true) {
  return useTenantQuery({
    queryKey: queryKeys.taxRates(),
    queryFn: () => api.getTaxRates(),
    enabled,
    staleTime: 0,
    refetchOnMount: "always",
  });
}

export function useCreateTaxRate() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: OrgTaxRateWrite) => api.createTaxRate(body),
    onSuccess: async (payload) => {
      await applyTaxRatesCache(queryClient, payload);
    },
  });
}

export function useUpdateTaxRate() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ rateId, body }: { rateId: string; body: OrgTaxRateWrite }) =>
      api.updateTaxRate(rateId, body),
    onSuccess: async (payload) => {
      await applyTaxRatesCache(queryClient, payload);
    },
  });
}

export function useDeleteTaxRate() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (rateId: string) => api.deleteTaxRate(rateId),
    onSuccess: async (payload) => {
      await applyTaxRatesCache(queryClient, payload);
    },
  });
}

export function useSyncTaxRates() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => api.syncTaxRates(),
    onSuccess: async (payload) => {
      await applyTaxRatesCache(queryClient, payload);
    },
  });
}
