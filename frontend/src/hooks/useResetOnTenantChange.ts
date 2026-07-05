import { useLayoutEffect, useRef } from "react";
import { useAuth } from "@/context/AuthContext";

/** Run reset when the signed-in tenant changes (org switch / tenant pick). */
export function useResetOnTenantChange(reset: () => void): void {
  const { user } = useAuth();
  const tenantId = user?.tenant_id ?? null;
  const resetRef = useRef(reset);
  const prevTenantRef = useRef<string | null | undefined>(undefined);

  resetRef.current = reset;

  useLayoutEffect(() => {
    if (prevTenantRef.current === undefined) {
      prevTenantRef.current = tenantId;
      return;
    }
    if (prevTenantRef.current !== tenantId) {
      prevTenantRef.current = tenantId;
      resetRef.current();
    }
  }, [tenantId]);
}
