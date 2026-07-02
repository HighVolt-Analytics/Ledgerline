import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import { queryKeys } from "@/lib/queryClient";

export function useCollections(enabled = true) {
  return useQuery({
    queryKey: queryKeys.collections(),
    queryFn: () => api.listCollections(),
    enabled,
  });
}
