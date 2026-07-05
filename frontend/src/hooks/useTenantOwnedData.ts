import { useSyncExternalStore } from "react";
import { getActiveTenantId } from "@/api/client";
import { useAuth } from "@/context/AuthContext";
import {
  canRenderTenantOwnedUi,
  getTenantDataGeneration,
  guardedTenantData,
  isTenantTransitionActive,
  subscribeTenantScope,
} from "@/lib/tenantSession";

type TenantQueryMeta = {
  isLoading?: boolean;
  /** Tenant id the payload was fetched for (query key[0] or response stamp). */
  dataTenantId?: string | null;
  /** First element of a tenant-scoped React Query key. */
  queryKeyTenantId?: string | null;
  /** Generation captured when the fetch started (local-state loaders). */
  fetchGeneration?: number | null;
};

export function useTenantScopeConsistent(): boolean {
  const { user } = useAuth();
  useSyncExternalStore(subscribeTenantScope, getTenantDataGeneration, getTenantDataGeneration);
  useSyncExternalStore(subscribeTenantScope, isTenantTransitionActive, isTenantTransitionActive);
  return canRenderTenantOwnedUi(user?.tenant_id);
}

export function useActiveTenantId(): string | null {
  const { user } = useAuth();
  useSyncExternalStore(subscribeTenantScope, getTenantDataGeneration, getTenantDataGeneration);
  return getActiveTenantId() ?? user?.tenant_id ?? null;
}

/**
 * Mask tenant-owned query results until JWT scope and profile tenant align,
 * and never surface rows fetched for a different tenant.
 */
export function useTenantOwnedData<T>(
  data: T | undefined,
  meta: TenantQueryMeta = {}
): { data: T | undefined; blocked: boolean; tenantId: string | null } {
  const { user } = useAuth();
  useSyncExternalStore(subscribeTenantScope, getTenantDataGeneration, getTenantDataGeneration);
  useSyncExternalStore(subscribeTenantScope, isTenantTransitionActive, isTenantTransitionActive);

  const profileTenantId = user?.tenant_id ?? null;
  const jwtTenantId = getActiveTenantId();
  const queryKeyTenantId = meta.queryKeyTenantId ?? null;
  // Prefer explicit stamps; fall back to query-key tenant, never assume profile alone.
  const dataTenantId = meta.dataTenantId ?? queryKeyTenantId ?? null;

  const safeData = guardedTenantData(data, {
    profileTenantId,
    isLoading: meta.isLoading,
    dataTenantId,
    queryKeyTenantId,
    fetchGeneration: meta.fetchGeneration,
  });

  const scopeOk = canRenderTenantOwnedUi(profileTenantId);
  const blocked = !scopeOk || meta.isLoading === true || safeData === undefined;

  return {
    data: safeData,
    blocked,
    tenantId: jwtTenantId ?? profileTenantId,
  };
}
