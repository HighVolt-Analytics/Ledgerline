import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import { useTenantQuery } from "@/hooks/useTenantQuery";
import { queryKeys, tenantQueryKey } from "@/lib/queryClient";
import {
  documentTypesFromRuleBookApi,
  expenseRulesFromRuleBookApi,
  purchaseRulesFromRuleBookApi,
  salesRulesFromRuleBookApi,
  ruleBookConfigFromApi,
  ruleBookConfigToApi,
  teamExpenseRulesFromRuleBookApi,
} from "@/lib/ruleBookConfigApi";
import type { RuleBookConfigState, VendorDetectionConfig } from "@/lib/v4RuleBookTypes";
import { DEFAULT_VENDOR_DETECTION_CONFIG } from "@/lib/v4RuleBookTypes";

export function useRuleBookConfig(enabled = true) {
  return useTenantQuery({
    queryKey: queryKeys.ruleBookConfig(),
    queryFn: async () => ruleBookConfigFromApi(await api.getRuleBookConfig()),
    enabled,
  });
}

/** Full editor payload without vendor/employee master hydration. */
export function useRuleBookEditorConfig(enabled = true) {
  return useTenantQuery({
    queryKey: [...queryKeys.ruleBookConfig(), "editor"],
    queryFn: async () =>
      ruleBookConfigFromApi(await api.getRuleBookConfig({ fields: "editor" })),
    enabled,
  });
}

export function useRuleBookIngestStats(enabled = true) {
  return useTenantQuery({
    queryKey: [...queryKeys.ruleBookConfig(), "ingest-stats"],
    queryFn: async () => {
      const raw = await api.getRuleBookConfig({ fields: "ingest_stats" });
      return (raw.email_capture_ingest_stats ?? {}) as Record<
        string,
        { matched_count: number; last_matched: string }
      >;
    },
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

export function useRuleBookVendorDetection(enabled = true) {
  return useTenantQuery({
    queryKey: [...queryKeys.ruleBookConfig(), "vendor-detection"],
    queryFn: async () => {
      const raw = await api.getRuleBookConfig({ fields: "vendor_detection" });
      return {
        weights: raw.vendor_detection_config?.weights ?? DEFAULT_VENDOR_DETECTION_CONFIG.weights,
        threshold: raw.vendor_detection_config?.threshold ?? DEFAULT_VENDOR_DETECTION_CONFIG.threshold,
      };
    },
    enabled,
  });
}

export function useRuleBookTeamExpensePosting(enabled = true) {
  return useTenantQuery({
    queryKey: [...queryKeys.ruleBookConfig(), "team-expense-posting"],
    queryFn: async () => {
      const raw = await api.getRuleBookConfig({ fields: "team_expense_posting" });
      return {
        defaultAdvanceParentLedger:
          raw.team_expense_posting?.default_advance_parent_ledger ?? "",
        settlementAccount: raw.team_expense_posting?.settlement_account ?? "",
      };
    },
    enabled,
  });
}

export function useRuleBookTeamExpensesWorkspace(enabled = true) {
  return useTenantQuery({
    queryKey: [...queryKeys.ruleBookConfig(), "team-expenses"],
    queryFn: async () => {
      const raw = await api.getRuleBookConfig({ fields: "team_expenses" });
      return {
        teamExpenseRules: teamExpenseRulesFromRuleBookApi(raw),
        teamExpensePosting: {
          defaultAdvanceParentLedger:
            raw.team_expense_posting?.default_advance_parent_ledger ?? "",
          settlementAccount: raw.team_expense_posting?.settlement_account ?? "",
        },
      };
    },
    enabled,
  });
}

export function useRuleBookExpenseRules(enabled = true) {
  return useTenantQuery({
    queryKey: [...queryKeys.ruleBookConfig(), "expense-rules"],
    queryFn: async () =>
      expenseRulesFromRuleBookApi(await api.getRuleBookConfig({ fields: "expense_rules" })),
    enabled,
  });
}

export function useRuleBookPurchaseRules(enabled = true) {
  return useTenantQuery({
    queryKey: [...queryKeys.ruleBookConfig(), "purchase-rules"],
    queryFn: async () =>
      purchaseRulesFromRuleBookApi(await api.getRuleBookConfig({ fields: "purchase_rules" })),
    enabled,
  });
}

export function useRuleBookSalesRules(enabled = true) {
  return useTenantQuery({
    queryKey: [...queryKeys.ruleBookConfig(), "sales-rules"],
    queryFn: async () =>
      salesRulesFromRuleBookApi(await api.getRuleBookConfig({ fields: "sales_rules" })),
    enabled,
  });
}

export function useSaveRuleBookVendorDetection() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (config: VendorDetectionConfig): Promise<VendorDetectionConfig> => {
      const saved = await api.putRuleBookVendorDetection({
        weights: config.weights,
        threshold: config.threshold,
      });
      return {
        weights: saved.vendor_detection_config?.weights ?? config.weights,
        threshold: saved.vendor_detection_config?.threshold ?? config.threshold,
      };
    },
    onSuccess: (config) => {
      queryClient.setQueryData([...queryKeys.ruleBookConfig(), "vendor-detection"], config);
      queryClient.setQueryData(
        queryKeys.ruleBookConfig(),
        (prev: RuleBookConfigState | undefined) =>
          prev ? { ...prev, vendorDetectionConfig: config } : prev
      );
      void queryClient.invalidateQueries({ queryKey: queryKeys.ruleBookChangelog() });
    },
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
      queryClient.setQueryData([...queryKeys.ruleBookConfig(), "editor"], config);
      queryClient.setQueryData(
        queryKeys.ruleBookConfig(),
        (prev: RuleBookConfigState | undefined) =>
          prev
            ? {
                ...config,
                vendorMasters: prev.vendorMasters,
                employeeMasters: prev.employeeMasters,
              }
            : prev
      );
      queryClient.setQueryData([...queryKeys.ruleBookConfig(), "document-types"], config.documentTypes);
      queryClient.setQueryData(
        [...queryKeys.ruleBookConfig(), "vendor-detection"],
        config.vendorDetectionConfig
      );
      queryClient.setQueryData(
        [...queryKeys.ruleBookConfig(), "team-expense-posting"],
        config.teamExpensePosting
      );
      queryClient.setQueryData(
        [...queryKeys.ruleBookConfig(), "expense-rules"],
        config.expenseRules
      );
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
      queryClient.setQueryData([...queryKeys.ruleBookConfig(), "editor"], config);
      queryClient.setQueryData(
        queryKeys.ruleBookConfig(),
        (prev: RuleBookConfigState | undefined) =>
          prev
            ? {
                ...config,
                vendorMasters: prev.vendorMasters,
                employeeMasters: prev.employeeMasters,
              }
            : prev
      );
      queryClient.setQueryData([...queryKeys.ruleBookConfig(), "document-types"], config.documentTypes);
      void queryClient.invalidateQueries({ queryKey: tenantQueryKey(["invoices"]) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.purchases() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.navBadges() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.dashboardOverview("", 10) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.ruleBookChangelog() });
    },
  });
}
