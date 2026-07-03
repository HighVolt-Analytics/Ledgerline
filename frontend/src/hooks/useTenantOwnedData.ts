import { useAuth } from "@/context/AuthContext";
import { getActiveTenantId } from "@/api/client";
import { guardedTenantData, isTenantScopeConsistent } from "@/lib/tenantSession";

type TenantQueryMeta = {
  isLoading?: boolean;
  /** When set, must match the active user tenant before data is shown. */
  dataTenantId?: string | null;
};

export function useTenantScopeConsistent(): boolean {
  const { user } = useAuth();
  return isTenantScopeConsistent(user?.tenant_id);
}

export function useActiveTenantId(): string | null {
  const { user } = useAuth();
  return user?.tenant_id ?? getActiveTenantId();
}

/** Mask tenant-owned query results until JWT scope and profile tenant align. */
export function useTenantOwnedData<T>(
  data: T | undefined,
  meta: TenantQueryMeta = {}
): { data: T | undefined; blocked: boolean; tenantId: string | null } {
  const { user } = useAuth();
  const tenantId = user?.tenant_id ?? null;
  const scopeOk = isTenantScopeConsistent(tenantId);
  const safeData = guardedTenantData(data, {
    profileTenantId: tenantId,
    isLoading: meta.isLoading,
    dataTenantId: meta.dataTenantId ?? tenantId,
  });

  return {
    data: safeData,
    blocked: !scopeOk || safeData === undefined,
    tenantId,
  };
}
