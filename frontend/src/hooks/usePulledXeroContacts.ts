import { useMutation, useQueryClient } from "@tanstack/react-query";

import { api } from "@/api/client";
import { useTenantQuery } from "@/hooks/useTenantQuery";
import { queryKeys } from "@/lib/queryClient";

const LIST_LIMIT = 200;

export function usePulledXeroContacts(enabled = true) {
  const statusQuery = useTenantQuery({
    queryKey: queryKeys.accountingIntegrationsStatus(),
    queryFn: () => api.getAccountingIntegrationsStatus({ fresh: true }),
    enabled,
    staleTime: 30_000,
  });
  const xeroConnected = statusQuery.data?.xero.status === "connected";
  const listQuery = useTenantQuery({
    queryKey: queryKeys.xeroPulledContacts(),
    queryFn: () => api.getXeroContactsList({ limit: LIST_LIMIT, offset: 0 }),
    enabled: enabled && xeroConnected && !statusQuery.blocked,
    staleTime: 30_000,
  });

  return {
    xeroConnected,
    loading: Boolean(statusQuery.isLoading && statusQuery.data === undefined),
    status: statusQuery.data ?? null,
    contacts: listQuery.data?.items ?? [],
    contactsTotal: listQuery.data?.total ?? 0,
    contactsLoading: Boolean(listQuery.isLoading && listQuery.data === undefined),
    contactsError: statusQuery.isError || listQuery.isError,
    refetchContacts: listQuery.refetch,
  };
}

export function useSyncPulledXeroContacts() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => api.syncXeroContacts(),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: queryKeys.xeroPulledContacts() });
    },
  });
}

export function useCreatePulledXeroContact() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (legalName: string) => api.createXeroContact({ legal_name: legalName }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: queryKeys.xeroPulledContacts() });
    },
  });
}
