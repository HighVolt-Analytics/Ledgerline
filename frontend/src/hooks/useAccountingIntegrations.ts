import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/api/client";
import type {
  AccountingIntegrationsStatus,
  XeroConnectionItem,
  XeroReadiness,
  XeroSyncContactsResult,
  XeroSyncSettingsResult,
  XeroVerifyResult,
} from "@/api/types";
import { useResetOnTenantChange } from "@/hooks/useResetOnTenantChange";
import { tenantQueryKey } from "@/lib/queryClient";
import {
  captureTenantFetchScope,
  handleTenantScopedLoadFailure,
  isTenantFetchScopeCurrent,
} from "@/lib/tenantSession";

/** Tenant-scoped React Query key parts for Xero integration data. */
export const xeroIntegrationKeys = {
  status: ["integrations", "accounting", "status"] as const,
  readiness: ["integrations", "xero", "readiness"] as const,
  connections: ["integrations", "xero", "connections"] as const,
};

export function xeroIntegrationQueryKey(part: keyof typeof xeroIntegrationKeys) {
  return tenantQueryKey(xeroIntegrationKeys[part]);
}

export function parseLedgerLinkInvoiceId(rowId: string): number | null {
  const match = /^ll-inv-(\d+)$/.exec(rowId.trim());
  if (!match) return null;
  const id = Number(match[1]);
  return Number.isFinite(id) ? id : null;
}

export function useAccountingIntegrations(enabled = true) {
  const [status, setStatus] = useState<AccountingIntegrationsStatus | null>(null);
  const [xeroReadiness, setXeroReadiness] = useState<XeroReadiness | null>(null);
  const [xeroVerify, setXeroVerify] = useState<XeroVerifyResult | null>(null);
  const [xeroConnections, setXeroConnections] = useState<XeroConnectionItem[]>([]);
  const [loading, setLoading] = useState(enabled);
  const [xeroLoading, setXeroLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [xeroError, setXeroError] = useState<string | null>(null);
  const loadSeq = useRef(0);
  const xeroLoadSeq = useRef(0);

  useResetOnTenantChange(() => {
    loadSeq.current += 1;
    xeroLoadSeq.current += 1;
    setStatus(null);
    setXeroReadiness(null);
    setXeroVerify(null);
    setXeroConnections([]);
    setError(null);
    setXeroError(null);
    setLoading(enabled);
    setXeroLoading(false);
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
      if (
        handleTenantScopedLoadFailure(err, {
          retry: () => {
            void reload(true);
          },
        })
      ) {
        return;
      }
      setStatus(null);
      setError(err instanceof Error ? err.message : "Failed to load accounting integrations");
    } finally {
      if (seq === loadSeq.current) {
        setLoading(false);
      }
    }
  }, [enabled]);

  const reloadXero = useCallback(async (fresh = false) => {
    if (!enabled) return;
    const scope = captureTenantFetchScope();
    const seq = ++xeroLoadSeq.current;
    setXeroLoading(true);
    try {
      const [readiness, connections] = await Promise.all([
        api.getXeroReadiness({ fresh }),
        api.getXeroConnections({ fresh }),
      ]);
      if (seq !== xeroLoadSeq.current || !isTenantFetchScopeCurrent(scope)) return;
      setXeroReadiness(readiness);
      setXeroConnections(connections.connections);
      setXeroError(null);
    } catch (err) {
      if (seq !== xeroLoadSeq.current || !isTenantFetchScopeCurrent(scope)) return;
      if (
        handleTenantScopedLoadFailure(err, {
          retry: () => {
            void reloadXero(true);
          },
        })
      ) {
        return;
      }
      setXeroReadiness(null);
      setXeroConnections([]);
      setXeroError(err instanceof Error ? err.message : "Failed to load Xero integration");
    } finally {
      if (seq === xeroLoadSeq.current) {
        setXeroLoading(false);
      }
    }
  }, [enabled]);

  const reloadAll = useCallback(
    async (fresh = false) => {
      await Promise.all([reload(fresh), reloadXero(fresh)]);
    },
    [reload, reloadXero]
  );

  const selectXeroOrg = useCallback(
    async (xeroConnectionId: string) => {
      const scope = captureTenantFetchScope();
      const result = await api.selectXeroConnection(xeroConnectionId);
      if (!isTenantFetchScopeCurrent(scope)) return result;
      await reloadAll(true);
      return result;
    },
    [reloadAll]
  );

  const syncXeroSettings = useCallback(async (): Promise<XeroSyncSettingsResult> => {
    const scope = captureTenantFetchScope();
    const result = await api.syncXeroSettings();
    if (!isTenantFetchScopeCurrent(scope)) return result;
    await reloadXero(true);
    return result;
  }, [reloadXero]);

  const syncXeroContacts = useCallback(async (): Promise<XeroSyncContactsResult> => {
    const scope = captureTenantFetchScope();
    const result = await api.syncXeroContacts();
    if (!isTenantFetchScopeCurrent(scope)) return result;
    await reloadXero(true);
    return result;
  }, [reloadXero]);

  const verifyXeroConnection = useCallback(async (): Promise<XeroVerifyResult> => {
    const scope = captureTenantFetchScope();
    const result = await api.verifyXeroConnection();
    if (!isTenantFetchScopeCurrent(scope)) return result;
    setXeroVerify(result);
    await reloadXero(true);
    return result;
  }, [reloadXero]);

  useEffect(() => {
    void reload();
  }, [reload]);

  useEffect(() => {
    void reloadXero();
  }, [reloadXero]);

  return {
    status,
    xeroReadiness,
    xeroVerify,
    xeroConnections,
    loading,
    xeroLoading,
    error,
    xeroError,
    reload,
    reloadXero,
    reloadAll,
    selectXeroOrg,
    syncXeroSettings,
    syncXeroContacts,
    verifyXeroConnection,
  };
}
