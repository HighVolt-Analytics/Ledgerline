import { useMutation, useQueryClient } from "@tanstack/react-query";

import { api } from "@/api/client";
import type {
  ChartOfAccountRow,
  ChartOfAccountsPayload,
  PlatformChartOfAccountRow,
  SubLedgerRow,
} from "@/api/types";
import { useTenantQuery } from "@/hooks/useTenantQuery";
import { newClientRowKey } from "@/lib/clientRowKey";
import { queryKeys } from "@/lib/queryClient";

function normalizeAccount(row: ChartOfAccountRow): ChartOfAccountRow {
  const raw = row as ChartOfAccountRow & {
    sub_ledgers?: SubLedgerRow[];
    linked_providers?: string[];
    sub_type?: string | null;
  };
  return {
    ...row,
    type: normalizeChartOfAccountType(row.type),
    sub_type: raw.sub_type ?? row.sub_type ?? null,
    linked_providers: raw.linked_providers ?? row.linked_providers ?? [],
    subLedgers: normalizeSubLedgers(raw.subLedgers ?? raw.sub_ledgers),
  };
}

function normalizePlatform(row: PlatformChartOfAccountRow): PlatformChartOfAccountRow {
  const raw = row as PlatformChartOfAccountRow & { sub_ledgers?: SubLedgerRow[] };
  return {
    ...row,
    type: normalizeChartOfAccountType(row.type),
    subLedgers: normalizeSubLedgers(raw.subLedgers ?? raw.sub_ledgers),
    linked_providers: row.linked_providers ?? [],
  };
}

export function normalizeChartOfAccountsPayload(res: ChartOfAccountsPayload): ChartOfAccountsPayload {
  const accounts = (res.accounts ?? []).map(normalizeAccount);
  return {
    ...res,
    accounts,
    local_accounts: (res.local_accounts ?? accounts).map(normalizeAccount),
    platform_accounts: (res.platform_accounts ?? []).map(normalizePlatform),
    xero_connected: Boolean(res.xero_connected),
    source: res.source ?? (res.xero_connected ? "xero" : "none"),
  };
}

async function applyCoaCaches(
  queryClient: ReturnType<typeof useQueryClient>,
  payload: ChartOfAccountsPayload
) {
  const normalized = normalizeChartOfAccountsPayload(payload);
  queryClient.setQueryData(queryKeys.chartOfAccountsWorkspace(), normalized);
  queryClient.setQueryData(queryKeys.chartOfAccounts(), normalized.accounts);
  void queryClient.invalidateQueries({ queryKey: queryKeys.ruleBookConfig() });
}

export function useChartOfAccounts(enabled = true) {
  return useTenantQuery({
    queryKey: queryKeys.chartOfAccounts(),
    queryFn: async () => {
      const res = await api.getChartOfAccounts();
      return normalizeChartOfAccountsPayload(res).accounts;
    },
    enabled,
    staleTime: 0,
    refetchOnMount: "always",
  });
}

export function useChartOfAccountsWorkspace(enabled = true) {
  return useTenantQuery({
    queryKey: queryKeys.chartOfAccountsWorkspace(),
    queryFn: async () => normalizeChartOfAccountsPayload(await api.getChartOfAccounts()),
    enabled,
    staleTime: 0,
    refetchOnMount: "always",
  });
}

export function useSaveChartOfAccounts() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (accounts: ChartOfAccountRow[]) =>
      normalizeChartOfAccountsPayload(await api.updateChartOfAccounts({ accounts })),
    onSuccess: async (payload) => {
      await applyCoaCaches(queryClient, payload);
    },
  });
}

export function useSyncChartOfAccounts() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => api.syncChartOfAccounts(),
    onSuccess: async (payload) => {
      await applyCoaCaches(queryClient, payload);
    },
  });
}

export function useCreateXeroChartOfAccount() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (
      body: Parameters<typeof api.createXeroChartOfAccount>[0]
    ) => api.createXeroChartOfAccount(body),
    onSuccess: async (payload) => {
      await applyCoaCaches(queryClient, payload);
    },
  });
}

export function useUpdateXeroChartOfAccount() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      accountId,
      body,
    }: {
      accountId: string;
      body: Parameters<typeof api.updateXeroChartOfAccount>[1];
    }) => api.updateXeroChartOfAccount(accountId, body),
    onSuccess: async (payload) => {
      await applyCoaCaches(queryClient, payload);
    },
  });
}

export function useDeleteXeroChartOfAccount() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (accountId: string) => api.deleteXeroChartOfAccount(accountId),
    onSuccess: async (payload) => {
      await applyCoaCaches(queryClient, payload);
    },
  });
}

