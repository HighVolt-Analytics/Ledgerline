import { QueryClient } from "@tanstack/react-query";
import { getActiveTenantId } from "@/api/client";

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 60_000,
      gcTime: 5 * 60_000,
      refetchOnWindowFocus: false,
      retry: 1,
      structuralSharing: false,
    },
  },
});

/** Active tenant from JWT — prefixes every query key to prevent cross-tenant cache bleed. */
export function tenantScope(): string {
  return getActiveTenantId() ?? "signed-out";
}

export function tenantQueryKey<const T extends readonly unknown[]>(
  parts: T
): readonly [string, ...T] {
  return [tenantScope(), ...parts];
}

const baseKeys = {
  navBadges: ["dashboard", "badges"] as const,
  notifications: ["notifications"] as const,
  dashboardOverview: (month: string, activityLimit: number) =>
    ["dashboard", "overview", month, activityLimit] as const,
  reportsAnalytics: (month: string) => ["reports", "analytics", month] as const,
  reportDocuments: (dateFrom?: string, dateTo?: string) =>
    ["reports", "documents", dateFrom ?? "all", dateTo ?? "all"] as const,
  reconciliationOverview: ["reconciliation", "overview"] as const,
  ruleBookConfig: ["rule-book", "config"] as const,
  orgAiBrief: ["tenants", "org-ai-brief"] as const,
  chartOfAccounts: ["tenants", "chart-of-accounts"] as const,
  aiProviders: ["rule-book", "ai-providers"] as const,
  ruleBookChangelog: ["rule-book", "changelog"] as const,
  recognitionSignals: ["rule-book", "recognition-signals"] as const,
  vendorMasters: ["vendor-masters"] as const,
  employeeMasters: ["employee-masters"] as const,
  pendingVendors: ["pending-vendors"] as const,
  vendorPayoutMethods: (vendorId: number) => ["vendor-payout-methods", vendorId] as const,
  routedInvoices: (routeTarget: string) => ["invoices", "routed", routeTarget] as const,
  payablesQueue: ["invoices", "payables"] as const,
  purchases: ["purchases"] as const,
  sales: ["sales"] as const,
  collections: ["collections"] as const,
  customerMasters: ["customer-masters"] as const,
  customers: ["customers"] as const,
  payments: ["payments"] as const,
  walletSummary: ["payments", "wallet-summary"] as const,
  stripeAccount: ["stripeAccount"] as const,
  stripeBalance: ["stripeBalance"] as const,
  stripeReadiness: ["stripeReadiness"] as const,
  stripeGlobalPayoutsReadiness: ["stripeGlobalPayoutsReadiness"] as const,
  stripeTransactions: (limit: number) => ["stripeTransactions", limit] as const,
  ledgerLink: ["ledger-link"] as const,
  billing: ["billing"] as const,
  appSettings: ["app-settings"] as const,
  mailboxes: ["mailboxes"] as const,
  myPermissions: ["auth", "permissions"] as const,
  institutionSettings: ["tenants", "institution-settings"] as const,
};

export const queryKeys = {
  navBadges: () => tenantQueryKey(baseKeys.navBadges),
  notifications: () => tenantQueryKey(baseKeys.notifications),
  dashboardOverview: (month: string, activityLimit: number) =>
    tenantQueryKey(baseKeys.dashboardOverview(month, activityLimit)),
  reportsAnalytics: (month: string) => tenantQueryKey(baseKeys.reportsAnalytics(month)),
  reportDocuments: (dateFrom?: string, dateTo?: string) =>
    tenantQueryKey(baseKeys.reportDocuments(dateFrom, dateTo)),
  reconciliationOverview: () => tenantQueryKey(baseKeys.reconciliationOverview),
  ruleBookConfig: () => tenantQueryKey(baseKeys.ruleBookConfig),
  orgAiBrief: () => tenantQueryKey(baseKeys.orgAiBrief),
  chartOfAccounts: () => tenantQueryKey(baseKeys.chartOfAccounts),
  aiProviders: () => tenantQueryKey(baseKeys.aiProviders),
  ruleBookChangelog: () => tenantQueryKey(baseKeys.ruleBookChangelog),
  recognitionSignals: () => tenantQueryKey(baseKeys.recognitionSignals),
  vendorMasters: () => tenantQueryKey(baseKeys.vendorMasters),
  employeeMasters: () => tenantQueryKey(baseKeys.employeeMasters),
  pendingVendors: () => tenantQueryKey(baseKeys.pendingVendors),
  vendorPayoutMethods: (vendorId: number) =>
    tenantQueryKey(baseKeys.vendorPayoutMethods(vendorId)),
  routedInvoices: (routeTarget: string) => tenantQueryKey(baseKeys.routedInvoices(routeTarget)),
  payablesQueue: () => tenantQueryKey(baseKeys.payablesQueue),
  purchases: () => tenantQueryKey(baseKeys.purchases),
  sales: () => tenantQueryKey(baseKeys.sales),
  collections: () => tenantQueryKey(baseKeys.collections),
  customerMasters: () => tenantQueryKey(baseKeys.customerMasters),
  customers: () => tenantQueryKey(baseKeys.customers),
  payments: () => tenantQueryKey(baseKeys.payments),
  walletSummary: () => tenantQueryKey(baseKeys.walletSummary),
  stripeAccount: () => tenantQueryKey(baseKeys.stripeAccount),
  stripeBalance: () => tenantQueryKey(baseKeys.stripeBalance),
  stripeReadiness: () => tenantQueryKey(baseKeys.stripeReadiness),
  stripeGlobalPayoutsReadiness: () => tenantQueryKey(baseKeys.stripeGlobalPayoutsReadiness),
  stripeTransactions: (limit: number) => tenantQueryKey(baseKeys.stripeTransactions(limit)),
  ledgerLink: () => tenantQueryKey(baseKeys.ledgerLink),
  billing: () => tenantQueryKey(baseKeys.billing),
  appSettings: () => tenantQueryKey(baseKeys.appSettings),
  mailboxes: () => tenantQueryKey(baseKeys.mailboxes),
  myPermissions: () => tenantQueryKey(baseKeys.myPermissions),
  institutionSettings: () => tenantQueryKey(baseKeys.institutionSettings),
};
