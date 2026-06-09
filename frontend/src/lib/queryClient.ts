import { QueryClient } from "@tanstack/react-query";

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      gcTime: 5 * 60_000,
      refetchOnWindowFocus: true,
      retry: 1,
    },
  },
});

export const queryKeys = {
  navBadges: ["dashboard", "badges"] as const,
  dashboardOverview: (month: string, activityLimit: number) =>
    ["dashboard", "overview", month, activityLimit] as const,
  reportsAnalytics: (month: string) => ["reports", "analytics", month] as const,
  reportDocuments: (dateFrom?: string, dateTo?: string) =>
    ["reports", "documents", dateFrom ?? "all", dateTo ?? "all"] as const,
  reconciliationOverview: ["reconciliation", "overview"] as const,
  ruleBookConfig: ["rule-book", "config"] as const,
  ruleBookChangelog: ["rule-book", "changelog"] as const,
  vendorMasters: ["vendor-masters"] as const,
  employeeMasters: ["employee-masters"] as const,
  pendingVendors: ["pending-vendors"] as const,
  routedInvoices: (routeTarget: string) => ["invoices", "routed", routeTarget] as const,
  payablesQueue: ["invoices", "payables"] as const,
};
