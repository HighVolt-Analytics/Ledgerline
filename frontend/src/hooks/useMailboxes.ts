import { useTenantQuery } from "@/hooks/useTenantQuery";
import { api } from "@/api/client";
import { useAuth } from "@/context/AuthContext";
import { isSuperAdmin } from "@/lib/roles";
import { queryKeys } from "@/lib/queryClient";

export function useMailboxes(enabled = true) {
  const { user } = useAuth();
  return useTenantQuery({
    queryKey: queryKeys.mailboxes(),
    queryFn: () => api.listMailboxes(),
    enabled: enabled && Boolean(user && !isSuperAdmin(user.role)),
  });
}
