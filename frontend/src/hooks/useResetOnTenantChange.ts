import { useEffect, useRef } from "react";
import { useAuth } from "@/context/AuthContext";

/** Run reset when the signed-in tenant changes (org switch / tenant pick). */
export function useResetOnTenantChange(reset: () => void): void {
  const { user } = useAuth();
  const tenantId = user?.tenant_id ?? null;
  const resetRef = useRef(reset);
  resetRef.current = reset;

  useEffect(() => {
    resetRef.current();
  }, [tenantId]);
}
