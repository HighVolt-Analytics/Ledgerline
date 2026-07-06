import { useTenantQuery } from "@/hooks/useTenantQuery";
import { api } from "@/api/client";
import { queryKeys } from "@/lib/queryClient";

export function useInstitutionSettings(enabled = true) {
  return useTenantQuery({
    queryKey: queryKeys.institutionSettings(),
    queryFn: () => api.getInstitutionSettings(),
    enabled,
  });
}
