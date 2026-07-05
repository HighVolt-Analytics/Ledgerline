import { useEffect, useSyncExternalStore, type ReactNode } from "react";
import { getActiveTenantId } from "@/api/client";
import { PageLoader } from "@/components/PageLoader";
import { useAuth } from "@/context/AuthContext";
import {
  canRenderTenantOwnedUi,
  endTenantTransition,
  getTenantDataGeneration,
  isTenantScopeConsistent,
  isTenantTransitionActive,
  subscribeTenantScope,
} from "@/lib/tenantSession";

/**
 * Remounts tenant-scoped UI when tenant_id / generation changes and blocks render
 * while JWT scope and profile tenant are out of sync or a switch is in flight.
 */
export function TenantBoundary({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth();
  const generation = useSyncExternalStore(
    subscribeTenantScope,
    getTenantDataGeneration,
    getTenantDataGeneration
  );
  const transitioning = useSyncExternalStore(
    subscribeTenantScope,
    isTenantTransitionActive,
    isTenantTransitionActive
  );

  const profileTenantId = user?.tenant_id ?? null;
  const jwtTenantId = getActiveTenantId();
  const scopeOk = isTenantScopeConsistent(profileTenantId);
  const canRender = canRenderTenantOwnedUi(profileTenantId);

  // Once JWT and profile agree, release the transition lock so a delayed hard
  // reload cannot leave the app stuck on the loader. Caches are already cleared.
  useEffect(() => {
    if (!loading && scopeOk && transitioning && jwtTenantId === profileTenantId) {
      endTenantTransition();
    }
  }, [loading, scopeOk, transitioning, profileTenantId, jwtTenantId, generation]);

  if (loading || (user && !canRender)) {
    return <PageLoader label="Loading organisation…" />;
  }

  return (
    <div key={`${profileTenantId ?? "signed-out"}:${generation}`}>{children}</div>
  );
}
