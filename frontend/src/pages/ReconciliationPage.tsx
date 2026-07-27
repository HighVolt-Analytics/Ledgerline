import { useEffect, useLayoutEffect, useMemo, useState } from "react";
import { CheckCircle2, ChevronDown, ChevronRight, Scale } from "lucide-react";
import { api } from "@/api/client";
import { EmptyState } from "@/components/EmptyState";
import { PageHeader } from "@/components/PageHeader";
import { PageLoader } from "@/components/PageLoader";
import { ReconciliationDetailDrawer } from "@/components/ReconciliationDetailDrawer";
import { YearMonthPeriodPicker } from "@/components/YearMonthPeriodPicker";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { useAuth } from "@/context/AuthContext";
import {
  useReconciliationDaily,
  useReconciliationDayDetail,
  useReconciliationOverview,
} from "@/hooks/useReconciliationOverview";
import { useTenantTime } from "@/hooks/useTenantTime";
import { money, formatMoneyByCurrencyMap } from "@/lib/format";
import { ruleBookConfigFromApi } from "@/lib/ruleBookConfigApi";
import { DEFAULT_POSTING_DEFAULTS } from "@/lib/v4RuleBookMockData";
import type { PostingDefaults } from "@/lib/v4RuleBookTypes";
import {
  buildMonthsForYear,
  buildReconPeriodOptions,
  buildReconYears,
  defaultReconPeriod,
  documentCountForRecon,
  filterReconciliationByMonth,
  formatReconMonthLabel,
  mapReconciliationOverview,
  yearFromPeriod,
} from "@/lib/reconciliation";
import { cn } from "@/lib/cn";
import { API_PORT_HINT, formatTenantLoadError } from "@/lib/tenantSession";

