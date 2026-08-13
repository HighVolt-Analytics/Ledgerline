import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import { useTenantQuery } from "@/hooks/useTenantQuery";
import { queryKeys, tenantQueryKey } from "@/lib/queryClient";
import {
  documentTypesFromRuleBookApi,
  ruleBookConfigFromApi,
  ruleBookConfigToApi,
} from "@/lib/ruleBookConfigApi";
import type { RuleBookConfigState } from "@/lib/v4RuleBookTypes";

export function useRuleBookConfig(enabled = true) {
  return useTenantQuery({
    queryKey: queryKeys.ruleBookConfig(),
    queryFn: async () => ruleBookConfigFromApi(await api.getRuleBookConfig()),
    enabled,
  });
}

/** Lean fetch for upload/matrix badges — document type labels only. */
export function useRuleBookDocumentTypes(enabled = true) {
  return useTenantQuery({
    queryKey: [...queryKeys.ruleBookConfig(), "document-types"],
    queryFn: async () =>
      documentTypesFromRuleBookApi(await api.getRuleBookConfig({ fields: "document_types" })),
    enabled,
  });
}

export type SaveRuleBookResult = {
  config: RuleBookConfigState;
};

export function useSaveRuleBookConfig() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (state: RuleBookConfigState): Promise<SaveRuleBookResult> => {
      const saved = await api.putRuleBookConfig(ruleBookConfigToApi(state));
      return { config: ruleBookConfigFromApi(saved) };
    },
    onSuccess: ({ config }) => {
      queryClient.setQueryData(queryKeys.ruleBookConfig(), config);
      queryClient.setQueryData([...queryKeys.ruleBookConfig(), "document-types"], config.documentTypes);
      void queryClient.invalidateQueries({ queryKey: tenantQueryKey(["invoices"]) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.purchases() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.navBadges() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.dashboardOverview("", 10) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.ruleBookChangelog() });
    },
  });
}

export function useDeleteRuleBookDocumentType() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (code: string): Promise<RuleBookConfigState> => {
      const saved = await api.deleteRuleBookDocumentType(code);
      return ruleBookConfigFromApi(saved);
    },
    onSuccess: (config) => {
      queryClient.setQueryData(queryKeys.ruleBookConfig(), config);
      void queryClient.invalidateQueries({ queryKey: tenantQueryKey(["invoices"]) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.purchases() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.navBadges() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.dashboardOverview("", 10) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.ruleBookChangelog() });
    },
  });
}
