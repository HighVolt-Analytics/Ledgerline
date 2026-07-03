import { type ReactNode } from "react";
import { useAuth } from "@/context/AuthContext";
import { PageLoader } from "@/components/PageLoader";
import { isTenantScopeConsistent } from "@/lib/tenantSession";

/**
 * Remounts tenant-scoped UI when tenant_id changes and blocks render while
 * JWT scope and profile tenant are out of sync (mid-switch).
 */
export function TenantBoundary({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth();
  const tenantId = user?.tenant_id ?? null;

  if (loading) {
    return <PageLoader />;
  }

  if (user && !isTenantScopeConsistent(tenantId)) {
    return <PageLoader />;
  }

  return <div key={tenantId ?? "signed-out"}>{children}</div>;
}
