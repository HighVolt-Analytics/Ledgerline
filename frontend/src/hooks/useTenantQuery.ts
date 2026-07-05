import {
  useQuery,
  type QueryKey,
  type UseQueryOptions,
  type UseQueryResult,
} from "@tanstack/react-query";
import { useAuth } from "@/context/AuthContext";
import { guardedTenantData, isTenantScopeConsistent } from "@/lib/tenantSession";

type TenantQueryOptions<
  TQueryFnData = unknown,
  TError = Error,
  TData = TQueryFnData,
  TQueryKey extends QueryKey = QueryKey,
> = UseQueryOptions<TQueryFnData, TError, TData, TQueryKey>;

export type TenantQueryResult<
  TData = unknown,
  TError = Error,
> = Omit<UseQueryResult<TData, TError>, "data"> & {
  data: TData | undefined;
  blocked: boolean;
  tenantId: string | null;
};

/** Tenant-gated useQuery — masks data until JWT scope and profile tenant align. */
export function useTenantQuery<
  TQueryFnData = unknown,
  TError = Error,
  TData = TQueryFnData,
  TQueryKey extends QueryKey = QueryKey,
>(
  options: TenantQueryOptions<TQueryFnData, TError, TData, TQueryKey>
): TenantQueryResult<TData, TError> {
  const { user } = useAuth();
  const tenantId = user?.tenant_id ?? null;
  const scopeOk = isTenantScopeConsistent(tenantId);
  const callerEnabled = options.enabled ?? true;

  const query = useQuery({
    ...options,
    enabled: scopeOk && callerEnabled,
  });

  const safeData = guardedTenantData(query.data, {
    profileTenantId: tenantId,
    isLoading: query.isLoading || query.isFetching,
    dataTenantId: tenantId,
  });

  return {
    ...query,
    data: safeData,
    blocked: !scopeOk || safeData === undefined,
    tenantId,
  } as TenantQueryResult<TData, TError>;
}
