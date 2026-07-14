/**
 * User-visible proof of Xero inbound/outbound sync: stored master data + history.
 */
import { useCallback, useEffect, useState } from "react";
import { api } from "@/api/client";
import type {
  XeroAccountRow,
  XeroContactRow,
  XeroExportHistoryRow,
  XeroMasterTotals,
  XeroSyncHistoryRow,
  XeroTaxRateRow,
} from "@/api/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useResetOnTenantChange } from "@/hooks/useResetOnTenantChange";
import {
  captureTenantFetchScope,
  isTenantFetchScopeCurrent,
} from "@/lib/tenantSession";

type TabId = "overview" | "accounts" | "tax_rates" | "contacts" | "sync_history" | "export_history";

const TABS: { id: TabId; label: string }[] = [
  { id: "overview", label: "Overview" },
  { id: "accounts", label: "Accounts" },
  { id: "tax_rates", label: "Tax rates" },
  { id: "contacts", label: "Contacts" },
  { id: "sync_history", label: "Sync history" },
  { id: "export_history", label: "Export history" },
];

function ProvenanceBadge() {
  return (
    <Badge variant="outline" className="text-[10px]">
      Source: Xero
    </Badge>
  );
}

export function XeroEvidencePanel({ enabled }: { enabled: boolean }) {
  const [tab, setTab] = useState<TabId>("overview");
  const [totals, setTotals] = useState<XeroMasterTotals | null>(null);
  const [accounts, setAccounts] = useState<XeroAccountRow[]>([]);
  const [taxRates, setTaxRates] = useState<XeroTaxRateRow[]>([]);
  const [contacts, setContacts] = useState<XeroContactRow[]>([]);
  const [syncHistory, setSyncHistory] = useState<XeroSyncHistoryRow[]>([]);
  const [exportHistory, setExportHistory] = useState<XeroExportHistoryRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reconcileBusy, setReconcileBusy] = useState(false);

  useResetOnTenantChange(() => {
    setTotals(null);
    setAccounts([]);
    setTaxRates([]);
    setContacts([]);
    setSyncHistory([]);
    setExportHistory([]);
    setError(null);
  });

  const reload = useCallback(async () => {
    if (!enabled) return;
    const scope = captureTenantFetchScope();
    setLoading(true);
    try {
      const [t, a, tr, c, sh, eh] = await Promise.all([
        api.getXeroMasterTotals(),
        api.getXeroAccounts({ limit: 50 }),
        api.getXeroTaxRates({ limit: 50 }),
        api.getXeroContactsList({ limit: 50 }),
        api.getXeroSyncHistory({ limit: 25 }),
        api.getXeroExportHistory({ limit: 25 }),
      ]);
      if (!isTenantFetchScopeCurrent(scope)) return;
      setTotals(t);
      setAccounts(a.items);
      setTaxRates(tr.items);
      setContacts(c.items);
      setSyncHistory(sh.items);
      setExportHistory(eh.items);
      setError(null);
    } catch (err) {
      if (!isTenantFetchScopeCurrent(scope)) return;
      setError(err instanceof Error ? err.message : "Failed to load Xero evidence");
    } finally {
      if (isTenantFetchScopeCurrent(scope)) setLoading(false);
    }
  }, [enabled]);

  useEffect(() => {
    void reload();
  }, [reload]);

  async function runReconcile() {
    setReconcileBusy(true);
    try {
      await api.reconcileXero();
      await reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Reconcile failed");
    } finally {
      setReconcileBusy(false);
    }
  }

  if (!enabled) return null;

  return (
    <div className="mt-4 border-t border-border pt-4" data-testid="xero-evidence-panel">
      <div className="flex flex-wrap gap-1 mb-3">
        {TABS.map((item) => (
          <Button
            key={item.id}
            size="sm"
            variant={tab === item.id ? "default" : "outline"}
            className="h-7 text-xs"
            onClick={() => setTab(item.id)}
          >
            {item.label}
          </Button>
        ))}
        <Button
          size="sm"
          variant="outline"
          className="h-7 text-xs ml-auto"
          disabled={loading}
          onClick={() => void reload()}
        >
          {loading ? "Refreshing…" : "Refresh proof"}
        </Button>
      </div>

      {error && <p className="text-xs text-destructive mb-2">{error}</p>}

      {tab === "overview" && (
        <div className="space-y-3 text-xs">
          <div className="grid sm:grid-cols-3 gap-2">
            <div className="rounded-md border border-border p-3">
              <p className="font-medium mb-1">Accounts stored</p>
              <p className="text-lg font-semibold">{totals?.accounts ?? "—"}</p>
            </div>
            <div className="rounded-md border border-border p-3">
              <p className="font-medium mb-1">Tax rates stored</p>
              <p className="text-lg font-semibold">{totals?.tax_rates ?? "—"}</p>
            </div>
            <div className="rounded-md border border-border p-3">
              <p className="font-medium mb-1">Contacts stored</p>
              <p className="text-lg font-semibold">{totals?.contacts ?? "—"}</p>
            </div>
          </div>
          <div className="flex gap-2">
            <Button size="sm" variant="outline" disabled={reconcileBusy} onClick={() => void runReconcile()}>
              {reconcileBusy ? "Reconciling…" : "Reconcile exported invoices"}
            </Button>
          </div>
          <p className="text-muted-foreground">
            Stored totals are committed database rows, not remote fetch counts alone.
          </p>
        </div>
      )}

      {tab === "accounts" && (
        <ul className="space-y-2 max-h-72 overflow-auto text-xs">
          {accounts.length === 0 && <li className="text-muted-foreground">No accounts stored yet.</li>}
          {accounts.map((row) => (
            <li key={row.id} className="rounded-md border border-border px-3 py-2">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-medium">{row.code || "—"}</span>
                <span>{row.name}</span>
                <ProvenanceBadge />
                <Badge variant="secondary">{row.sync_status}</Badge>
              </div>
              <p className="text-muted-foreground mt-1">
                Xero ID {row.xero_account_id}
                {row.last_synced_at ? ` · synced ${new Date(row.last_synced_at).toLocaleString()}` : ""}
              </p>
            </li>
          ))}
        </ul>
      )}

      {tab === "tax_rates" && (
        <ul className="space-y-2 max-h-72 overflow-auto text-xs">
          {taxRates.length === 0 && <li className="text-muted-foreground">No tax rates stored yet.</li>}
          {taxRates.map((row) => (
            <li key={row.id} className="rounded-md border border-border px-3 py-2">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-medium">{row.tax_type}</span>
                <span>{row.name}</span>
                <ProvenanceBadge />
                <Badge variant="secondary">{row.sync_status}</Badge>
              </div>
              <p className="text-muted-foreground mt-1">
                Rate {row.effective_rate ?? "—"}
                {row.last_synced_at ? ` · synced ${new Date(row.last_synced_at).toLocaleString()}` : ""}
              </p>
            </li>
          ))}
        </ul>
      )}

      {tab === "contacts" && (
        <ul className="space-y-2 max-h-72 overflow-auto text-xs">
          {contacts.length === 0 && <li className="text-muted-foreground">No contacts stored yet.</li>}
          {contacts.map((row) => (
            <li key={row.id} className="rounded-md border border-border px-3 py-2">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-medium">{row.name || row.xero_contact_id}</span>
                <ProvenanceBadge />
                <Badge variant="secondary">{row.mapping_status}</Badge>
                <Badge variant="outline">{row.sync_status}</Badge>
              </div>
              <p className="text-muted-foreground mt-1">
                Xero ID {row.xero_contact_id}
                {row.is_supplier ? " · supplier" : ""}
                {row.is_customer ? " · customer" : ""}
              </p>
            </li>
          ))}
        </ul>
      )}

      {tab === "sync_history" && (
        <ul className="space-y-2 max-h-72 overflow-auto text-xs">
          {syncHistory.length === 0 && <li className="text-muted-foreground">No sync jobs yet.</li>}
          {syncHistory.map((row) => (
            <li key={row.id} className="rounded-md border border-border px-3 py-2">
              <div className="flex flex-wrap gap-2 items-center">
                <span className="font-medium">#{row.id} {row.job_type}</span>
                <Badge variant="secondary">{row.status}</Badge>
                <span className="text-muted-foreground">{row.trigger_type || "manual"}</span>
              </div>
              <p className="text-muted-foreground mt-1">
                fetched {row.records_fetched} · created {row.records_created} · updated {row.records_updated} ·
                unchanged {row.records_unchanged} · failed {row.records_failed} · persisted {row.records_persisted}
              </p>
              {row.error_message && <p className="text-destructive mt-1">{row.error_message}</p>}
            </li>
          ))}
        </ul>
      )}

      {tab === "export_history" && (
        <ul className="space-y-2 max-h-72 overflow-auto text-xs">
          {exportHistory.length === 0 && <li className="text-muted-foreground">No exports yet.</li>}
          {exportHistory.map((row) => (
            <li key={row.id} className="rounded-md border border-border px-3 py-2">
              <div className="flex flex-wrap gap-2 items-center">
                <span className="font-medium">Invoice {row.invoice_id ?? "—"}</span>
                <Badge variant="outline">Exported to Xero</Badge>
                <Badge variant="secondary">{row.external_status || row.sync_status || "—"}</Badge>
              </div>
              <p className="text-muted-foreground mt-1">
                Xero {row.external_number || row.external_entity_id || "—"}
                {row.last_pushed_at ? ` · exported ${new Date(row.last_pushed_at).toLocaleString()}` : ""}
                {row.last_reconciled_at
                  ? ` · reconciled ${new Date(row.last_reconciled_at).toLocaleString()}`
                  : ""}
              </p>
              {row.sync_error_message && <p className="text-destructive mt-1">{row.sync_error_message}</p>}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export async function reloadXeroEvidenceCaches(): Promise<void> {
  // Lightweight helper for parent toast handlers to bust list caches via a fresh fetch.
  await Promise.all([
    api.getXeroMasterTotals(),
    api.getXeroAccounts({ limit: 1 }),
  ]);
}
