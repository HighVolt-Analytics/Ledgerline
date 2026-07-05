import { useTenantQuery } from "@/hooks/useTenantQuery";
import { api } from "@/api/client";
import { queryKeys } from "@/lib/queryClient";

export function useCollections(enabled = true) {
  return useTenantQuery({
    queryKey: queryKeys.collections(),
    queryFn: () => api.listCollections(),
    enabled,
  });
}
