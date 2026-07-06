import { useEffect, useLayoutEffect, useMemo, useState } from "react";
import { CheckCircle2, ChevronDown, ChevronRight, Scale } from "lucide-react";
import { api } from "@/api/client";
import { EmptyState } from "@/components/EmptyState";
import { PageHeader } from "@/components/PageHeader";
import { PageLoader } from "@/components/PageLoader";
import { YearMonthPeriodPicker } from "@/components/YearMonthPeriodPicker";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { useAuth } from "@/context/AuthContext";
import { useReconciliationOverview } from "@/hooks/useReconciliationOverview";
import { useTenantTime } from "@/hooks/useTenantTime";
import { money } from "@/lib/format";
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

  const [postingDefaults, setPostingDefaults] = useState<PostingDefaults>({
    ...DEFAULT_POSTING_DEFAULTS,
  });
  const [period, setPeriod] = useState("");
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const tenantScope = user?.tenant_id ?? null;

  const currency = overview?.base_currency ?? "AUD";
  const fmt = (v: number) => money(v, currency);

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
                {periodDocumentCount > 0 && (
                  <span className="tnum"> · Δ (Dr − Cr) = {fmt(e.deltaDrCr)}</span>
                )}
              </div>
            </div>
          </div>
          <div className="flex gap-6 text-sm">
            <div className="text-right">
              <div className="text-xs text-muted-foreground">Total debits</div>
              <div className="tnum font-semibold">{fmt(e.sumDr)}</div>
            </div>
            <div className="text-right">
              <div className="text-xs text-muted-foreground">Total credits</div>
              <div className="tnum font-semibold">{fmt(e.sumCr)}</div>
            </div>
            <div className="text-right">
              <div className="text-xs text-muted-foreground">Documents</div>
              <div className="tnum font-semibold">{periodDocumentCount}</div>
            </div>
          </div>
        </div>
      </Card>

      {periodDocumentCount === 0 ? (
        <Card className="p-10 text-center text-sm text-muted-foreground">
          No documents with ledger postings in {periodLabel}.
        </Card>
      ) : (
        <div className="space-y-3">
          {e.byDate.map((day) => {
            const open = expanded[day.date] ?? false;
            return (
              <Card key={day.date} className="overflow-hidden" data-testid={`recon-date-${day.date}`}>
                <button
                  type="button"
                  onClick={() => setExpanded((prev) => ({ ...prev, [day.date]: !open }))}
                  className="w-full flex items-center gap-3 px-4 py-3 hover-elevate text-left"
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
                              {inv.postings.map((posting, idx) => (
                                <tr key={idx} className="border-t border-border/60">
                                  <td className="px-3 py-1.5">{posting.account}</td>
                                  <td className="px-3 py-1.5 text-right tnum">
                                    {posting.debit ? fmt(posting.debit) : "—"}
                                  </td>
                                  <td className="px-3 py-1.5 text-right tnum">
                                    {posting.credit ? fmt(posting.credit) : "—"}
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
        tax account, and the document total credits {postingDefaults.payableAccount}.
      </p>
    </div>
  );
}
