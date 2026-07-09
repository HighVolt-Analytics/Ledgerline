import { useEffect, useRef, useSyncExternalStore } from "react";
import { useAuth } from "@/context/AuthContext";
import {
  getTenantDataGeneration,
  subscribeTenantScope,
} from "@/lib/tenantSession";

/**
 * Run reset when the signed-in tenant or tenant data generation changes.
 * Clears local page state so in-flight responses cannot repaint prior-tenant rows.
 */
export function useResetOnTenantChange(reset: () => void): void {
  const { user } = useAuth();
  const tenantId = user?.tenant_id ?? null;
  const generation = useSyncExternalStore(
    subscribeTenantScope,
    getTenantDataGeneration,
    getTenantDataGeneration
  );
  const resetRef = useRef(reset);
  resetRef.current = reset;
  const prevRef = useRef<{ tenantId: string | null; generation: number } | null>(null);

  useEffect(() => {
    const prev = prevRef.current;
    prevRef.current = { tenantId, generation };
    // Skip the initial mount reset only when generation is unchanged from first paint
    // and we have not yet established a prior snapshot — still reset on first mount
    // so stale state from a parent remount cannot linger.
    if (prev == null) {
      resetRef.current();
      return;
    }
    if (prev.tenantId !== tenantId || prev.generation !== generation) {
      resetRef.current();
    }
  }, [tenantId, generation]);
}
