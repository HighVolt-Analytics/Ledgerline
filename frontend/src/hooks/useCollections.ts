import { api } from "@/api/client";
import { useTenantQuery } from "@/hooks/useTenantQuery";
import { queryKeys } from "@/lib/queryClient";

export function useCollections(enabled = true) {
  return useTenantQuery({
    queryKey: queryKeys.collections(),
    queryFn: () => api.listCollections(),
    enabled,
  });
}
