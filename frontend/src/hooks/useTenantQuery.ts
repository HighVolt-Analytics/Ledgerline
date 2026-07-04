import {
  useQuery,
  type QueryKey,
  type UseQueryOptions,
  type UseQueryResult,
} from "@tanstack/react-query";
import { getActiveTenantId } from "@/api/client";
import { useAuth } from "@/context/AuthContext";
import { useTenantOwnedData } from "@/hooks/useTenantOwnedData";
import {
  canRenderTenantOwnedUi,
  captureTenantFetchScope,
  isTenantFetchScopeCurrent,
} from "@/lib/tenantSession";

export function tenantIdFromQueryKey(key: QueryKey): string | null {
  const first = key[0];
  return typeof first === "string" && first !== "signed-out" && first !== "unknown"
    ? first
    : null;
}

type TenantUseQueryOptions<TQueryFnData, TError, TData> = Omit<
  UseQueryOptions<TQueryFnData, TError, TData, QueryKey>,
  "queryFn"
> & {
  /** Tenant-scoped key from queryKeys.*() (first element must be tenant id). */
  queryKey: QueryKey;
  queryFn: () => Promise<TQueryFnData>;
};

/**
 * Tenant-scoped useQuery: requires tenant-prefixed keys, aborts fetches across
 * tenant changes, and masks results when scope is inconsistent.
 */
export function useTenantQuery<TQueryFnData, TError = Error, TData = TQueryFnData>(
  options: TenantUseQueryOptions<TQueryFnData, TError, TData>
): UseQueryResult<TData, TError> & { blocked: boolean; tenantId: string | null } {
  const { user } = useAuth();
  const profileTenantId = user?.tenant_id ?? null;
  const scopeOk = canRenderTenantOwnedUi(profileTenantId);
  const activeTenantId = getActiveTenantId();
  const keyTenantId = tenantIdFromQueryKey(options.queryKey);

  const query = useQuery({
    ...options,
    structuralSharing: false,
    enabled:
      (typeof options.enabled === "boolean" ? options.enabled : true) &&
      scopeOk &&
      Boolean(activeTenantId) &&
      keyTenantId === activeTenantId,
    queryFn: async () => {
      const scope = captureTenantFetchScope();
      const data = await options.queryFn();
      if (!isTenantFetchScopeCurrent(scope)) {
        throw new Error("Tenant scope changed");
      }
      return data;
    },
  });

  const { data: safeData, blocked, tenantId } = useTenantOwnedData(
    query.data as TData | undefined,
    {
      isLoading: query.isLoading || query.isPending,
      queryKeyTenantId: keyTenantId,
      dataTenantId: keyTenantId,
    }
  );

  return {
    ...query,
    data: safeData as TData | undefined,
    blocked,
    tenantId,
  } as UseQueryResult<TData, TError> & { blocked: boolean; tenantId: string | null };
}
