import { clearGetCache, getActiveTenantId } from "@/api/client";
import { getAccessToken, getStoredUser } from "@/lib/authSession";
import { tenantIdFromToken } from "@/lib/authToken";
import { clearInvoiceFetchDedupe } from "@/lib/invoices";
import { queryClient } from "@/lib/queryClient";
import { clearRecognitionSignalCatalog } from "@/lib/recognitionSignalCatalog";

/** Tenant id from persisted session before applying a new access token. */
export function readSessionTenantId(): string | null {
  return tenantIdFromToken(getAccessToken()) ?? getStoredUser()?.tenant_id ?? null;
}

export function tenantSessionWillChange(nextAccessToken: string): boolean {
  const previousTenantId = readSessionTenantId();
  const nextTenantId = tenantIdFromToken(nextAccessToken);
  return Boolean(previousTenantId && nextTenantId && previousTenantId !== nextTenantId);
}

export function clearAllTenantCaches(): void {
  queryClient.clear();
  clearGetCache();
  clearRecognitionSignalCatalog();
  clearInvoiceFetchDedupe();
}

/** Whether tenant-scoped queries should run (JWT matches profile). */
export function tenantQueriesEnabled(profileTenantId: string | null | undefined): boolean {
  return isTenantScopeConsistent(profileTenantId);
}

/** True when JWT/session tenant matches the signed-in user profile tenant. */
export function isTenantScopeConsistent(profileTenantId: string | null | undefined): boolean {
  const jwtTenantId = getActiveTenantId();
  if (!profileTenantId || !jwtTenantId) return Boolean(profileTenantId) === Boolean(jwtTenantId);
  return profileTenantId === jwtTenantId;
}

/**
 * Hide tenant-owned list data while scope is inconsistent or a refetch is in flight
 * after the active tenant changed.
 */
export function guardedTenantData<T>(
  data: T | undefined,
  options: {
    profileTenantId: string | null | undefined;
    isLoading?: boolean;
    dataTenantId?: string | null;
  }
): T | undefined {
  if (!isTenantScopeConsistent(options.profileTenantId)) return undefined;
  if (options.isLoading) return undefined;
  if (
    options.dataTenantId &&
    options.profileTenantId &&
    options.dataTenantId !== options.profileTenantId
  ) {
    return undefined;
  }
  return data;
}