export function usePullXeroChartOfAccount() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (accountId: string) => api.pullXeroChartOfAccount(accountId),
    onSuccess: async (payload) => {
      await applyCoaCaches(queryClient, payload);
    },
  });
}

export function useCreateQboChartOfAccount() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: Parameters<typeof api.createQboChartOfAccount>[0]) =>
      api.createQboChartOfAccount(body),
    onSuccess: async (payload) => {
      await applyCoaCaches(queryClient, payload);
    },
  });
}

export function useUpdateQboChartOfAccount() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      accountId,
      body,
    }: {
      accountId: string;
      body: Parameters<typeof api.updateQboChartOfAccount>[1];
    }) => api.updateQboChartOfAccount(accountId, body),
    onSuccess: async (payload) => {
      await applyCoaCaches(queryClient, payload);
    },
  });
}

export function useDeleteQboChartOfAccount() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (accountId: string) => api.deleteQboChartOfAccount(accountId),
    onSuccess: async (payload) => {
      await applyCoaCaches(queryClient, payload);
    },
  });
}

export function usePullQboChartOfAccount() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (accountId: string) => api.pullQboChartOfAccount(accountId),
    onSuccess: async (payload) => {
      await applyCoaCaches(queryClient, payload);
    },
  });
}

export type ChartOfAccountRowLocal = ChartOfAccountRow & { _rowKey: string };

export function newChartOfAccountRow(): ChartOfAccountRowLocal {
  return {
    code: "",
    name: "",
    type: "Expense",
    subLedgers: [],
    _rowKey: newClientRowKey("coa"),
  };
}

function normalizeSubLedgers(
  value: SubLedgerRow[] | { code: string; name: string; origin?: string }[] | undefined
): SubLedgerRow[] {
  if (!value?.length) return [];
  return value.map((row) => {
    const origin = (row as SubLedgerRow).origin;
    return {
      code: (row.code ?? "").trim(),
      name: (row.name ?? "").trim(),
      ...(origin === "party" || origin === "manual" ? { origin } : {}),
    };
  });
}

export function chartOfAccountRowToPayload(row: ChartOfAccountRow): ChartOfAccountRow & {
  sub_ledgers?: SubLedgerRow[];
} {
  const subLedgers = (row.subLedgers ?? [])
    .map((sub) => ({
      code: sub.code.trim(),
      name: sub.name.trim(),
      ...(sub.origin ? { origin: sub.origin } : {}),
    }))
    .filter((sub) => sub.code && sub.name);
  return {
    code: row.code.trim(),
    name: row.name.trim(),
    type: row.type,
    sub_type: row.sub_type ?? null,
    linked_providers: row.linked_providers ?? [],
    subLedgers,
    sub_ledgers: subLedgers,
  };
}

export const CHART_OF_ACCOUNT_TYPES = [
  "Expense",
  "Asset",
  "Liability",
  "Revenue",
  "Equity",
] as const;

export type ChartOfAccountTypeOption = (typeof CHART_OF_ACCOUNT_TYPES)[number];

export function normalizeChartOfAccountType(value: string | undefined): ChartOfAccountTypeOption {
  const cleaned = (value ?? "").trim();
  return CHART_OF_ACCOUNT_TYPES.includes(cleaned as ChartOfAccountTypeOption)
    ? (cleaned as ChartOfAccountTypeOption)
    : "Expense";
}

export function inferChartOfAccountTypeFromName(name: string): ChartOfAccountTypeOption {
  const lower = name.trim().toLowerCase();
  if (!lower) return "Expense";
  if (/\b(receivable|debtor|debtors|trade)\b/.test(lower)) return "Asset";
  if (/\b(payable|suspense|gst collected|tax collected|output tax)\b/.test(lower)) return "Liability";
  if (/\b(gst paid|bank|advance|float)\b/.test(lower)) return "Asset";
  if (/\b(sales|revenue|income|turnover)\b/.test(lower)) return "Revenue";
  if (/\b(equity|retained)\b/.test(lower)) return "Equity";
  return "Expense";
}

export function coaTypeMisclassificationWarnings(accounts: ChartOfAccountRow[]): string[] {
  const warnings: string[] = [];
  for (const row of accounts) {
    const name = row.name.trim();
    if (!name) continue;
    if (/\b(sales|revenue|income|turnover)\b/i.test(name) && row.type !== "Revenue") {
      warnings.push(`"${name}" looks like revenue but is typed ${row.type}.`);
    }
    if (/\b(receivable|debtor|debtors)\b/i.test(name) && row.type !== "Asset") {
      warnings.push(`"${name}" looks like a receivable but is typed ${row.type}.`);
    }
  }
  return warnings;
}
