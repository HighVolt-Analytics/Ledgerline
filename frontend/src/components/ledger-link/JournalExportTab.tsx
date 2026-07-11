import { useCallback, useMemo, useState } from "react";
import { AlertCircle, CheckCircle2, Download, RefreshCw, Upload } from "lucide-react";
import type { LedgerLinkExports } from "@/api/types";
import { api } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/cn";
import { money } from "@/lib/format";
import { EXPORT_TARGETS } from "@/lib/v4MockData";
import { ExportStatusBadge } from "./ExportStatusBadge";
import { IntegrationBrandIcon } from "@/components/integrations/IntegrationBrandIcon";
import { parseLedgerLinkInvoiceId } from "@/hooks/useAccountingIntegrations";

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
};

type RowPushState = "idle" | "sending" | "sent" | "failed" | "skipped";

type PushHistoryEntry = {
  id: string;
  ts: string;
  target: string;
  count: number;
  failed: number;
  status: string;
};

const GROUPS: { key: keyof LedgerLinkExports; label: string }[] = [
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

function displayRowStatus(baseStatus: string, pushState: RowPushState, pushDetail?: string): string {
  if (pushState === "sending") return "Sending to Xero";
  if (pushState === "sent") return pushDetail || "Pushed to Xero";
  if (pushState === "failed") return pushDetail || "Push failed";
  if (pushState === "skipped") return pushDetail || "Skipped";
  return baseStatus;
}

export function JournalExportTab({
  exports,
  currency = "SGD",
}: {
  exports?: LedgerLinkExports;
  currency?: string;
}) {
  const [target, setTarget] = useState<string>("Xero");
  const [pushing, setPushing] = useState(false);
  const [pushError, setPushError] = useState<string | null>(null);
  const [rowPushStates, setRowPushStates] = useState<Record<string, RowPushState>>({});
  const [rowPushDetails, setRowPushDetails] = useState<Record<string, string>>({});
  const [history, setHistory] = useState<PushHistoryEntry[]>([]);
  const fmt = (v: number) => money(v, currency);

  const rows = useMemo(() => flattenExports(exports), [exports]);
  const pendingRows = useMemo(
    () => rows.filter((r) => r.status === "Pending Export" && parseLedgerLinkInvoiceId(r.id) != null),
    [rows]
  );
  const pending = pendingRows.length;
  const total = rows.reduce((s, r) => s + r.amount, 0);
  const isXeroTarget = target === "Xero";

  const downloadCsv = () => {
    const header = ["Group", "Document", "Date", "Party", "DebitAccount", "CreditAccount", "Amount", "Status"];
    const body = rows.map((r) =>
      [
        r.group,
        r.doc,
        r.date,
        `"${r.party}"`,
        `"${r.debit}"`,
        `"${r.credit}"`,
        r.amount.toFixed(2),
        displayRowStatus(r.status, rowPushStates[r.id] ?? "idle", rowPushDetails[r.id]),
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

  const pushInvoiceRow = useCallback(async (row: ExportPreviewRow) => {
    const invoiceId = parseLedgerLinkInvoiceId(row.id);
    if (invoiceId == null) {
      setRowPushStates((prev) => ({ ...prev, [row.id]: "skipped" }));
      setRowPushDetails((prev) => ({
        ...prev,
        [row.id]: "Only invoice rows can be pushed to Xero",
      }));
      return { ok: false as const, skipped: true, detail: "Only invoice rows can be pushed to Xero" };
    }

    const applyOutcome = (
      state: RowPushState,
      detail: string,
      ok: boolean,
      skipped: boolean
    ) => {
      setRowPushStates((prev) => {
        const next = { ...prev };
        for (const candidate of rows) {
          if (parseLedgerLinkInvoiceId(candidate.id) === invoiceId) {
            next[candidate.id] = state;
          }
        }
        return next;
      });
      setRowPushDetails((prev) => {
        const next = { ...prev };
        for (const candidate of rows) {
          if (parseLedgerLinkInvoiceId(candidate.id) === invoiceId) {
            next[candidate.id] = detail;
          }
        }
        return next;
      });
      return { ok, skipped, detail };
    };

    setRowPushStates((prev) => {
      const next = { ...prev };
      for (const candidate of rows) {
        if (parseLedgerLinkInvoiceId(candidate.id) === invoiceId) {
          next[candidate.id] = "sending";
        }
      }
      return next;
    });

    try {
      const result = await api.pushXeroInvoice(invoiceId);
      if (result.skipped) {
        return applyOutcome(
          "skipped",
          result.reason || "Skipped by server",
          false,
          true
        );
      }
      const label =
        result.external_number != null
          ? `Pushed to Xero · ${result.external_number}`
          : result.external_status
            ? `Pushed to Xero · ${result.external_status}`
            : "Pushed to Xero";
      return applyOutcome("sent", label, true, false);
    } catch (err) {
      const message = err instanceof Error ? err.message : "Push failed";
      return applyOutcome("failed", message, false, false);
    }
  }, [rows]);

  const pushToTarget = async () => {
    if (!isXeroTarget) return;
    if (pendingRows.length === 0) return;

    setPushing(true);
    setPushError(null);

    const uniqueByInvoice = new Map<number, ExportPreviewRow>();
    for (const row of pendingRows) {
      const invoiceId = parseLedgerLinkInvoiceId(row.id);
      if (invoiceId != null && !uniqueByInvoice.has(invoiceId)) {
        uniqueByInvoice.set(invoiceId, row);
      }
    }

    let sent = 0;
    let failed = 0;
    let skipped = 0;

    for (const row of uniqueByInvoice.values()) {
      const outcome = await pushInvoiceRow(row);
      if (outcome.skipped) skipped += 1;
      else if (outcome.ok) sent += 1;
      else failed += 1;
    }

    setPushing(false);

    const status =
      failed > 0 ? "Partial failure" : sent > 0 ? "Success" : skipped > 0 ? "Skipped" : "No changes";

    setHistory((h) => [
      {
        id: `ex-${Date.now()}`,
        ts: new Date().toISOString().slice(0, 16).replace("T", " "),
        target,
        count: sent,
        failed,
        status,
      },
      ...h,
    ]);

    if (failed > 0) {
      setPushError(`${failed} invoice${failed === 1 ? "" : "s"} failed to push. Retry failed rows below.`);
    }
  };

  const retryRow = async (row: ExportPreviewRow) => {
    if (!isXeroTarget) return;
    setPushError(null);
    await pushInvoiceRow(row);
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
              {rows.length} journal lines · {pending} pending invoices
            </div>
            <div className="tnum font-semibold">Total {fmt(total)}</div>
          </div>
        </div>

        {!isXeroTarget && (
          <p className="text-xs text-muted-foreground mt-3">
            Live API push is available for Xero only. Other targets support CSV download.
          </p>
        )}

        {pushError && (
          <p className="text-xs text-destructive mt-3 inline-flex items-center gap-1.5">
            <AlertCircle className="h-3.5 w-3.5 shrink-0" />
            {pushError}
          </p>
        )}

        <div className="flex flex-wrap items-center gap-2 mt-4">
          <Button size="sm" variant="outline" onClick={downloadCsv} data-testid="button-download-csv">
            <Download className="h-4 w-4 mr-1.5" /> Download CSV
          </Button>
          <Button
            size="sm"
            onClick={() => void pushToTarget()}
            disabled={pushing || pending === 0 || !isXeroTarget}
            data-testid="button-push"
          >
            <Upload className="h-4 w-4 mr-1.5" />
            {pushing ? "Pushing to Xero…" : `Push to ${target}`}
          </Button>
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
                <th className="px-4 py-2 font-medium w-20" />
              </tr>
            </thead>
            <tbody>
              {rows.length === 0 ? (
                <tr>
                  <td colSpan={7} className="px-4 py-8 text-center text-muted-foreground text-sm">
                    No journal lines ready for export yet.
                  </td>
                </tr>
              ) : (
                rows.map((row) => {
                  const pushState = rowPushStates[row.id] ?? "idle";
                  const displayStatus = displayRowStatus(
                    row.status,
                    pushState,
                    rowPushDetails[row.id]
                  );
                  return (
                    <tr key={row.id} className="row-band border-b border-border/60">
                      <td className="px-4 py-2 text-muted-foreground">{row.group}</td>
                      <td className="px-3 py-2 font-medium">{row.doc}</td>
                      <td className="px-3 py-2">{row.debit}</td>
                      <td className="px-3 py-2">{row.credit}</td>
                      <td className="px-3 py-2 text-right tnum">{fmt(row.amount)}</td>
                      <td className="px-4 py-2">
                        <ExportStatusBadge status={displayStatus} />
                      </td>
                      <td className="px-4 py-2">
                        {isXeroTarget && pushState === "failed" && (
                          <Button
                            size="sm"
                            variant="ghost"
                            className="h-7 text-xs"
                            onClick={() => void retryRow(row)}
                          >
                            <RefreshCw className="h-3 w-3 mr-1" />
                            Retry
                          </Button>
                        )}
                        {pushState === "sent" && (
                          <CheckCircle2 className="h-4 w-4 text-primary" aria-label="Sent" />
                        )}
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </Card>

      <Card className="overflow-hidden">
        <div className="px-4 py-2.5 border-b border-border text-sm font-medium">Export history</div>
        <div className="divide-y divide-border/60">
          {history.length === 0 ? (
            <p className="px-4 py-3 text-sm text-muted-foreground">No pushes yet.</p>
          ) : (
            history.map((h) => (
              <div key={h.id} className="px-4 py-2.5 flex flex-wrap items-center gap-2 text-sm">
                <span className="tnum text-muted-foreground">{h.ts}</span>
                <span className="font-medium">{h.target}</span>
                <span className="text-muted-foreground">
                  {h.count} sent
                  {h.failed > 0 ? ` · ${h.failed} failed` : ""}
                </span>
                <Badge
                  variant="outline"
                  className={cn(
                    "ml-auto text-[10px]",
                    h.status === "Partial failure" && "border-destructive/40 text-destructive"
                  )}
                >
                  {h.status}
                </Badge>
              </div>
            ))
          )}
        </div>
      </Card>
    </div>
  );
}
