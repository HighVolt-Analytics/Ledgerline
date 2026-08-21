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
  subledgerApBalances: (asOf?: string) => ["reports", "subledger", "ap", asOf ?? ""] as const,
  subledgerArBalances: (asOf?: string) => ["reports", "subledger", "ar", asOf ?? ""] as const,
  reportDocuments: (dateFrom?: string, dateTo?: string) =>
    ["reports", "documents", dateFrom ?? "all", dateTo ?? "all"] as const,
  teAdvanceSettlement: ["reports", "team-expenses", "advance-settlement"] as const,
  teBudgetUtilization: ["reports", "team-expenses", "budget-utilization"] as const,
  teDepartmentBudgetUtilization: [
    "reports",
    "team-expenses",
    "department-budget-utilization",
  ] as const,
  teWorkspaceKpis: ["reports", "team-expenses", "workspace-kpis"] as const,
  expensesWorkspaceKpis: ["reports", "expenses", "workspace-kpis"] as const,
  purchasesWorkspaceKpis: ["purchases", "workspace-kpis"] as const,
  salesWorkspaceKpis: ["sales", "workspace-kpis"] as const,
  teExpenseSummary: (dateFrom?: string, dateTo?: string) =>
    ["reports", "team-expenses", "expense-summary", dateFrom ?? "all", dateTo ?? "all"] as const,
  departmentBudgets: ["department-budgets"] as const,
  reconciliationOverview: ["reconciliation", "overview"] as const,
  reconciliationDaily: ["reconciliation", "daily"] as const,
  reconciliationDayDetail: (date: string) => ["reconciliation", "daily", date, "detail"] as const,
  ruleBookConfig: ["rule-book", "config"] as const,
  orgAiBrief: ["tenants", "org-ai-brief"] as const,
  chartOfAccounts: ["tenants", "chart-of-accounts"] as const,
  aiProviders: ["rule-book", "ai-providers"] as const,
  ruleBookChangelog: ["rule-book", "changelog"] as const,
  recognitionSignals: ["rule-book", "recognition-signals"] as const,
  vendorMasters: ["vendor-masters"] as const,
  employeeMasters: ["employee-masters"] as const,
  pendingVendors: ["pending-vendors"] as const,
  pendingCustomers: ["pending-customers"] as const,
  vendorPayoutMethods: (vendorId: number) => ["vendor-payout-methods", vendorId] as const,
  routedInvoices: (routeTarget: string) => ["invoices", "routed", routeTarget] as const,
  payablesQueue: ["invoices", "payables"] as const,
  uploadDocuments: (
    page: number,
    pageSize: number,
    source: string,
    q: string,
    mailboxId: number | null,
    captureSource: string
  ) =>
    ["invoices", "upload", page, pageSize, source, q, mailboxId ?? "all", captureSource] as const,
  purchases: ["purchases"] as const,
  purchasesTwoWay: ["purchases", "two-way"] as const,
  sales: ["sales"] as const,
  salesTwoWay: ["sales", "two-way"] as const,
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
  paypalReadiness: ["paypalReadiness"] as const,
  paypalBalance: ["paypalBalance"] as const,
  paypalTransactions: (limit: number) => ["paypalTransactions", limit] as const,
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
  subledgerApBalances: (asOf?: string) => tenantQueryKey(baseKeys.subledgerApBalances(asOf)),
  subledgerArBalances: (asOf?: string) => tenantQueryKey(baseKeys.subledgerArBalances(asOf)),
  reportDocuments: (dateFrom?: string, dateTo?: string) =>
    tenantQueryKey(baseKeys.reportDocuments(dateFrom, dateTo)),
  teAdvanceSettlement: () => tenantQueryKey(baseKeys.teAdvanceSettlement),
  teBudgetUtilization: () => tenantQueryKey(baseKeys.teBudgetUtilization),
  teDepartmentBudgetUtilization: () =>
    tenantQueryKey(baseKeys.teDepartmentBudgetUtilization),
  teWorkspaceKpis: () => tenantQueryKey(baseKeys.teWorkspaceKpis),
  expensesWorkspaceKpis: () => tenantQueryKey(baseKeys.expensesWorkspaceKpis),
  purchasesWorkspaceKpis: () => tenantQueryKey(baseKeys.purchasesWorkspaceKpis),
  salesWorkspaceKpis: () => tenantQueryKey(baseKeys.salesWorkspaceKpis),
  teExpenseSummary: (dateFrom?: string, dateTo?: string) =>
    tenantQueryKey(baseKeys.teExpenseSummary(dateFrom, dateTo)),
  departmentBudgets: () => tenantQueryKey(baseKeys.departmentBudgets),
  reconciliationOverview: () => tenantQueryKey(baseKeys.reconciliationOverview),
  reconciliationDaily: () => tenantQueryKey(baseKeys.reconciliationDaily),
  reconciliationDayDetail: (date: string) =>
    tenantQueryKey(baseKeys.reconciliationDayDetail(date)),
  ruleBookConfig: () => tenantQueryKey(baseKeys.ruleBookConfig),
  orgAiBrief: () => tenantQueryKey(baseKeys.orgAiBrief),
  chartOfAccounts: () => tenantQueryKey(baseKeys.chartOfAccounts),
  aiProviders: () => tenantQueryKey(baseKeys.aiProviders),
  ruleBookChangelog: () => tenantQueryKey(baseKeys.ruleBookChangelog),
  recognitionSignals: () => tenantQueryKey(baseKeys.recognitionSignals),
  vendorMasters: () => tenantQueryKey(baseKeys.vendorMasters),
  employeeMasters: () => tenantQueryKey(baseKeys.employeeMasters),
  pendingVendors: () => tenantQueryKey(baseKeys.pendingVendors),
  pendingCustomers: () => tenantQueryKey(baseKeys.pendingCustomers),
  vendorPayoutMethods: (vendorId: number) =>
    tenantQueryKey(baseKeys.vendorPayoutMethods(vendorId)),
  routedInvoices: (routeTarget: string) => tenantQueryKey(baseKeys.routedInvoices(routeTarget)),
  payablesQueue: () => tenantQueryKey(baseKeys.payablesQueue),
  uploadDocuments: (
    page: number,
    pageSize: number,
    source: string,
    q: string,
    mailboxId: number | null,
    captureSource: string
  ) =>
    tenantQueryKey(
      baseKeys.uploadDocuments(page, pageSize, source, q, mailboxId, captureSource)
    ),
  purchases: () => tenantQueryKey(baseKeys.purchases),
  purchasesTwoWay: () => tenantQueryKey(baseKeys.purchasesTwoWay),
  sales: () => tenantQueryKey(baseKeys.sales),
  salesTwoWay: () => tenantQueryKey(baseKeys.salesTwoWay),
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
  paypalReadiness: () => tenantQueryKey(baseKeys.paypalReadiness),
  paypalBalance: () => tenantQueryKey(baseKeys.paypalBalance),
  paypalTransactions: (limit: number) => tenantQueryKey(baseKeys.paypalTransactions(limit)),
  ledgerLink: () => tenantQueryKey(baseKeys.ledgerLink),
  billing: () => tenantQueryKey(baseKeys.billing),
  appSettings: () => tenantQueryKey(baseKeys.appSettings),
  mailboxes: () => tenantQueryKey(baseKeys.mailboxes),
  myPermissions: () => tenantQueryKey(baseKeys.myPermissions),
  institutionSettings: () => tenantQueryKey(baseKeys.institutionSettings),
};
