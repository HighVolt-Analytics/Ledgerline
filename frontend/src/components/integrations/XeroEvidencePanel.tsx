/**
 * Xero integration evidence: synced lists, export queue, ledger.
 */
import { useCallback, useEffect, useState } from "react";
import { api } from "@/api/client";
import type {
  XeroAccountRow,
  XeroContactRow,
  XeroExportHistoryRow,
  XeroExportLedgerRow,
  XeroExportQueueItem,
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

type TabId =
  | "overview"
  | "accounts"
  | "tax_rates"
  | "contacts"
  | "export_queue"
  | "export_ledger"
  | "sync_history"
  | "export_history";

const TABS: { id: TabId; label: string }[] = [
  { id: "overview", label: "Overview" },
  { id: "accounts", label: "Accounts" },
  { id: "tax_rates", label: "Tax rates" },
  { id: "contacts", label: "Contacts" },
  { id: "export_queue", label: "Export queue" },
  { id: "export_ledger", label: "Export evidence" },
  { id: "sync_history", label: "Sync history" },
  { id: "export_history", label: "Legacy history" },
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
  const [queue, setQueue] = useState<XeroExportQueueItem[]>([]);
  const [ledger, setLedger] = useState<XeroExportLedgerRow[]>([]);
  const [syncHistory, setSyncHistory] = useState<XeroSyncHistoryRow[]>([]);
  const [exportHistory, setExportHistory] = useState<XeroExportHistoryRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<number | null>(null);

  useResetOnTenantChange(() => {
    setTotals(null);
    setAccounts([]);
    setTaxRates([]);
    setContacts([]);
    setQueue([]);
    setLedger([]);
    setSyncHistory([]);
    setExportHistory([]);
    setError(null);
  });

  const reload = useCallback(async () => {
    if (!enabled) return;
    const scope = captureTenantFetchScope();
    setLoading(true);
    try {
      const [t, a, tr, c, q, led, sh, eh] = await Promise.all([
        api.getXeroMasterTotals(),
        api.getXeroAccounts({ limit: 50 }),
        api.getXeroTaxRates({ limit: 50 }),
        api.getXeroContactsList({ limit: 50 }),
        api.getXeroExportQueue({ limit: 25 }),
        api.getXeroExportLedger({ limit: 25 }),
        api.getXeroSyncHistory({ limit: 25 }),
        api.getXeroExportHistory({ limit: 25 }),
      ]);
      if (!isTenantFetchScopeCurrent(scope)) return;
      setTotals(t);
      setAccounts(a.items);
      setTaxRates(tr.items);
      setContacts(c.items);
      setQueue(q.items);
      setLedger(led.items);
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

  async function exportInvoice(invoiceId: number) {
    setBusyId(invoiceId);
    setError(null);
    try {
      await api.exportXeroInvoice(invoiceId);
      await reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Export failed");
    } finally {
      setBusyId(null);
    }
  }

  async function refreshExport(syncId: number) {
    setBusyId(syncId);
    try {
      await api.refreshXeroExport(syncId);
      await reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Refresh failed");
    } finally {
      setBusyId(null);
    }
  }

  async function retryAttachment(syncId: number) {
    setBusyId(syncId);
    try {
      await api.retryXeroAttachment(syncId);
      await reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Attachment retry failed");
    } finally {
      setBusyId(null);
    }
  }

  async function runReconcile() {
    setBusyId(-1);
    try {
      await api.runXeroReconciliation();
      await reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Reconciliation failed");
    } finally {
      setBusyId(null);
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

      {error && (
        <p className="text-xs text-destructive mb-2" data-testid="xero-structured-error">
          {error}
        </p>
      )}

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
            <Button size="sm" variant="outline" disabled={busyId === -1} onClick={() => void runReconcile()}>
              {busyId === -1 ? "Reconciling…" : "Run reconciliation"}
            </Button>
          </div>
          <p className="text-muted-foreground">
            Counts are committed database rows. Export evidence requires ACCPAY Draft + PDF attachment.
          </p>
        </div>
      )}

      {tab === "accounts" && (
        <ul className="space-y-2 max-h-72 overflow-auto text-xs" data-testid="xero-accounts-list">
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
                External ID {row.xero_account_id}
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
              </div>
              <p className="text-muted-foreground mt-1">External ID {row.xero_contact_id}</p>
            </li>
          ))}
        </ul>
      )}

      {tab === "export_queue" && (
        <ul className="space-y-2 max-h-80 overflow-auto text-xs" data-testid="xero-export-queue">
          {queue.length === 0 && <li className="text-muted-foreground">No eligible supplier invoices.</li>}
          {queue.map((item) => (
            <li key={item.invoice_id} className="rounded-md border border-border px-3 py-2 space-y-2">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-medium">#{item.invoice_id}</span>
                <span>{item.invoice_no || "—"}</span>
                <span>{item.vendor}</span>
                <Badge variant={item.valid ? "secondary" : "destructive"}>
                  {item.valid ? "Ready" : "Blocked"}
                </Badge>
              </div>
              {!item.valid && (
                <ul className="text-destructive space-y-1" data-testid="xero-blocking-errors">
                  {item.blocking_errors.map((err) => (
                    <li key={`${err.code}:${err.message}`}>{err.message}</li>
                  ))}
                </ul>
              )}
              <Button
                size="sm"
                disabled={!item.valid || busyId === item.invoice_id}
                onClick={() => void exportInvoice(item.invoice_id)}
                data-testid="xero-export-action"
              >
                {busyId === item.invoice_id ? "Exporting…" : "Export to Xero"}
              </Button>
            </li>
          ))}
        </ul>
      )}

      {tab === "export_ledger" && (
        <ul className="space-y-2 max-h-80 overflow-auto text-xs" data-testid="xero-export-ledger">
          {ledger.length === 0 && <li className="text-muted-foreground">No export evidence yet.</li>}
          {ledger.map((row) => (
            <li key={row.sync_id} className="rounded-md border border-border px-3 py-2 space-y-1">
              <div className="flex flex-wrap gap-2 items-center">
                <span className="font-medium">Invoice #{row.source_invoice_id}</span>
                <Badge variant="outline">{row.status}</Badge>
                <span data-testid="xero-attachment-status">
                  <Badge variant="secondary">PDF: {row.attachment_status || "—"}</Badge>
                </span>
              </div>
              <p className="text-muted-foreground">
                Xero {row.external_number || "—"} · ID {row.external_id || "—"} · status{" "}
                {row.external_status || "—"} · amount {row.external_total ?? "—"} · attempts{" "}
                {row.attempt_count}
              </p>
              {row.error_message && (
                <p className="text-destructive">
                  [{row.error_bucket}/{row.error_code}] {row.error_message}
                </p>
              )}
              <div className="flex gap-2">
                <Button
                  size="sm"
                  variant="outline"
                  disabled={busyId === row.sync_id}
                  onClick={() => void refreshExport(row.sync_id)}
                >
                  Refresh status
                </Button>
                {row.attachment_status !== "success" && row.external_id && (
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={busyId === row.sync_id}
                    onClick={() => void retryAttachment(row.sync_id)}
                  >
                    Retry attachment
                  </Button>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}

      {tab === "sync_history" && (
        <ul className="space-y-2 max-h-72 overflow-auto text-xs">
          {syncHistory.length === 0 && <li className="text-muted-foreground">No sync jobs yet.</li>}
          {syncHistory.map((row) => (
            <li key={row.id} className="rounded-md border border-border px-3 py-2">
              <span className="font-medium">{row.job_type}</span> · {row.status} · fetched{" "}
              {row.records_fetched} / created {row.records_created} / updated {row.records_updated} /
              unchanged {row.records_unchanged} / failed {row.records_failed}
            </li>
          ))}
        </ul>
      )}

      {tab === "export_history" && (
        <ul className="space-y-2 max-h-72 overflow-auto text-xs">
          {exportHistory.length === 0 && <li className="text-muted-foreground">No legacy export refs.</li>}
          {exportHistory.map((row) => (
            <li key={row.id} className="rounded-md border border-border px-3 py-2">
              Invoice {row.invoice_id} · {row.external_number} · {row.external_status} ·{" "}
              {row.sync_status}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export async function reloadXeroEvidenceCaches(): Promise<void> {
  await Promise.all([
    api.getXeroMasterTotals(),
    api.getXeroAccounts({ limit: 50 }),
    api.getXeroTaxRates({ limit: 50 }),
    api.getXeroContactsList({ limit: 50 }),
    api.getXeroExportLedger({ limit: 25 }),
  ]);
}
