import { useMemo, useState } from "react";
import { CheckCircle2, Download, Upload } from "lucide-react";
import type { LedgerLinkExports } from "@/api/types";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/cn";
import { money } from "@/lib/format";
import { EXPORT_TARGETS } from "@/lib/v4MockData";
import { ExportStatusBadge } from "./ExportStatusBadge";
import { IntegrationBrandIcon } from "@/components/integrations/IntegrationBrandIcon";

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

export function JournalExportTab({
  exports,
  currency = "AUD",
}: {
  exports?: LedgerLinkExports;
  currency?: string;
}) {
  const [target, setTarget] = useState<string>("Xero");
  const [pushing, setPushing] = useState(false);
  const [progress, setProgress] = useState(0);
  const [history, setHistory] = useState<
    { id: string; ts: string; target: string; count: number; user: string; status: string }[]
  >([]);
  const fmt = (v: number) => money(v, currency);

  const rows = useMemo(() => flattenExports(exports), [exports]);
  const pending = rows.filter((r) => r.status === "Pending Export").length;
  const total = rows.reduce((s, r) => s + r.amount, 0);

  const downloadCsv = () => {
    const header = ["Group", "Document", "Date", "Party", "DebitAccount", "CreditAccount", "Amount", "Status"];
    const body = rows.map((r) =>
      [r.group, r.doc, r.date, `"${r.party}"`, `"${r.debit}"`, `"${r.credit}"`, r.amount.toFixed(2), r.status].join(",")
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

  const pushToTarget = () => {
    setPushing(true);
    setProgress(0);
    const timer = window.setInterval(() => {
      setProgress((p) => {
        if (p >= 100) {
          window.clearInterval(timer);
          setPushing(false);
          setHistory((h) => [
            {
              id: `ex-${Date.now()}`,
              ts: new Date().toISOString().slice(0, 16).replace("T", " "),
              target,
              count: pending,
              user: "Current user",
              status: "Success",
            },
            ...h,
          ]);
          return 100;
        }
        return p + 20;
      });
    }, 180);
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
              {rows.length} journal lines · {pending} pending
            </div>
            <div className="tnum font-semibold">Total {fmt(total)}</div>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2 mt-4">
          <Button size="sm" variant="outline" onClick={downloadCsv} data-testid="button-download-csv">
            <Download className="h-4 w-4 mr-1.5" /> Download CSV
          </Button>
          <Button size="sm" onClick={pushToTarget} disabled={pushing || rows.length === 0} data-testid="button-push">
            <Upload className="h-4 w-4 mr-1.5" />
            {pushing ? "Pushing…" : `Push to ${target}`}
          </Button>
          {pushing && (
            <div className="flex-1 min-w-[160px] flex items-center gap-2">
              <div className="flex-1 h-2 rounded-full bg-muted overflow-hidden">
                <div
                  className="h-full bg-primary transition-all"
                  style={{ width: `${progress}%` }}
                />
              </div>
              <span className="tnum text-xs text-muted-foreground w-9">{progress}%</span>
            </div>
          )}
          {!pushing && progress === 100 && (
            <span className="inline-flex items-center gap-1.5 text-xs text-primary">
              <CheckCircle2 className="h-3.5 w-3.5" /> Pushed to {target}
            </span>
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
                    <td className="px-3 py-2 text-right tnum">{fmt(row.amount)}</td>
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

      <Card className="overflow-hidden">
        <div className="px-4 py-2.5 border-b border-border text-sm font-medium">Export history</div>
        <div className="divide-y divide-border/60">
          {history.map((h) => (
            <div key={h.id} className="px-4 py-2.5 flex flex-wrap items-center gap-2 text-sm">
              <span className="tnum text-muted-foreground">{h.ts}</span>
              <span className="font-medium">{h.target}</span>
              <span className="text-muted-foreground">
                {h.count} lines · {h.user}
              </span>
              <Badge variant="outline" className="ml-auto text-[10px]">
                {h.status}
              </Badge>
            </div>
          ))}
        </div>
      </Card>
    </div>
  );
}
