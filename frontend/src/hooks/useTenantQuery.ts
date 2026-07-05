import {
  useQuery,
  type QueryKey,
  type UseQueryResult,
} from "@tanstack/react-query";
import { getActiveTenantId } from "@/api/client";
import { useAuth } from "@/context/AuthContext";
import { useTenantOwnedData } from "@/hooks/useTenantOwnedData";
import {
  canRenderTenantOwnedUi,
  captureTenantFetchScope,
  isTenantFetchAbortError,
  isTenantFetchScopeCurrent,
  TenantFetchAbortError,
} from "@/lib/tenantSession";

export function tenantIdFromQueryKey(key: QueryKey): string | null {
  const first = key[0];
  return typeof first === "string" && first !== "signed-out" && first !== "unknown"
    ? first
    : null;
}

type TenantUseQueryOptions<TQueryFnData, TError = Error> = {
  /** Tenant-scoped key from queryKeys.*() (first element must be tenant id). */
  queryKey: QueryKey;
  queryFn: () => Promise<TQueryFnData>;
  enabled?: boolean;
  staleTime?: number;
  gcTime?: number;
  refetchInterval?: number | false;
  refetchOnMount?: boolean | "always";
  retry?: boolean | number | ((failureCount: number, error: TError) => boolean);
};

function mergeScopeRetry<TError>(
  userRetry: TenantUseQueryOptions<unknown, TError>["retry"]
): (failureCount: number, err: unknown) => boolean {
  return (failureCount, err) => {
    if (isTenantFetchAbortError(err) && failureCount < 2) return true;
    if (userRetry === undefined) return false;
    if (typeof userRetry === "boolean") return userRetry;
    if (typeof userRetry === "number") return failureCount < userRetry;
    return userRetry(failureCount, err as TError);
  };
}

/**
 * Tenant-scoped useQuery: requires tenant-prefixed keys, aborts fetches across
 * tenant changes, and masks results when scope is inconsistent.
 */
export function useTenantQuery<TQueryFnData, TError = Error, TData = TQueryFnData>(
  options: TenantUseQueryOptions<TQueryFnData, TError>
): UseQueryResult<TData, TError> & { blocked: boolean; tenantId: string | null } {
  const { user } = useAuth();
  const profileTenantId = user?.tenant_id ?? null;
  const scopeOk = canRenderTenantOwnedUi(profileTenantId);
  const activeTenantId = getActiveTenantId();
  const keyTenantId = tenantIdFromQueryKey(options.queryKey);
  const { retry: userRetry, ...queryOptions } = options;

  const query = useQuery({
    ...queryOptions,
    structuralSharing: false,
    retry: mergeScopeRetry(userRetry),
    enabled:
      (typeof options.enabled === "boolean" ? options.enabled : true) &&
      scopeOk &&
      Boolean(activeTenantId) &&
      keyTenantId === activeTenantId,
    queryFn: async () => {
      const scope = captureTenantFetchScope();
      const data = await options.queryFn();
      if (!isTenantFetchScopeCurrent(scope)) {
        throw new TenantFetchAbortError();
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

  const scopeAbortError =
    query.isError && isTenantFetchAbortError(query.error) ? query.error : null;

  return {
    ...query,
    isError: query.isError && !scopeAbortError,
    error: scopeAbortError ? null : (query.error as TError | null),
    data: safeData as TData | undefined,
    blocked: blocked || Boolean(scopeAbortError),
    tenantId,
  } as unknown as UseQueryResult<TData, TError> & { blocked: boolean; tenantId: string | null };
}
