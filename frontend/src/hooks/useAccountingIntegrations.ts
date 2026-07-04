import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/api/client";
import type { AccountingIntegrationsStatus } from "@/api/types";
import { useResetOnTenantChange } from "@/hooks/useResetOnTenantChange";
import {
  captureTenantFetchScope,
  isTenantFetchScopeCurrent,
} from "@/lib/tenantSession";

export function useAccountingIntegrations(enabled = true) {
  const [status, setStatus] = useState<AccountingIntegrationsStatus | null>(null);
  const [loading, setLoading] = useState(enabled);
  const [error, setError] = useState<string | null>(null);
  const loadSeq = useRef(0);

  useResetOnTenantChange(() => {
    loadSeq.current += 1;
    setStatus(null);
    setError(null);
    setLoading(enabled);
  });

  const reload = useCallback(async (fresh = false) => {
    if (!enabled) return;
    const scope = captureTenantFetchScope();
    const seq = ++loadSeq.current;
    setLoading(true);
    try {
      const data = await api.getAccountingIntegrationsStatus({ fresh });
      if (seq !== loadSeq.current || !isTenantFetchScopeCurrent(scope)) return;
      setStatus(data);
      setError(null);
    } catch (err) {
      if (seq !== loadSeq.current || !isTenantFetchScopeCurrent(scope)) return;
      setStatus(null);
      setError(err instanceof Error ? err.message : "Failed to load accounting integrations");
    } finally {
      if (seq === loadSeq.current && isTenantFetchScopeCurrent(scope)) {
        setLoading(false);
      }
    }
  }, [enabled]);

  useEffect(() => {
    void reload();
  }, [reload]);

  return { status, loading, error, reload };
}
