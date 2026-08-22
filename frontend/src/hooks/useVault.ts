import { api } from "@/api/client";
import { useTenantQuery } from "@/hooks/useTenantQuery";
import { queryKeys } from "@/lib/queryClient";
import {
  vaultSelectionQueryKey,
  type VaultSelection,
} from "@/lib/vault";

export const VAULT_PAGE_FILE_LIMIT = 50;
export const VAULT_POLL_MS = 90_000;

export function useVaultTree() {
  return useTenantQuery({
    queryKey: queryKeys.vaultTree(),
    queryFn: () => api.getVaultTree({ fileLimit: VAULT_PAGE_FILE_LIMIT }),
  });
}

export function useVaultFiles(selection: VaultSelection | null, enabled = true) {
  return useTenantQuery({
    queryKey: queryKeys.vaultFiles(vaultSelectionQueryKey(selection)),
    queryFn: () =>
      api.getVaultFiles({
        org: selection?.org,
        book: selection?.book,
        documentType: selection?.documentType,
        vendor: selection?.vendor,
        year: selection?.year,
        month: selection?.month,
        poFolder: selection?.poFolder,
        limit: VAULT_PAGE_FILE_LIMIT,
      }),
    enabled: enabled && Boolean(selection?.org),
  });
}

export function useVaultDocumentSets(enabled = true) {
  return useTenantQuery({
    queryKey: queryKeys.vaultDocumentSets(),
    queryFn: () => api.getVaultDocumentSets(),
    enabled,
  });
}

export function useVaultFileByInvoice(invoiceId: number | null, enabled = true) {
  return useTenantQuery({
    queryKey: queryKeys.vaultFiles(`invoice:${invoiceId ?? 0}`),
    queryFn: () => api.getVaultFiles({ invoiceId: invoiceId as number }),
    enabled: enabled && invoiceId != null && invoiceId > 0,
  });
}
