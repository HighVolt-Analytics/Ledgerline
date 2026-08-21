import { api } from "@/api/client";
import { useAuth } from "@/context/AuthContext";
import { useTenantQuery } from "@/hooks/useTenantQuery";
import { isSuperAdmin } from "@/lib/roles";
import { queryKeys } from "@/lib/queryClient";

export function useNavBadges() {
  const { user } = useAuth();
  return useTenantQuery({
    queryKey: queryKeys.navBadges(),
    queryFn: () => api.getNavBadges(),
    refetchInterval: 90_000,
    enabled: Boolean(user && !isSuperAdmin(user.role)),
  });
}
