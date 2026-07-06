import { useTenantQuery } from "@/hooks/useTenantQuery";
import { api } from "@/api/client";
import type { UserPermissions } from "@/api/types";
import { queryKeys } from "@/lib/queryClient";

export function usePermissions() {
  const query = useTenantQuery({
    queryKey: queryKeys.myPermissions(),
    queryFn: () => api.getMyPermissions(),
  });
  return {
    permissions: (query.data ?? null) as UserPermissions | null,
    loading: query.isLoading || query.isPending || query.blocked,
  };
}

export function canAccessNavPath(
  path: string,
  permissions: UserPermissions | null | undefined
): boolean {
  if (!permissions) return true;
  if (path === "/rules") return permissions.permissions["Edit Policy"] === true;
  if (path === "/integrations") return permissions.permissions["Manage Users"] === true;
  if (path === "/upload") {
    return (
      permissions.permissions.Comment === true ||
      permissions.permissions.Approve === true ||
      permissions.permissions.Post === true
    );
  }
  return permissions.permissions.View !== false;
}
