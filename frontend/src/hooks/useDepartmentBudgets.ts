import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import type { DepartmentBudgetRow } from "@/api/types";
import { useTenantQuery } from "@/hooks/useTenantQuery";
import { queryKeys } from "@/lib/queryClient";

export function useDepartmentBudgets(enabled = true) {
  return useTenantQuery({
    queryKey: queryKeys.departmentBudgets(),
    queryFn: () => api.listDepartmentBudgets(),
    enabled,
  });
}

export function useCreateDepartmentBudget() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: {
      department: string;
      gl_ledger?: string;
      period_kind: "monthly" | "quarterly" | "annual";
      period_key: string;
      allocated: number;
      notes?: string | null;
    }) => api.createDepartmentBudget(body),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.departmentBudgets() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.teDepartmentBudgetUtilization() });
    },
  });
}

export function useDeleteDepartmentBudget() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (budgetId: number) => api.deleteDepartmentBudget(budgetId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.departmentBudgets() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.teDepartmentBudgetUtilization() });
    },
  });
}

export type { DepartmentBudgetRow };
