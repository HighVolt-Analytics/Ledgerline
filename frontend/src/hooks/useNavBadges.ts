import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import { queryKeys } from "@/lib/queryClient";

export function useNavBadges() {
  return useQuery({
    queryKey: queryKeys.navBadges,
    queryFn: () => api.getNavBadges(),
    refetchInterval: 30_000,
  });
}
