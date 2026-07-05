import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import { useAuth } from "@/context/AuthContext";
import { useTenantQuery } from "@/hooks/useTenantQuery";
import { isSuperAdmin } from "@/lib/roles";
import { queryKeys } from "@/lib/queryClient";

export function useNotifications() {
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const enabled = Boolean(user && !isSuperAdmin(user.role));

  const query = useTenantQuery({
    queryKey: queryKeys.notifications(),
    queryFn: () => api.getNotifications(),
    refetchInterval: 30_000,
    enabled,
  });

  const markAllRead = useMutation({
    mutationFn: () => api.markNotificationsRead(),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.notifications() });
    },
  });

  return {
    ...query,
    markAllRead,
  };
}
