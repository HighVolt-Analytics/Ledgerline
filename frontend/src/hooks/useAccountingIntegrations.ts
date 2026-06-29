import { useCallback, useEffect, useState } from "react";
import { api } from "@/api/client";
import type { AccountingIntegrationsStatus } from "@/api/types";

export function useAccountingIntegrations(enabled = true) {
  const [status, setStatus] = useState<AccountingIntegrationsStatus | null>(null);
  const [loading, setLoading] = useState(enabled);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(async (fresh = false) => {
    if (!enabled) return;
    setLoading(true);
    try {
      const data = await api.getAccountingIntegrationsStatus({ fresh });
      setStatus(data);
      setError(null);
    } catch (err) {
      setStatus(null);
      setError(err instanceof Error ? err.message : "Failed to load accounting integrations");
    } finally {
      setLoading(false);
    }
  }, [enabled]);

  useEffect(() => {
    void reload();
  }, [reload]);

  return { status, loading, error, reload };
}
