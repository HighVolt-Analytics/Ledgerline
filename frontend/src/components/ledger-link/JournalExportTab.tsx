/**
 * Journal export tab: workbook preview + Xero Accounting Export Pipeline.
 * XeroEvidencePanel is the canonical pipeline UI; this tab mirrors its queue/export behaviour.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { AlertCircle, Download, RefreshCw, Upload } from "lucide-react";
import type {
  LedgerLinkExports,
  XeroExportHistoryRow,
  XeroExportLedgerRow,
  XeroExportQueueItem,
} from "@/api/types";
import { api } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/cn";
import { formatMoneyByCurrencyMap, money } from "@/lib/format";
import { EXPORT_TARGETS } from "@/lib/v4MockData";
import { ExportStatusBadge } from "./ExportStatusBadge";
import { IntegrationBrandIcon } from "@/components/integrations/IntegrationBrandIcon";
import { useResetOnTenantChange } from "@/hooks/useResetOnTenantChange";
import {
  captureTenantFetchScope,
  isTenantFetchScopeCurrent,
} from "@/lib/tenantSession";

const TARGET_BRANDS: Record<string, Parameters<typeof IntegrationBrandIcon>[0]["id"] | null> = {
  Xero: "xero",
  "QuickBooks Online": "qbo",
  MYOB: "myob",
  Stripe: "stripe",
};

type ExportPreviewRow = {
  id: string;
  group: string;
  doc: string;
  date: string;
  party: string;
  debit: string;
  credit: string;
  amount: number;
  status: string;
  currency?: string;
};

type LedgerExportGroupKey = Exclude<keyof LedgerLinkExports, "group_meta">;

const GROUPS: { key: LedgerExportGroupKey; label: string }[] = [
  { key: "invoices", label: "Invoices" },
  { key: "bills", label: "Bills" },
  { key: "expenses", label: "Expenses" },
  { key: "purchases", label: "Purchases" },
  { key: "payments", label: "Payments" },
];

function flattenExports(exports?: LedgerLinkExports): ExportPreviewRow[] {
  if (!exports) return [];
  return GROUPS.flatMap(({ key, label }) =>
    (exports[key] ?? []).map((row) => ({
      ...row,
      group: label,
    }))
  );
}

export function JournalExportTab({
  exports,
  currency = "",
}: {
  exports?: LedgerLinkExports;
  currency?: string;
}) {
  const [target, setTarget] = useState<string>("Xero");
  const [queue, setQueue] = useState<XeroExportQueueItem[]>([]);
  const [ledger, setLedger] = useState<XeroExportLedgerRow[]>([]);
  const [exportHistory, setExportHistory] = useState<XeroExportHistoryRow[]>([]);
  const [loadingQueue, setLoadingQueue] = useState(false);
  const [busyId, setBusyId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const fmtRow = (v: number, rowCurrency?: string | null) =>
    money(v, rowCurrency?.trim() ? rowCurrency : null);

  const rows = useMemo(() => flattenExports(exports), [exports]);
  const totalsByCurrency = useMemo(() => {
    const meta = exports?.group_meta;
    if (meta && Object.keys(meta).length > 0) {
      const out: Record<string, number> = {};
      for (const group of GROUPS) {
        const totals = meta[group.key]?.totals_by_currency ?? {};
        for (const [code, amount] of Object.entries(totals)) {
          out[code] = (out[code] ?? 0) + amount;
        }
      }
      return out;
    }
    const out: Record<string, number> = {};
    for (const row of rows) {
      const code = (row.currency || "").trim().toUpperCase() || "UNKNOWN";
      out[code] = (out[code] ?? 0) + row.amount;
    }
    return out;
  }, [exports, rows]);
  const exportCount = useMemo(() => {
    const meta = exports?.group_meta;
    if (meta && Object.keys(meta).length > 0) {
      return GROUPS.reduce((sum, group) => sum + (meta[group.key]?.count ?? 0), 0);
    }
    return rows.length;
  }, [exports, rows]);
  const totalLabel = useMemo(() => {
    const codes = Object.keys(totalsByCurrency);
    if (codes.length > 1) return formatMoneyByCurrencyMap(totalsByCurrency);
    const only = codes[0];
    const amount = Object.values(totalsByCurrency).reduce((sum, n) => sum + n, 0);
    return money(amount, only && only !== "UNKNOWN" ? only : currency);
  }, [totalsByCurrency, currency]);
  const isXeroTarget = target === "Xero";
  const pending = isXeroTarget ? queue.length : 0;
  const readyCount = queue.filter((item) => item.valid).length;

  useResetOnTenantChange(() => {
    setQueue([]);
    setLedger([]);
    setExportHistory([]);
    setError(null);
    setBusyId(null);
  });

  const refreshXeroEvidence = useCallback(async () => {
    if (!isXeroTarget) return;
    const scope = captureTenantFetchScope();
    setLoadingQueue(true);
    try {
      const [q, led, eh] = await Promise.all([
        api.getXeroExportQueue({ limit: 50 }),
        api.getXeroExportLedger({ limit: 50 }),
        api.getXeroExportHistory({ limit: 50 }),
      ]);
      if (!isTenantFetchScopeCurrent(scope)) return;
      setQueue(q.items);
      setLedger(led.items);
      setExportHistory(eh.items);
      setError(null);
    } catch (err) {
      if (!isTenantFetchScopeCurrent(scope)) return;
      setError(err instanceof Error ? err.message : "Failed to load Xero export queue");
    } finally {
      if (isTenantFetchScopeCurrent(scope)) setLoadingQueue(false);
    }
  }, [isXeroTarget]);

  useEffect(() => {
    if (!isXeroTarget) return;
    void refreshXeroEvidence();
  }, [isXeroTarget, refreshXeroEvidence]);

  const downloadCsv = () => {
    const header = [
      "Group",
      "Document",
      "Date",
      "Party",
      "DebitAccount",
      "CreditAccount",
      "Amount",
      "Currency",
      "Status",
    ];
    const body = rows.map((r) =>
      [
        r.group,
        r.doc,
        r.date,
        `"${r.party}"`,
        `"${r.debit}"`,
        `"${r.credit}"`,
        r.amount.toFixed(2),
        r.currency || "",
        r.status,
      ].join(",")
    );
    const blob = new Blob([[header.join(","), ...body].join("\n")], {
      type: "text/csv;charset=utf-8;",
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `ledgerline-journal-${target.toLowerCase().replace(/\s+/g, "-")}.csv`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  };

  const exportInvoice = async (invoiceId: number) => {
    setBusyId(invoiceId);
    setError(null);
    try {
      await api.exportXeroInvoice(invoiceId);
      await refreshXeroEvidence();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Export failed");
    } finally {
      setBusyId(null);
    }
  };

  const exportAllReady = async () => {
    const ready = queue.filter((item) => item.valid);
    if (ready.length === 0) return;
    setError(null);
    for (const item of ready) {
      setBusyId(item.invoice_id);
      try {
        await api.exportXeroInvoice(item.invoice_id);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Export failed");
        setBusyId(null);
        await refreshXeroEvidence();
        return;
      }
    }
    setBusyId(null);
    await refreshXeroEvidence();
  };

  return (
    <div className="space-y-4">
      <Card className="p-4">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <div className="text-[11px] text-muted-foreground uppercase tracking-wide mb-1.5">
              Target accounting system
            </div>
            <div className="flex flex-wrap gap-1.5">
              {EXPORT_TARGETS.map((t) => (
                <button
                  key={t}
                  type="button"
                  onClick={() => setTarget(t)}
                  data-testid={`target-${t}`}
                  className={cn(
                    "rounded-md border px-3 py-1.5 text-xs font-medium transition-colors",
                    target === t
                      ? "border-primary bg-primary/10 text-primary"
                      : "border-border bg-card text-muted-foreground hover-elevate"
                  )}
                >
                  <span className="inline-flex items-center gap-2">
                    {TARGET_BRANDS[t] ? (
                      <IntegrationBrandIcon id={TARGET_BRANDS[t]} size={14} />
                    ) : null}
                    <span>{t}</span>
                  </span>
                </button>
              ))}
            </div>
          </div>
          <div className="text-right text-sm">
            <div className="text-xs text-muted-foreground">
              {exportCount} journal lines
              {rows.length < exportCount ? ` · showing ${rows.length}` : ""}
              {isXeroTarget
                ? ` · ${pending} pending invoices · ${readyCount} ready`
                : ""}
            </div>
            <div className="tnum font-semibold">Total {totalLabel}</div>
          </div>
        </div>

        {!isXeroTarget && (
          <p className="text-xs text-muted-foreground mt-3">
            Live API export is available for Xero only. Other targets support CSV download.
          </p>
        )}

        {error && (
          <p
            className="text-xs text-destructive mt-3 inline-flex items-center gap-1.5"
            data-testid="journal-export-error"
          >
            <AlertCircle className="h-3.5 w-3.5 shrink-0" />
            {error}
          </p>
        )}

        <div className="flex flex-wrap items-center gap-2 mt-4">
          <Button size="sm" variant="outline" onClick={downloadCsv} data-testid="button-download-csv">
            <Download className="h-4 w-4 mr-1.5" /> Download CSV
          </Button>
          {isXeroTarget && (
            <>
              <Button
                size="sm"
                variant="outline"
                disabled={loadingQueue || busyId != null}
                onClick={() => void refreshXeroEvidence()}
                data-testid="button-refresh-queue"
              >
                <RefreshCw className="h-4 w-4 mr-1.5" />
                {loadingQueue ? "Refreshing…" : "Refresh queue"}
              </Button>
              <Button
                size="sm"
                onClick={() => void exportAllReady()}
                disabled={busyId != null || readyCount === 0}
                data-testid="button-export-xero"
              >
                <Upload className="h-4 w-4 mr-1.5" />
                {busyId != null ? "Exporting…" : `Export ready to Xero (${readyCount})`}
              </Button>
            </>
          )}
        </div>
      </Card>

      <Card className="overflow-hidden">
        <div className="px-4 py-2.5 border-b border-border text-sm font-medium">
          Journal export preview
        </div>
        <div className="overflow-x-auto max-h-80 overflow-y-auto">
          <table className="w-full text-sm">
            <thead className="sticky top-0 bg-card">
              <tr className="text-xs text-muted-foreground border-b border-border text-left">
                <th className="px-4 py-2 font-medium">Group</th>
                <th className="px-3 py-2 font-medium">Document</th>
                <th className="px-3 py-2 font-medium">Debit</th>
                <th className="px-3 py-2 font-medium">Credit</th>
                <th className="px-3 py-2 font-medium text-right">Amount</th>
                <th className="px-4 py-2 font-medium">Status</th>
              </tr>
            </thead>
            <tbody>
              {rows.length === 0 ? (
                <tr>
                  <td colSpan={6} className="px-4 py-8 text-center text-muted-foreground text-sm">
                    No journal lines ready for export yet.
                  </td>
                </tr>
              ) : (
                rows.map((row) => (
                  <tr key={row.id} className="row-band border-b border-border/60">
                    <td className="px-4 py-2 text-muted-foreground">{row.group}</td>
                    <td className="px-3 py-2 font-medium">{row.doc}</td>
                    <td className="px-3 py-2">{row.debit}</td>
                    <td className="px-3 py-2">{row.credit}</td>
                    <td className="px-3 py-2 text-right tnum">
                      {fmtRow(row.amount, row.currency)}
                    </td>
                    <td className="px-4 py-2">
                      <ExportStatusBadge status={row.status} />
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </Card>

      {isXeroTarget && (
        <Card className="overflow-hidden" data-testid="journal-xero-export-queue">
          <div className="px-4 py-2.5 border-b border-border text-sm font-medium">
            Xero export queue
          </div>
          <ul className="space-y-2 max-h-80 overflow-auto text-xs p-3" data-testid="xero-export-queue">
            {loadingQueue && queue.length === 0 && (
              <li className="text-muted-foreground">Loading export queue…</li>
            )}
            {!loadingQueue && queue.length === 0 && (
              <li className="text-muted-foreground">No eligible supplier invoices.</li>
            )}
            {queue.map((item) => (
              <li
                key={item.invoice_id}
                className="rounded-md border border-border px-3 py-2 space-y-2"
              >
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
        </Card>
      )}

      {isXeroTarget && (
        <Card className="overflow-hidden" data-testid="journal-xero-export-ledger">
          <div className="px-4 py-2.5 border-b border-border text-sm font-medium">
            Xero export evidence
          </div>
          <ul className="space-y-2 max-h-80 overflow-auto text-xs p-3" data-testid="xero-export-ledger">
            {ledger.length === 0 && (
              <li className="text-muted-foreground">No export evidence yet.</li>
            )}
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
              </li>
            ))}
          </ul>
        </Card>
      )}

      {isXeroTarget && (
        <Card className="overflow-hidden" data-testid="journal-xero-export-history">
          <div className="px-4 py-2.5 border-b border-border text-sm font-medium">
            Export history
          </div>
          <div className="divide-y divide-border/60">
            {exportHistory.length === 0 ? (
              <p className="px-4 py-3 text-sm text-muted-foreground">No export history yet.</p>
            ) : (
              exportHistory.map((h) => (
                <div
                  key={h.id}
                  className="px-4 py-2.5 flex flex-wrap items-center gap-2 text-sm"
                >
                  <span className="font-medium">Invoice {h.invoice_id ?? "—"}</span>
                  <span className="text-muted-foreground">
                    {h.external_number || h.external_entity_id || "—"} · {h.external_status || "—"}
                  </span>
                  <Badge variant="outline" className="ml-auto text-[10px]">
                    {h.sync_status || "—"}
                  </Badge>
                </div>
              ))
            )}
          </div>
        </Card>
      )}
    </div>
  );
}
