import { api } from "@/api/client";
import { useTenantQuery } from "@/hooks/useTenantQuery";
import { queryKeys } from "@/lib/queryClient";
import type { CollectionTab } from "@/lib/v4MockData";

export const COLLECTIONS_PAGE_SIZE = 50;

export function useCollections(status: CollectionTab, enabled = true) {
  return useTenantQuery({
    queryKey: queryKeys.collections(status),
    queryFn: () => api.listCollections({ status, limit: COLLECTIONS_PAGE_SIZE }),
    enabled,
  });
}

export function useCollectionWorkspaceKpis(enabled = true) {
  return useTenantQuery({
    queryKey: queryKeys.collectionsWorkspaceKpis(),
    queryFn: () => api.getCollectionWorkspaceKpis(),
    enabled,
  });
}
