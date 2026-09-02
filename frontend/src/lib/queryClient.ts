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
  positionLiquidity: (period: string) => ["dashboard", "position-liquidity", period] as const,
  efficiencyAutomation: (period: string) => ["dashboard", "efficiency-automation", period] as const,
  cashLiabilityOutlook: (period: string) => ["dashboard", "cash-liability-outlook", period] as const,
  budgetConcentrationRisk: (period: string) => ["dashboard", "budget-concentration-risk", period] as const,
  cfoAlerts: (period: string) => ["dashboard", "cfo-alerts", period] as const,
  processEfficiencyTrends: (period: string) =>
    ["dashboard", "process-efficiency-trends", period] as const,
  reportsAnalytics: (month: string) => ["reports", "analytics", month] as const,
  subledgerApBalances: (asOf?: string) => ["reports", "subledger", "ap", asOf ?? ""] as const,
  subledgerArBalances: (asOf?: string) => ["reports", "subledger", "ar", asOf ?? ""] as const,
  reportDocuments: (dateFrom?: string, dateTo?: string) =>
    ["reports", "documents", dateFrom ?? "all", dateTo ?? "all"] as const,
  reportCatalog: ["reports", "catalog"] as const,
  reportPreview: (
    reportId: string,
    range: string,
    compare: boolean,
    dateFrom: string,
    dateTo: string
  ) => ["reports", "preview", reportId, range, compare, dateFrom, dateTo] as const,
  reportLayouts: (reportId: string) => ["reports", "layouts", reportId] as const,
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
  chartOfAccountsWorkspace: ["tenants", "chart-of-accounts", "workspace"] as const,
  taxRates: ["tenants", "tax-rates"] as const,
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
  collectionsWorkspaceKpis: ["collections", "workspace-kpis"] as const,
  customerMasters: ["customer-masters"] as const,
  customers: ["customers"] as const,
  vendors: ["vendors"] as const,
  payments: ["payments"] as const,
  paymentsWorkspaceKpis: ["payments", "workspace-kpis"] as const,
  bankFeedAccounts: ["bank-feeds", "accounts"] as const,
  bankFeedTransactions: ["bank-feeds", "transactions"] as const,
  bankFeedTransaction: ["bank-feeds", "transaction"] as const,
  bankFeedTxnAudit: ["bank-feeds", "txn-audit"] as const,
  bankFeedMatchTargets: ["bank-feeds", "match-targets"] as const,
  bankFeedImports: ["bank-feeds", "imports"] as const,
  bankFeedTxnNotes: ["bank-feeds", "txn-notes"] as const,
  bankFeedUnsettled: ["bank-feeds", "unsettled"] as const,
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
  ledgerLinkOverview: ["ledger-link", "overview"] as const,
  ledgerLinkExports: ["ledger-link", "exports"] as const,
  ledgerLinkDay: (day: string) => ["ledger-link", "days", day] as const,
  vaultTree: ["vault", "tree"] as const,
  vaultFiles: ["vault", "files"] as const,
  vaultDocumentSets: ["vault", "document-sets"] as const,
  billing: ["billing"] as const,
  appSettings: ["app-settings"] as const,
  mailboxes: ["mailboxes"] as const,
  emailIngestionRules: ["mailboxes", "ingestion-rules"] as const,
  myPermissions: ["auth", "permissions"] as const,
  institutionSettings: ["tenants", "institution-settings"] as const,
};

