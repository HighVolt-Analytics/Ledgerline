import { ApiError, clearGetCache, getActiveTenantId, getAuthToken } from "@/api/client";
import { getAccessToken, getStoredUser } from "@/lib/authSession";
import { tenantIdFromToken } from "@/lib/authToken";
import { queryClient } from "@/lib/queryClient";

export const TENANT_SCOPE_CHANGED_EVENT = "ledgerline:tenant-scope-changed";

export const TENANT_SCOPE_CHANGED_MESSAGE = "Tenant scope changed";

/** Non-user-facing abort when a fetch completes after tenant scope moved on. */
export class TenantFetchAbortError extends Error {
  constructor(message = TENANT_SCOPE_CHANGED_MESSAGE) {
    super(message);
    this.name = "TenantFetchAbortError";
  }
}

export function isTenantFetchAbortError(err: unknown): boolean {
  if (err instanceof TenantFetchAbortError) return true;
  if (err instanceof ApiError && err.status === 409 && err.message === TENANT_SCOPE_CHANGED_MESSAGE) {
    return true;
  }
  if (err instanceof Error && !(err instanceof ApiError) && err.message === TENANT_SCOPE_CHANGED_MESSAGE) {
    return true;
  }
  return false;
}

export function formatTenantLoadError(message: string, apiHint: string): string {
  if (message === TENANT_SCOPE_CHANGED_MESSAGE) return message;
  return message + apiHint;
}

export const API_PORT_HINT = " Ensure the API is running on port 8001.";

/** Ignore scope-abort failures in manual loaders; optionally retry. */
export function handleTenantScopedLoadFailure(
  err: unknown,
  options?: { retry?: () => void }
): boolean {
  if (!isTenantFetchAbortError(err)) return false;
  options?.retry?.();
  return true;
}

/** Bumped on every tenant change / full cache clear so in-flight work can self-abort. */
let tenantDataGeneration = 0;

/** True while a tenant switch is in progress (before hard reload or scope settles). */
let tenantTransitionActive = false;

type TenantScopeListener = () => void;
const listeners = new Set<TenantScopeListener>();

function notifyTenantScopeListeners(): void {
  for (const listener of listeners) {
    try {
      listener();
    } catch {
      /* ignore subscriber errors */
    }
  }
  if (typeof window !== "undefined") {
    window.dispatchEvent(
      new CustomEvent(TENANT_SCOPE_CHANGED_EVENT, {
        detail: {
          generation: tenantDataGeneration,
          tenantId: getActiveTenantId(),
          transitioning: tenantTransitionActive,
        },
      })
    );
  }
}

export function getTenantDataGeneration(): number {
  return tenantDataGeneration;
}

export function isTenantTransitionActive(): boolean {
  return tenantTransitionActive;
}

export function subscribeTenantScope(listener: TenantScopeListener): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function beginTenantTransition(): void {
  tenantTransitionActive = true;
  tenantDataGeneration += 1;
  notifyTenantScopeListeners();
}

export function endTenantTransition(): void {
  if (!tenantTransitionActive) return;
  tenantTransitionActive = false;
  notifyTenantScopeListeners();
}

/** Tenant id from in-memory JWT first, then persisted session (pre-persist reads). */
export function readSessionTenantId(previousAccessToken?: string | null): string | null {
  const fromMemory = tenantIdFromToken(previousAccessToken ?? getAuthToken());
  if (fromMemory) return fromMemory;
  return tenantIdFromToken(getAccessToken()) ?? getStoredUser()?.tenant_id ?? null;
}

/**
 * Detect tenant change BEFORE persistAuthSuccess writes the new token.
 * Prefer an explicit previous token (in-memory) so sessionStorage is never the sole source.
 */
export function tenantSessionWillChange(
  nextAccessToken: string,
  previousAccessToken?: string | null
): boolean {
  const previousTenantId = readSessionTenantId(previousAccessToken);
  const nextTenantId = tenantIdFromToken(nextAccessToken);
  return Boolean(previousTenantId && nextTenantId && previousTenantId !== nextTenantId);
}

export function clearAllTenantCaches(): void {
  beginTenantTransition();
  queryClient.clear();
  clearGetCache();
  notifyTenantScopeListeners();
}

/** True when JWT tenant and profile tenant agree (ignores in-flight transition lock). */
export function isTenantScopeConsistent(profileTenantId: string | null | undefined): boolean {
  const jwtTenantId = getActiveTenantId();
  if (!profileTenantId || !jwtTenantId) {
    return Boolean(profileTenantId) === Boolean(jwtTenantId);
  }
  return profileTenantId === jwtTenantId;
}

/** Safe to paint tenant-owned UI: scope consistent and not mid-switch. */
export function canRenderTenantOwnedUi(profileTenantId: string | null | undefined): boolean {
  return !tenantTransitionActive && isTenantScopeConsistent(profileTenantId);
}

/**
 * Hide tenant-owned list data while scope is inconsistent, transitioning,
 * loading, or when the data was fetched for a different tenant.
 */
export function guardedTenantData<T>(
  data: T | undefined,
  options: {
    profileTenantId: string | null | undefined;
    isLoading?: boolean;
    /** Tenant id the data was fetched for (from query key or response stamp). */
    dataTenantId?: string | null;
    /** First element of a tenant-scoped React Query key. */
    queryKeyTenantId?: string | null;
    fetchGeneration?: number | null;
  }
): T | undefined {
  if (!canRenderTenantOwnedUi(options.profileTenantId)) return undefined;
  if (options.isLoading) return undefined;

  const activeTenantId = getActiveTenantId();
  if (!activeTenantId || activeTenantId !== options.profileTenantId) return undefined;

  if (
    options.queryKeyTenantId != null &&
    options.queryKeyTenantId !== activeTenantId
  ) {
    return undefined;
  }

  if (options.dataTenantId != null && options.dataTenantId !== activeTenantId) {
    return undefined;
  }

  if (
    options.fetchGeneration != null &&
    options.fetchGeneration !== tenantDataGeneration
  ) {
    return undefined;
  }

  return data;
}

/** Snapshot for in-flight work; discard results when this no longer matches. */
export function captureTenantFetchScope(): {
  tenantId: string | null;
  generation: number;
} {
  return {
    tenantId: getActiveTenantId(),
    generation: tenantDataGeneration,
  };
}

export function isTenantFetchScopeCurrent(scope: {
  tenantId: string | null;
  generation: number;
}): boolean {
  if (tenantTransitionActive) return false;
  if (scope.generation !== tenantDataGeneration) return false;
  const active = getActiveTenantId();
  if (!scope.tenantId || !active) return false;
  return scope.tenantId === active;
}