export function ReconciliationPage() {
  const { user } = useAuth();
  const { timeZone, locale } = useTenantTime();
  const {
    data: overview,
    isLoading,
    error,
    blocked,
  } = useReconciliationOverview(Boolean(user));
  const { data: dailyRows } = useReconciliationDaily(Boolean(user));

  const [postingDefaults, setPostingDefaults] = useState<PostingDefaults>({
    ...DEFAULT_POSTING_DEFAULTS,
  });
  const [period, setPeriod] = useState("");
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const [detailDate, setDetailDate] = useState<string | null>(null);
  const { data: dayDetail } = useReconciliationDayDetail(detailDate, Boolean(user));
  const tenantScope = user?.tenant_id ?? null;

  const dailyByDate = useMemo(() => {
    const map = new Map<string, NonNullable<typeof dailyRows>[number]>();
    for (const row of dailyRows ?? []) {
      map.set(row.date, row);
    }
    return map;
  }, [dailyRows]);

  const baseCurrency = overview?.base_currency ?? "SGD";
  const fmtBase = (v: number) => money(v, baseCurrency, locale);
  const fmtRow = (v: number, currency?: string | null) =>
    money(v, currency?.trim() ? currency : null, locale);
  const fmtCurrencyMap = (totals: Record<string, number>) =>
    formatMoneyByCurrencyMap(totals, locale);

  useLayoutEffect(() => {
    setPostingDefaults({ ...DEFAULT_POSTING_DEFAULTS });
    setPeriod("");
    setExpanded({});
  }, [tenantScope]);

  useEffect(() => {
    if (!tenantScope) {
      setPeriod("");
      return;
    }
    api
      .getRuleBookConfig()
      .then((config) => setPostingDefaults(ruleBookConfigFromApi(config).postingDefaults))
      .catch(() => setPostingDefaults({ ...DEFAULT_POSTING_DEFAULTS }));
  }, [tenantScope]);

  const fullRecon = useMemo(
    () => (overview ? mapReconciliationOverview(overview) : null),
    [overview]
  );

  const activePeriod = useMemo(() => {
    if (!fullRecon) return "";
    if (period) {
      const year = yearFromPeriod(period);
      const months = buildMonthsForYear(year, timeZone, locale);
      if (months.some((m) => m.value === period)) return period;
    }
    return defaultReconPeriod(fullRecon, timeZone);
  }, [fullRecon, period, timeZone, locale]);

  const periodOptions = useMemo(
    () => buildReconPeriodOptions(fullRecon, timeZone, locale),
    [fullRecon, timeZone, locale]
  );

  const yearOptions = useMemo(() => buildReconYears(fullRecon, timeZone), [fullRecon, timeZone]);

  const selectedYear = activePeriod ? yearFromPeriod(activePeriod) : yearOptions[0] ?? "";

  const monthOptions = useMemo(
    () => (selectedYear ? buildMonthsForYear(selectedYear, timeZone, locale) : []),
    [selectedYear, timeZone, locale]
  );

  useEffect(() => {
    if (!activePeriod || activePeriod === period) return;
    if (!period) setPeriod(activePeriod);
  }, [activePeriod, period]);

  const periodLabel =
    periodOptions.find((p) => p.value === activePeriod)?.label ??
    (activePeriod ? formatReconMonthLabel(activePeriod, locale) : "Select month");

  const handleYearChange = (year: string) => {
    const months = buildMonthsForYear(year, timeZone, locale);
    if (months.length === 0) {
      setPeriod("");
      setExpanded({});
      return;
    }
    const monthPart = activePeriod.slice(5, 7);
    const keepMonth = months.find((m) => m.value.endsWith(`-${monthPart}`));
    setPeriod((keepMonth ?? months[0]).value);
    setExpanded({});
  };

  const handleMonthChange = (monthKey: string) => {
    setPeriod(monthKey);
    setExpanded({});
  };

  const periodRecon = useMemo(() => {
    if (!fullRecon || !activePeriod) return null;
    return filterReconciliationByMonth(fullRecon, activePeriod);
  }, [fullRecon, activePeriod]);

  const periodDocumentCount = periodRecon ? documentCountForRecon(periodRecon) : 0;

  const hasAnyDocuments = fullRecon != null && documentCountForRecon(fullRecon) > 0;

  const subtitle = useMemo(() => {
    if (!hasAnyDocuments) return "Double-entry posting and ledger balance check.";
    return "Double-entry postings per document, grouped by invoice date.";
  }, [hasAnyDocuments]);

  const periodSelector =
    yearOptions.length > 0 ? (
      <YearMonthPeriodPicker
        year={selectedYear}
        monthKey={activePeriod}
        yearOptions={yearOptions}
        monthOptions={monthOptions}
        onYearChange={handleYearChange}
        onMonthChange={handleMonthChange}
        disabled={isLoading}
        yearId="recon-year"
        monthId="recon-month"
        yearTestId="select-recon-year"
        monthTestId="select-recon-month"
        pickerTestId="recon-period-picker"
      />
    ) : null;

  if (!user) {
    return (
      <div>
        <PageHeader title="Reconciliation" subtitle="Double-entry posting and ledger balance check." />
        <EmptyState title="Sign in required" hint="Sign in to view ledger reconciliation." />
      </div>
    );
  }

  if (error && !blocked) {
    const message =
      error instanceof Error ? error.message : "Failed to load reconciliation";
    return (
      <Card className="p-6 border-destructive/30 bg-destructive/5 text-sm text-destructive">
        {formatTenantLoadError(message, API_PORT_HINT)}
      </Card>
    );
  }

  if (isLoading || blocked || !overview) {
    return <PageLoader variant="reports" />;
  }

  if (!hasAnyDocuments) {
    return (
      <div>
        <PageHeader title="Reconciliation" subtitle="Double-entry posting and ledger balance check." />
        <EmptyState
          title="Nothing to reconcile"
          hint="Process invoices through Approvals to generate ledger postings."
        />
      </div>
    );
  }

  if (!periodRecon) {
    return <PageLoader variant="reports" />;
  }

  const e = periodRecon;

  return (
    <div>
      <PageHeader title="Reconciliation" subtitle={subtitle} actions={periodSelector} />

      <Card
        className={cn(
          "p-5 mb-6",
          e.balanced
            ? "bg-[hsl(var(--chart-1)/0.06)] border-[hsl(var(--chart-1)/0.3)]"
            : "bg-destructive/5 border-destructive/30"
        )}
        data-testid="recon-banner"
      >
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            {e.balanced ? (
              <CheckCircle2 className="h-8 w-8 text-[hsl(var(--chart-1))]" />
            ) : (
              <Scale className="h-8 w-8 text-destructive" />
            )}
            <div>
              <div className="text-base font-semibold">
                {periodDocumentCount === 0
                  ? "No activity"
                  : e.balanced
                    ? "Ledger balanced"
                    : "Out of balance"}
              </div>
              <div className="text-sm text-muted-foreground">
                {periodLabel}
                {periodDocumentCount > 0 && !e.hasMixedCurrencies && (
                  <span className="tnum"> · Δ (Dr − Cr) = {fmtBase(e.deltaDrCr)}</span>
                )}
              </div>
              <div className="text-xs text-muted-foreground mt-1">
                Base currency totals ({baseCurrency})
                {e.hasMixedCurrencies ? " · foreign amounts shown per document" : ""}
              </div>
            </div>
          </div>
          <div className="flex gap-6 text-sm">
            <div className="text-right">
              <div className="text-xs text-muted-foreground">Total debits</div>
              <div className="tnum font-semibold">
                {e.hasMixedCurrencies ? fmtCurrencyMap(e.drByCurrency) : fmtBase(e.sumDr)}
              </div>
            </div>
            <div className="text-right">
              <div className="text-xs text-muted-foreground">Total credits</div>
              <div className="tnum font-semibold">
                {e.hasMixedCurrencies ? fmtCurrencyMap(e.crByCurrency) : fmtBase(e.sumCr)}
              </div>
            </div>
            <div className="text-right">
              <div className="text-xs text-muted-foreground">Documents</div>
              <div className="tnum font-semibold">{periodDocumentCount}</div>
            </div>
          </div>
        </div>
        {e.hasMixedCurrencies ? (
          <div
            className="mt-3 rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs text-amber-700 dark:text-amber-300"
            data-testid="recon-mixed-currency-warning"
          >
            Mixed currencies in this period. Document amounts stay in their own currency;
            conversion happens at payment. Do not treat foreign amounts as {baseCurrency}.
          </div>
        ) : null}
      </Card>

      {periodDocumentCount === 0 ? (
        <Card className="p-10 text-center text-sm text-muted-foreground">
          No documents with ledger postings in {periodLabel}.
        </Card>
      ) : (
        <div className="space-y-3">
          {e.byDate.map((day) => {
            const open = expanded[day.date] ?? false;
            const daily = dailyByDate.get(day.date);
            return (
              <Card key={day.date} className="overflow-hidden" data-testid={`recon-date-${day.date}`}>
                <div className="flex items-center gap-2 px-4 py-3">
                  <button
                    type="button"
                    onClick={() => setExpanded((prev) => ({ ...prev, [day.date]: !open }))}
                    className="flex flex-1 items-center gap-3 hover-elevate text-left min-w-0"
                    data-testid={`recon-toggle-${day.date}`}
                  >
                    {open ? (
                      <ChevronDown className="h-4 w-4 shrink-0" />
                    ) : (
                      <ChevronRight className="h-4 w-4 shrink-0" />
                    )}
                    <span className="font-medium tnum">{day.date}</span>
                    <Badge variant="outline" className="tnum">
                      {day.count} docs
                    </Badge>
                    {daily ? (
                      <>
                        <Badge
                          variant="outline"
                          className={
                            daily.rc1_passed
                              ? "text-[hsl(var(--chart-1))] border-[hsl(var(--chart-1)/0.4)]"
                              : "border-destructive/40 text-destructive"
                          }
                        >
                          RC1 {daily.rc1_passed ? "Pass" : "Fail"}
                        </Badge>
                        <Badge
                          variant="outline"
                          className={
                            daily.rc2_passed
                              ? "text-[hsl(var(--chart-1))] border-[hsl(var(--chart-1)/0.4)]"
                              : "border-destructive/40 text-destructive"
                          }
                        >
                          RC2 {daily.rc2_passed ? "Pass" : "Fail"}
                        </Badge>
                      </>
                    ) : null}
                    <div className="flex-1" />
                    <span className="text-sm text-muted-foreground tnum hidden sm:inline">
                      {day.hasMixedCurrencies
                        ? `Dr ${fmtCurrencyMap(day.drByCurrency)} · Cr ${fmtCurrencyMap(day.crByCurrency)}`
                        : `Dr ${fmtRow(day.sumDr, day.currencies[0] || baseCurrency)} · Cr ${fmtRow(day.sumCr, day.currencies[0] || baseCurrency)}`}
                    </span>
                    {day.hasMixedCurrencies ? (
                      <Badge
                        variant="outline"
                        className="border-amber-500/40 text-amber-700 dark:text-amber-300"
                        data-testid={`recon-mixed-${day.date}`}
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
                        Δ {fmtRow(day.delta, day.currencies[0] || baseCurrency)}
                      </Badge>
                    )}
                  </button>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    className="shrink-0"
                    onClick={() => setDetailDate(day.date)}
                    data-testid={`recon-detail-${day.date}`}
                  >
                    RC detail
                  </Button>
                </div>

                {open && (
                  <div className="border-t border-border px-4 py-3 space-y-4">
                    {day.invoices.map((inv) => (
                      <div key={inv.id}>
                        <div className="flex items-center gap-2 mb-1.5 text-sm">
                          <span className="font-medium">{inv.id}</span>
                          <span className="text-muted-foreground">{inv.vendor}</span>
                          {inv.currency ? (
                            <Badge variant="outline" className="tnum text-[10px]">
                              {inv.currency}
                            </Badge>
                          ) : (
                            <Badge
                              variant="outline"
                              className="border-amber-500/40 text-amber-700 dark:text-amber-300 text-[10px]"
                            >
                              Currency unknown
                            </Badge>
                          )}
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
                              {inv.postings.map((posting, idx) => (
                                <tr key={idx} className="border-t border-border/60">
                                  <td className="px-3 py-1.5">{posting.account}</td>
                                  <td className="px-3 py-1.5 text-right tnum">
                                    {posting.debit ? fmtRow(posting.debit, inv.currency) : "—"}
                                  </td>
                                  <td className="px-3 py-1.5 text-right tnum">
                                    {posting.credit ? fmtRow(posting.credit, inv.currency) : "—"}
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
      )}

      <p className="text-xs text-muted-foreground mt-4">
        Postings: each line subtotal debits its GL account, total {postingDefaults.taxAccount} debits the
        tax account, and the document total credits {postingDefaults.payableAccount}. RC1 checks invoice
        totals against payable/receivable control accounts; RC2 checks debits equal credits.
        Document currency is kept until payment; FX conversion uses the payment application rate.
      </p>

      <ReconciliationDetailDrawer
        detail={dayDetail ?? null}
        open={detailDate != null}
        onClose={() => setDetailDate(null)}
        currency={baseCurrency}
      />
    </div>
  );
}