export const queryKeys = {
  navBadges: () => tenantQueryKey(baseKeys.navBadges),
  notifications: () => tenantQueryKey(baseKeys.notifications),
  dashboardOverview: (month: string, activityLimit: number) =>
    tenantQueryKey(baseKeys.dashboardOverview(month, activityLimit)),
  positionLiquidity: (period: string) => tenantQueryKey(baseKeys.positionLiquidity(period)),
  positionLiquidityAll: () => tenantQueryKey(["dashboard", "position-liquidity"] as const),
  efficiencyAutomation: (period: string) => tenantQueryKey(baseKeys.efficiencyAutomation(period)),
  cashLiabilityOutlook: (period: string) => tenantQueryKey(baseKeys.cashLiabilityOutlook(period)),
  budgetConcentrationRisk: (period: string) => tenantQueryKey(baseKeys.budgetConcentrationRisk(period)),
  cfoAlerts: (period: string) => tenantQueryKey(baseKeys.cfoAlerts(period)),
  processEfficiencyTrends: (period: string) =>
    tenantQueryKey(baseKeys.processEfficiencyTrends(period)),
  reportsAnalytics: (month: string) => tenantQueryKey(baseKeys.reportsAnalytics(month)),
  subledgerApBalances: (asOf?: string) => tenantQueryKey(baseKeys.subledgerApBalances(asOf)),
  subledgerArBalances: (asOf?: string) => tenantQueryKey(baseKeys.subledgerArBalances(asOf)),
  reportDocuments: (dateFrom?: string, dateTo?: string) =>
    tenantQueryKey(baseKeys.reportDocuments(dateFrom, dateTo)),
  reportCatalog: () => tenantQueryKey(baseKeys.reportCatalog),
  reportPreview: (
    reportId: string,
    range: string,
    compare: boolean,
    dateFrom?: string,
    dateTo?: string
  ) =>
    tenantQueryKey(
      baseKeys.reportPreview(reportId, range, compare, dateFrom ?? "", dateTo ?? "")
    ),
  reportLayouts: (reportId: string) => tenantQueryKey(baseKeys.reportLayouts(reportId)),
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
  chartOfAccountsWorkspace: () => tenantQueryKey(baseKeys.chartOfAccountsWorkspace),
  taxRates: () => tenantQueryKey(baseKeys.taxRates),
  aiProviders: () => tenantQueryKey(baseKeys.aiProviders),
  ruleBookChangelog: () => tenantQueryKey(baseKeys.ruleBookChangelog),
  recognitionSignals: () => tenantQueryKey(baseKeys.recognitionSignals),
  vendorMasters: (revealBank?: boolean) =>
    revealBank === undefined
      ? tenantQueryKey(baseKeys.vendorMasters)
      : tenantQueryKey([...baseKeys.vendorMasters, revealBank]),
  employeeMasters: (revealBank?: boolean) =>
    revealBank === undefined
      ? tenantQueryKey(baseKeys.employeeMasters)
      : tenantQueryKey([...baseKeys.employeeMasters, revealBank]),
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
  collections: (status?: string) =>
    status
      ? tenantQueryKey([...baseKeys.collections, status] as const)
      : tenantQueryKey(baseKeys.collections),
  collectionsWorkspaceKpis: () => tenantQueryKey(baseKeys.collectionsWorkspaceKpis),
  customerMasters: () => tenantQueryKey(baseKeys.customerMasters),
  customers: () => tenantQueryKey(baseKeys.customers),
  vendors: () => tenantQueryKey(baseKeys.vendors),
  payments: (status?: string) =>
    status
      ? tenantQueryKey([...baseKeys.payments, status] as const)
      : tenantQueryKey(baseKeys.payments),
  paymentsWorkspaceKpis: () => tenantQueryKey(baseKeys.paymentsWorkspaceKpis),
  bankFeedAccounts: (includeArchived = false) =>
    tenantQueryKey([...baseKeys.bankFeedAccounts, includeArchived] as const),
  bankFeedTransactions: (
    accountId: number | null,
    matchStatus: string,
    page: number
  ) =>
    tenantQueryKey([
      ...baseKeys.bankFeedTransactions,
      accountId ?? "none",
      matchStatus,
      page,
    ] as const),
  bankFeedTransaction: (transactionId: number | null) =>
    tenantQueryKey([
      ...baseKeys.bankFeedTransaction,
      transactionId ?? "none",
    ] as const),
  bankFeedTxnAudit: (transactionId: number | null) =>
    tenantQueryKey([
      ...baseKeys.bankFeedTxnAudit,
      transactionId ?? "none",
    ] as const),
  bankFeedMatchTargets: (matchedType: "payment" | "collection", bankAccountId?: number | null) =>
    tenantQueryKey(
      [...baseKeys.bankFeedMatchTargets, matchedType, bankAccountId ?? "none"] as const
    ),
  bankFeedImports: (accountId: number | null, page: number, pageSize = 20) =>
    tenantQueryKey(
      [...baseKeys.bankFeedImports, accountId ?? "none", page, pageSize] as const
    ),
  bankFeedTxnNotes: (transactionId: number | null) =>
    tenantQueryKey([...baseKeys.bankFeedTxnNotes, transactionId ?? "none"] as const),
  bankFeedUnsettled: (page: number, pageSize = 50) =>
    tenantQueryKey([...baseKeys.bankFeedUnsettled, page, pageSize] as const),
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
  ledgerLinkOverview: () => tenantQueryKey(baseKeys.ledgerLinkOverview),
  ledgerLinkExports: () => tenantQueryKey(baseKeys.ledgerLinkExports),
  ledgerLinkDay: (day: string) => tenantQueryKey(baseKeys.ledgerLinkDay(day)),
  vaultTree: () => tenantQueryKey(baseKeys.vaultTree),
  vaultFiles: (selectionKey: string) =>
    tenantQueryKey([...baseKeys.vaultFiles, selectionKey] as const),
  vaultDocumentSets: () => tenantQueryKey(baseKeys.vaultDocumentSets),
  billing: () => tenantQueryKey(baseKeys.billing),
  appSettings: () => tenantQueryKey(baseKeys.appSettings),
  mailboxes: () => tenantQueryKey(baseKeys.mailboxes),
  emailIngestionRules: () => tenantQueryKey(baseKeys.emailIngestionRules),
  emailIngestionStats: () => tenantQueryKey([...baseKeys.emailIngestionRules, "stats"] as const),
  myPermissions: () => tenantQueryKey(baseKeys.myPermissions),
  institutionSettings: () => tenantQueryKey(baseKeys.institutionSettings),
};
