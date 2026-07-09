import { useState } from "react";
import { CheckCircle2, ChevronDown, ChevronRight, Scale } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { LedgerOverviewSkeleton } from "@/components/skeleton/PageSkeletons";
import { cn } from "@/lib/cn";
import { money } from "@/lib/format";
import type { ReconSummary } from "@/lib/reconciliation";

type LedgerOverviewProps = {
  recon: ReconSummary | null;
  loading?: boolean;
  currency?: string;
};

export function LedgerOverview({ recon, loading = false, currency = "SGD" }: LedgerOverviewProps) {
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const fmt = (v: number) => money(v, currency);

  if (loading) {
    return <LedgerOverviewSkeleton />;
  }

  if (!recon) {
    return (
      <Card className="p-6 text-sm text-muted-foreground">
        No processed journal entries yet. Post invoices through the pipeline to see reconciliation here.
      </Card>
    );
  }

  const docCount = recon.byDate.reduce((s, d) => s + d.count, 0);

  return (
    <div>
      <Card
        className={cn(
          "p-5 mb-6",
          recon.balanced
            ? "bg-[hsl(var(--chart-1)/0.06)] border-[hsl(var(--chart-1)/0.3)]"
            : "bg-destructive/5 border-destructive/30"
        )}
        data-testid="recon-banner"
      >
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            {recon.balanced ? (
              <CheckCircle2 className="h-8 w-8 text-[hsl(var(--chart-1))]" />
            ) : (
              <Scale className="h-8 w-8 text-destructive" />
            )}
            <div>
              <div className="text-base font-semibold">
                {recon.balanced ? "Ledger balanced" : "Out of balance"}
              </div>
              <div className="text-sm text-muted-foreground tnum">
                Δ (Dr − Cr) = {fmt(recon.deltaDrCr)}
              </div>
            </div>
          </div>
          <div className="flex gap-6 text-sm">
            <div className="text-right">
              <div className="text-xs text-muted-foreground">Total debits</div>
              <div className="tnum font-semibold">{fmt(recon.sumDr)}</div>
            </div>
            <div className="text-right">
              <div className="text-xs text-muted-foreground">Total credits</div>
              <div className="tnum font-semibold">{fmt(recon.sumCr)}</div>
            </div>
            <div className="text-right">
              <div className="text-xs text-muted-foreground">Documents</div>
              <div className="tnum font-semibold">{docCount}</div>
            </div>
          </div>
        </div>
      </Card>

      <div className="space-y-3">
        {recon.byDate.map((day) => {
          const open = expanded[day.date] ?? false;
          return (
            <Card key={day.date} className="overflow-hidden" data-testid={`recon-date-${day.date}`}>
              <button
                type="button"
                onClick={() => setExpanded((e) => ({ ...e, [day.date]: !open }))}
                className="w-full flex items-center gap-3 px-4 py-3 hover-elevate text-left"
                data-testid={`recon-toggle-${day.date}`}
              >
                {open ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
                <span className="font-medium tnum">{day.date}</span>
                <Badge variant="outline" className="tnum">
                  {day.count} docs
                </Badge>
                <div className="flex-1" />
                <span className="text-sm text-muted-foreground tnum hidden sm:inline">
                  Dr {fmt(day.sumDr)} · Cr {fmt(day.sumCr)}
                </span>
                <Badge
                  variant="outline"
                  className={
                    day.delta === 0
                      ? "text-[hsl(var(--chart-1))] border-[hsl(var(--chart-1)/0.4)]"
                      : "border-destructive/40 text-destructive"
                  }
                >
                  Δ {fmt(day.delta)}
                </Badge>
              </button>

              {open && (
                <div className="border-t border-border px-4 py-3 space-y-4">
                  {day.invoices.map((inv) => (
                    <div key={inv.id}>
                      <div className="flex items-center gap-2 mb-1.5 text-sm">
                        <span className="font-medium">{inv.id}</span>
                        <span className="text-muted-foreground">{inv.vendor}</span>
                        <span className="tnum text-muted-foreground ml-auto">{fmt(inv.total)}</span>
                      </div>
                      <div className="overflow-x-auto rounded-md border border-border">
                        <table className="w-full text-sm">
                          <thead>
                            <tr className="text-xs text-muted-foreground bg-muted/50 text-left">
                              <th className="px-3 py-1.5 font-medium">Account</th>
                              <th className="px-3 py-1.5 font-medium text-right">Debit</th>
                              <th className="px-3 py-1.5 font-medium text-right">Credit</th>
                            </tr>
                          </thead>
                          <tbody>
                            {inv.postings.map((row, idx) => (
                              <tr key={idx} className="border-t border-border/60">
                                <td className="px-3 py-1.5">{row.account}</td>
                                <td className="px-3 py-1.5 text-right tnum">
                                  {row.debit ? fmt(row.debit) : "—"}
                                </td>
                                <td className="px-3 py-1.5 text-right tnum">
                                  {row.credit ? fmt(row.credit) : "—"}
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </Card>
          );
        })}
      </div>

      <p className="text-xs text-muted-foreground mt-4">
        Postings: each line subtotal debits its GL account, total GST debits the tax account, and the
        document total credits Accounts Payable.
      </p>
    </div>
  );
}
