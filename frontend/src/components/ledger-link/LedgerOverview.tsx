import { useState } from "react";
import { CheckCircle2, ChevronDown, ChevronRight, Eye, Scale } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { LedgerOverviewSkeleton } from "@/components/skeleton/PageSkeletons";
import { useLedgerLinkDay } from "@/hooks/useLedgerLink";
import { cn } from "@/lib/cn";
import { formatMoneyByCurrencyMap, money } from "@/lib/format";
import { documentCountForRecon, mapReconDay, type ReconDay, type ReconSummary } from "@/lib/reconciliation";

type LedgerOverviewProps = {
  recon: ReconSummary | null;
  loading?: boolean;
  currency?: string;
  onViewInvoice?: (invoiceId: number) => void;
};

export function LedgerOverview({
  recon,
  loading = false,
  currency = "",
  onViewInvoice,
}: LedgerOverviewProps) {
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const fmtBase = (v: number) => money(v, currency);
  const fmtRow = (v: number, rowCurrency?: string | null) =>
    money(v, rowCurrency?.trim() ? rowCurrency : null);
  const fmtMap = (totals: Record<string, number>) => formatMoneyByCurrencyMap(totals);

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

  const docCount = documentCountForRecon(recon);
  const totalDays = recon.totalDayCount ?? recon.byDate.length;

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
                {recon.hasMixedCurrencies
                  ? "Mixed currencies — totals shown by currency"
                  : `Δ (Dr − Cr) = ${fmtBase(recon.deltaDrCr)}`}
              </div>
              <div className="text-xs text-muted-foreground mt-1">
                Base currency totals ({currency})
              </div>
            </div>
          </div>
          <div className="flex gap-6 text-sm">
            <div className="text-right">
              <div className="text-xs text-muted-foreground">Total debits</div>
              <div className="tnum font-semibold">
                {recon.hasMixedCurrencies ? fmtMap(recon.drByCurrency) : fmtBase(recon.sumDr)}
              </div>
            </div>
            <div className="text-right">
              <div className="text-xs text-muted-foreground">Total credits</div>
              <div className="tnum font-semibold">
                {recon.hasMixedCurrencies ? fmtMap(recon.crByCurrency) : fmtBase(recon.sumCr)}
              </div>
            </div>
            <div className="text-right">
              <div className="text-xs text-muted-foreground">Documents</div>
              <div className="tnum font-semibold">{docCount}</div>
            </div>
          </div>
        </div>
        {recon.hasMixedCurrencies ? (
          <div
            className="mt-3 rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs text-amber-700 dark:text-amber-300"
            data-testid="ledger-mixed-currency-warning"
          >
            Mixed currencies detected. Document amounts stay in source currency until payment
            conversion.
          </div>
        ) : null}
      </Card>

      <div className="space-y-3">
        {recon.byDate.map((day) => (
          <LedgerOverviewDay
            key={day.date}
            day={day}
            open={expanded[day.date] ?? false}
            onToggle={() => setExpanded((e) => ({ ...e, [day.date]: !e[day.date] }))}
            currency={currency}
            fmtRow={fmtRow}
            fmtMap={fmtMap}
            onViewInvoice={onViewInvoice}
          />
        ))}
      </div>

      {totalDays > recon.byDate.length ? (
        <p className="text-xs text-muted-foreground mt-3">
          Showing {recon.byDate.length} of {totalDays} posting days (most recent).
        </p>
      ) : null}

      <p className="text-xs text-muted-foreground mt-4">
        Postings: each line subtotal debits its GL account, total GST debits the tax account, and the
        document total credits Accounts Payable. Source currency is kept until payment conversion.
      </p>
    </div>
  );
}

function LedgerOverviewDay({
  day,
  open,
  onToggle,
  currency,
  fmtRow,
  fmtMap,
  onViewInvoice,
}: {
  day: ReconDay;
  open: boolean;
  onToggle: () => void;
  currency: string;
  fmtRow: (v: number, rowCurrency?: string | null) => string;
  fmtMap: (totals: Record<string, number>) => string;
  onViewInvoice?: (invoiceId: number) => void;
}) {
  const needsFetch = open && day.invoices.length === 0 && day.count > 0;
  const { data, isLoading } = useLedgerLinkDay(day.date, needsFetch);
  const invoices = data ? mapReconDay(data).invoices : day.invoices;

  return (
    <Card className="overflow-hidden" data-testid={`recon-date-${day.date}`}>
      <button
        type="button"
        onClick={onToggle}
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
          {day.hasMixedCurrencies
            ? `Dr ${fmtMap(day.drByCurrency)} · Cr ${fmtMap(day.crByCurrency)}`
            : `Dr ${fmtRow(day.sumDr, day.currencies[0] || currency)} · Cr ${fmtRow(day.sumCr, day.currencies[0] || currency)}`}
        </span>
        {day.hasMixedCurrencies ? (
          <Badge
            variant="outline"
            className="border-amber-500/40 text-amber-700 dark:text-amber-300"
          >
            Mixed FX
          </Badge>
        ) : (
          <Badge
            variant="outline"
            className={
              day.delta === 0
                ? "text-[hsl(var(--chart-1))] border-[hsl(var(--chart-1)/0.4)]"
                : "border-destructive/40 text-destructive"
            }
          >
            Δ {fmtRow(day.delta, day.currencies[0] || currency)}
          </Badge>
        )}
      </button>

      {open && (
        <div className="border-t border-border px-4 py-3 space-y-4">
          {isLoading && invoices.length === 0 ? (
            <p className="text-sm text-muted-foreground">Loading postings…</p>
          ) : (
            invoices.map((inv) => (
              <div key={inv.invoiceId ?? inv.id}>
                <div className="flex items-center gap-2 mb-1.5 text-sm">
                  <span className="font-medium">{inv.id}</span>
                  <span className="text-muted-foreground">{inv.vendor}</span>
                  {inv.currency ? (
                    <Badge variant="outline" className="tnum text-[10px]">
                      {inv.currency}
                    </Badge>
                  ) : null}
                  {onViewInvoice && inv.invoiceId != null ? (
                    <Button
                      type="button"
                      size="sm"
                      variant="outline"
                      className="h-7 gap-1.5 px-2 text-xs"
                      onClick={() => onViewInvoice(inv.invoiceId!)}
                      data-testid={`ledger-view-invoice-${inv.invoiceId}`}
                      aria-label={`View document ${inv.id}`}
                    >
                      <Eye className="h-3.5 w-3.5" />
                      View
                    </Button>
                  ) : null}
                  <span className="tnum text-muted-foreground ml-auto">
                    {fmtRow(inv.total, inv.currency)}
                  </span>
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
                            {row.debit ? fmtRow(row.debit, inv.currency) : "—"}
                          </td>
                          <td className="px-3 py-1.5 text-right tnum">
                            {row.credit ? fmtRow(row.credit, inv.currency) : "—"}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            ))
          )}
        </div>
      )}
    </Card>
  );
}
