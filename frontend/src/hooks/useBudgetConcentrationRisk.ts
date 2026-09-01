import { api } from "@/api/client";
import { useTenantQuery } from "@/hooks/useTenantQuery";
import { queryKeys } from "@/lib/queryClient";

export function useBudgetConcentrationRisk() {
  return useTenantQuery({
    queryKey: queryKeys.budgetConcentrationRisk(),
    queryFn: () => api.getBudgetConcentrationRisk(),
    staleTime: 60_000,
    placeholderData: (previousData) => previousData,
  });
}
