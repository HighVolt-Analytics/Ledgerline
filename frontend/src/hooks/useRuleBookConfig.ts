import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import { queryKeys } from "@/lib/queryClient";
import { ruleBookConfigFromApi, ruleBookConfigToApi } from "@/lib/ruleBookConfigApi";
import type { RuleBookConfigState } from "@/lib/v4RuleBookTypes";

export function useRuleBookConfig(enabled = true) {
  return useQuery({
    queryKey: queryKeys.ruleBookConfig,
    queryFn: async () => ruleBookConfigFromApi(await api.getRuleBookConfig()),
    enabled,
  });
}

export type SaveRuleBookResult = {
  config: RuleBookConfigState;
  remapped: number;
};

export function useSaveRuleBookConfig() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (state: RuleBookConfigState): Promise<SaveRuleBookResult> => {
      const saved = await api.putRuleBookConfig(ruleBookConfigToApi(state));
      let remapped = 0;
      try {
        const result = await api.remapInvoices();
        remapped = result.updated;
      } catch {
        // Save succeeded; remap is best-effort so editors are not blocked.
      }
      return { config: ruleBookConfigFromApi(saved), remapped };
    },
    onSuccess: ({ config }) => {
      queryClient.setQueryData(queryKeys.ruleBookConfig, config);
      void queryClient.invalidateQueries({ queryKey: ["invoices"] });
      void queryClient.invalidateQueries({ queryKey: queryKeys.navBadges });
      void queryClient.invalidateQueries({ queryKey: queryKeys.dashboardOverview("", 10) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.ruleBookChangelog });
    },
  });
}
