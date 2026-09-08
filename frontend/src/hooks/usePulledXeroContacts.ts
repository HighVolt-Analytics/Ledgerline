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
  const qboConnected = statusQuery.data?.quickbooks_online.status === "connected";
  const connectedProvider = qboConnected ? "quickbooks" : xeroConnected ? "xero" : null;
  const listQuery = useTenantQuery({
    queryKey: connectedProvider === "quickbooks" ? queryKeys.qboPulledContacts() : queryKeys.xeroPulledContacts(),
    queryFn: () =>
      connectedProvider === "quickbooks"
        ? api.getQboContactsList({ limit: LIST_LIMIT, offset: 0 })
        : api.getXeroContactsList({ limit: LIST_LIMIT, offset: 0 }),
    enabled: enabled && Boolean(connectedProvider) && !statusQuery.blocked,
    staleTime: 30_000,
  });

  return {
    xeroConnected,
    qboConnected,
    connectedProvider,
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
    mutationFn: async () => {
      const status = await api.getAccountingIntegrationsStatus({ fresh: true });
      if (status.quickbooks_online.status === "connected") {
        return api.syncQboContacts();
      }
      return api.syncXeroContacts();
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: queryKeys.xeroPulledContacts() });
      await queryClient.invalidateQueries({ queryKey: queryKeys.qboPulledContacts() });
    },
  });
}

export function useCreatePulledXeroContact() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (draft: {
      legal_name: string;
      entity_type?: "vendor" | "customer";
      given_name?: string;
      family_name?: string;
      company_name?: string;
      email?: string;
      phone?: string;
      tax_identifier?: string;
    }) => {
      const status = await api.getAccountingIntegrationsStatus({ fresh: true });
      if (status.quickbooks_online.status === "connected") {
        return api.createQboContact({
          legal_name: draft.legal_name,
          entity_type: draft.entity_type ?? "vendor",
          given_name: draft.given_name,
          family_name: draft.family_name,
          company_name: draft.company_name,
          email: draft.email,
          phone: draft.phone,
          tax_identifier: draft.tax_identifier,
        });
      }
      return api.createXeroContact({ legal_name: draft.legal_name });
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: queryKeys.xeroPulledContacts() });
      await queryClient.invalidateQueries({ queryKey: queryKeys.qboPulledContacts() });
    },
  });
}
