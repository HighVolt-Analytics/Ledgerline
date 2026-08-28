/**
 * Journal export: workbook preview + Xero export actions.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { AlertCircle, Download, RefreshCw, Upload } from "lucide-react";
import type { LedgerLinkExports, XeroExportQueueItem } from "@/api/types";
import { api } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { formatMoneyByCurrencyMap, money } from "@/lib/format";
import { ExportStatusBadge } from "./ExportStatusBadge";
import { IntegrationBrandIcon } from "@/components/integrations/IntegrationBrandIcon";
import { useResetOnTenantChange } from "@/hooks/useResetOnTenantChange";
import {
  captureTenantFetchScope,
  isTenantFetchScopeCurrent,
} from "@/lib/tenantSession";

const NOT_READY_MESSAGE = "Xero integration is not ready";

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
  const [queue, setQueue] = useState<XeroExportQueueItem[]>([]);
  const [loadingQueue, setLoadingQueue] = useState(false);
  const [busyId, setBusyId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [xeroReady, setXeroReady] = useState<boolean | null>(null);
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
  const pending = queue.length;
  const readyCount = queue.filter((item) => item.valid).length;
  const statusLine = error ?? (xeroReady === false ? NOT_READY_MESSAGE : null);

  useResetOnTenantChange(() => {
    setQueue([]);
    setError(null);
    setXeroReady(null);
    setBusyId(null);
  });

  const refreshXeroEvidence = useCallback(async () => {
    const scope = captureTenantFetchScope();
    setLoadingQueue(true);
    try {
      const [q, readiness] = await Promise.all([
        api.getXeroExportQueue({ limit: 50 }),
        api.getXeroReadiness(),
      ]);
      if (!isTenantFetchScopeCurrent(scope)) return;
      setQueue(q.items);
      setXeroReady(readiness.ready === true);
      setError(null);
    } catch (err) {
      if (!isTenantFetchScopeCurrent(scope)) return;
      setError(err instanceof Error ? err.message : "Failed to load Xero export queue");
    } finally {
      if (isTenantFetchScopeCurrent(scope)) setLoadingQueue(false);
    }
  }, []);

  useEffect(() => {
    void refreshXeroEvidence();
  }, [refreshXeroEvidence]);

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
    a.download = "ledgerline-journal-xero.csv";
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
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
    <Card className="overflow-hidden">
      <div className="px-4 py-2.5 space-y-1.5">
        <div className="flex items-center justify-between gap-3">
          <div className="text-[11px] text-muted-foreground uppercase tracking-wide">
            Target accounting system
          </div>
          <span
            className="inline-flex items-center gap-2 rounded-md border border-primary bg-primary/10 px-2.5 py-1 text-xs font-medium text-primary"
            data-testid="target-Xero"
          >
            <IntegrationBrandIcon id="xero" size={14} />
            Xero
          </span>
        </div>

        <div className="flex items-center justify-between gap-3 min-h-[1rem]">
          <div className="text-xs leading-none text-muted-foreground">
            {exportCount} journal lines
            {rows.length < exportCount ? ` · showing ${rows.length}` : ""}
            {` · ${pending} pending invoices · ${readyCount} ready`}
          </div>
          {statusLine ? (
            <p
              className="m-0 flex items-center justify-end gap-1.5 text-xs leading-none text-destructive"
              data-testid="journal-export-error"
            >
              <AlertCircle className="h-3.5 w-3.5 shrink-0" />
              {statusLine}
            </p>
          ) : null}
        </div>

        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex flex-wrap items-center gap-2">
            <Button size="sm" variant="outline" onClick={downloadCsv} data-testid="button-download-csv">
              <Download className="h-4 w-4 mr-1.5" /> Download CSV
            </Button>
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
          </div>
          <div className="tnum text-sm font-semibold ml-auto">Total {totalLabel}</div>
        </div>
      </div>

      <div className="border-t border-border">
        <div className="px-4 py-2.5 text-sm font-medium">Journal export preview</div>
        <div className="overflow-x-auto max-h-80 overflow-y-auto">
          <table className="w-full text-sm">
            <thead className="sticky top-0 bg-card">
              <tr className="text-xs text-muted-foreground border-y border-border">
                <th className="px-4 py-2 font-medium text-left">Group</th>
                <th className="px-3 py-2 font-medium text-left">Document</th>
                <th className="px-3 py-2 font-medium text-left">Debit</th>
                <th className="px-3 py-2 font-medium text-left">Credit</th>
                <th className="px-3 py-2 font-medium text-left">Status</th>
                <th className="px-4 py-2 font-medium text-right whitespace-nowrap" align="right">
                  Amount
                </th>
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
                    <td className="px-4 py-2 text-muted-foreground text-left">{row.group}</td>
                    <td className="px-3 py-2 font-medium text-left">{row.doc}</td>
                    <td className="px-3 py-2 text-left">{row.debit}</td>
                    <td className="px-3 py-2 text-left">{row.credit}</td>
                    <td className="px-3 py-2 text-left">
                      <ExportStatusBadge status={row.status} />
                    </td>
                    <td className="px-4 py-2 text-right tnum whitespace-nowrap" align="right">
                      {fmtRow(row.amount, row.currency)}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </Card>
  );
}
