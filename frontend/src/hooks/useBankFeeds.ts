import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import type { BankFeedQueueTab } from "@/api/types";
import { useTenantQuery } from "@/hooks/useTenantQuery";
import { queryKeys } from "@/lib/queryClient";

export const BANK_FEEDS_PAGE_SIZE = 50;

export function useBankAccounts(enabled = true) {
  return useTenantQuery({
    queryKey: queryKeys.bankFeedAccounts(false),
    queryFn: () => api.listBankAccounts(false),
    enabled,
  });
}

export function useBankFeedImports(
  accountId: number | null,
  page = 1,
  pageSize = 20,
  enabled = true
) {
  return useTenantQuery({
    queryKey: queryKeys.bankFeedImports(accountId, page, pageSize),
    queryFn: () =>
      api.listBankFeedImports(accountId!, { page, page_size: pageSize }, { fresh: true }),
    enabled: enabled && accountId != null,
  });
}

export function useBankTransactions(
  accountId: number | null,
  matchStatus: BankFeedQueueTab,
  page = 1,
  enabled = true
) {
  const reconcile = matchStatus === "reconcile";
  return useTenantQuery({
    queryKey: queryKeys.bankFeedTransactions(accountId, matchStatus, page),
    queryFn: () =>
      api.listBankTransactions(accountId!, {
        ...(reconcile ? { reconcile: true } : { match_status: matchStatus }),
        page,
        page_size: BANK_FEEDS_PAGE_SIZE,
      }),
    enabled: enabled && accountId != null,
  });
}

export function useBankTransaction(transactionId: number | null, enabled = true) {
  return useTenantQuery({
    queryKey: queryKeys.bankFeedTransaction(transactionId),
    queryFn: () => api.getBankTransaction(transactionId!, { fresh: true }),
    enabled: enabled && transactionId != null,
  });
}

export function useBankTransactionAudit(transactionId: number | null, enabled = true) {
  return useTenantQuery({
    queryKey: queryKeys.bankFeedTxnAudit(transactionId),
    queryFn: () => api.listBankTransactionAudit(transactionId!, { fresh: true }),
    enabled: enabled && transactionId != null,
  });
}

export function useBankTransactionNotes(transactionId: number | null, enabled = true) {
  return useTenantQuery({
    queryKey: queryKeys.bankFeedTxnNotes(transactionId),
    queryFn: () => api.listBankTransactionNotes(transactionId!, { fresh: true }),
    enabled: enabled && transactionId != null,
  });
}

export function useBankMatchTargets(
  matchedType: "payment" | "collection",
  bankAccountId: number | null,
  enabled = true
) {
  return useTenantQuery({
    queryKey: queryKeys.bankFeedMatchTargets(matchedType, bankAccountId),
    queryFn: () =>
      api.listBankMatchTargets(matchedType, {
        limit: 100,
        fresh: true,
        bank_account_id: bankAccountId ?? undefined,
      }),
    enabled: enabled && bankAccountId != null,
  });
}

export function useUnsettledSettlements(page = 1, pageSize = BANK_FEEDS_PAGE_SIZE, enabled = true) {
  return useTenantQuery({
    queryKey: queryKeys.bankFeedUnsettled(page, pageSize),
    queryFn: () =>
      api.listUnsettledSettlements({ page, page_size: pageSize }, { fresh: true }),
    enabled,
  });
}

function useInvalidateBankFeeds() {
  const queryClient = useQueryClient();
  return async () => {
    await queryClient.invalidateQueries({
      queryKey: queryKeys.bankFeedAccounts().slice(0, 2),
    });
  };
}

export function useBankFeedMutations() {
  const invalidate = useInvalidateBankFeeds();

  const createAccount = useMutation({
    mutationFn: (body: {
      name: string;
      currency: string;
      account_mask?: string | null;
      coa_account_name?: string | null;
    }) => api.createBankAccount(body),
    onSuccess: () => invalidate(),
  });

  const importStatement = useMutation({
    mutationFn: ({ accountId, file }: { accountId: number; file: File }) =>
      api.importBankFeedStatement(accountId, file),
    onSuccess: () => invalidate(),
  });

  const importCsv = importStatement;

  const runMatch = useMutation({
    mutationFn: (accountId: number) => api.runBankFeedMatch(accountId),
    onSuccess: () => invalidate(),
  });

  const runCategorize = useMutation({
    mutationFn: (accountId: number) => api.runBankFeedCategorize(accountId),
    onSuccess: () => invalidate(),
  });

  const setCategory = useMutation({
    mutationFn: ({
      transactionId,
      category_coa,
      ledger,
      sub_ledger,
    }: {
      transactionId: number;
      category_coa?: string | null;
      ledger?: string | null;
      sub_ledger?: string | null;
    }) =>
      api.setBankTransactionCategory(transactionId, {
        category_coa,
        ledger,
        sub_ledger,
      }),
    onSuccess: () => invalidate(),
  });

  const confirmMatch = useMutation({
    mutationFn: (matchId: number) => api.confirmBankMatch(matchId),
    onSuccess: () => invalidate(),
  });

  const unmatch = useMutation({
    mutationFn: ({ matchId, reason }: { matchId: number; reason?: string | null }) =>
      api.unmatchBankMatch(matchId, reason),
    onSuccess: () => invalidate(),
  });

  const exclude = useMutation({
    mutationFn: ({
      transactionId,
      reason,
    }: {
      transactionId: number;
      reason?: string | null;
    }) => api.excludeBankTransaction(transactionId, reason),
    onSuccess: () => invalidate(),
  });

  const createMatch = useMutation({
    mutationFn: ({
      transactionId,
      matched_type,
      matched_id,
      allocated_amount,
    }: {
      transactionId: number;
      matched_type: "payment" | "collection";
      matched_id: number;
      allocated_amount?: number | null;
    }) =>
      api.createBankTransactionMatch(transactionId, {
        matched_type,
        matched_id,
        allocated_amount,
      }),
    onSuccess: () => invalidate(),
  });

  const createJournal = useMutation({
    mutationFn: ({
      transactionId,
      body,
    }: {
      transactionId: number;
      body: {
        party_type: "vendor" | "customer";
        party_id?: number | null;
        create_party?: { name: string } | null;
        ledger: string;
        description: string;
        tax_rate_percent: number;
      };
    }) => api.createBankJournal(transactionId, body),
    onSuccess: () => invalidate(),
  });

  const transfer = useMutation({
    mutationFn: ({
      transactionId,
      to_bank_account_id,
      description,
    }: {
      transactionId: number;
      to_bank_account_id: number;
      description: string;
    }) => api.transferBankTransaction(transactionId, { to_bank_account_id, description }),
    onSuccess: () => invalidate(),
  });

  const createNote = useMutation({
    mutationFn: ({
      transactionId,
      body,
    }: {
      transactionId: number;
      body: string;
    }) => api.createBankTransactionNote(transactionId, { body }),
    onSuccess: () => invalidate(),
  });

  const reverseCreate = useMutation({
    mutationFn: (transactionId: number) => api.reverseBankCreate(transactionId),
    onSuccess: () => invalidate(),
  });

  return {
    createAccount,
    importStatement,
    importCsv,
    runMatch,
    runCategorize,
    setCategory,
    confirmMatch,
    unmatch,
    exclude,
    createMatch,
    createJournal,
    transfer,
    createNote,
    reverseCreate,
  };
}
