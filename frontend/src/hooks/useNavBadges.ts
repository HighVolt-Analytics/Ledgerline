import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import { useAuth } from "@/context/AuthContext";
import { isSuperAdmin } from "@/lib/roles";
import { queryKeys } from "@/lib/queryClient";

export function useNavBadges() {
  const { user } = useAuth();
  return useQuery({
    queryKey: queryKeys.navBadges(),
    queryFn: () => api.getNavBadges(),
    refetchInterval: 30_000,
    enabled: Boolean(user && !isSuperAdmin(user.role)),
  });
}
