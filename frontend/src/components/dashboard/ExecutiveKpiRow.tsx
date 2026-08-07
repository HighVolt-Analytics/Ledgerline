import {
  ClockCountdown,
  CurrencyDollar,
  Files,
  Lightning,
  Timer,
} from "@phosphor-icons/react";
import { KpiCard } from "@/components/KpiCard";

/** Placeholder executive KPIs until overview API exposes savings metrics. */
export const PLACEHOLDER_EXECUTIVE_KPIS = {
  documentsProcessed: 125,
  documentsDelta: { dir: "up" as const, text: "18% vs. prior period", good: true },
  timeSavedMinutes: 1458,
  timeSavedHoursLabel: "24.3 hours recovered",
  avgTimeSavedPerDoc: 12,
  aiSavingsPct: 22,
  aiSavingsDelta: { dir: "up" as const, text: "3.8 pts vs. prior period", good: true },
  costSaved: 4167,
  currency: "USD",
};

function formatMinutes(minutes: number): string {
  return `${minutes.toLocaleString()} min`;
}

export function ExecutiveKpiRow({
  currencySymbol = "$",
}: {
  currencySymbol?: string;
}) {
  const k = PLACEHOLDER_EXECUTIVE_KPIS;

  return (
    <div
      className="grid gap-3 grid-cols-2 lg:grid-cols-5 mb-6"
      data-testid="dashboard-executive-kpis"
    >
      <KpiCard
        label="Documents processed"
        value={k.documentsProcessed.toLocaleString()}
        delta={k.documentsDelta}
        icon={Files}
        moduleColor="violet"
        testid="kpi-docs-processed"
      />
      <KpiCard
        label="Time returned"
        value={formatMinutes(k.timeSavedMinutes)}
        hint={k.timeSavedHoursLabel}
        icon={ClockCountdown}
        moduleColor="blue"
        testid="kpi-time-saved"
      />
      <KpiCard
        label="Average time saved"
        value={formatMinutes(k.avgTimeSavedPerDoc)}
        hint="per document"
        icon={Timer}
        moduleColor="rust"
        testid="kpi-avg-time-saved"
      />
      <KpiCard
        label="Automation efficiency"
        value={`${k.aiSavingsPct}%`}
        delta={k.aiSavingsDelta}
        icon={Lightning}
        moduleColor="rose"
        testid="kpi-ai-savings"
      />
      <KpiCard
        label="Estimated cost saved"
        value={`${currencySymbol}${k.costSaved.toLocaleString()}`}
        hint="Based on your cost model"
        icon={CurrencyDollar}
        moduleColor="cyan"
        testid="kpi-cost-saved"
      />
    </div>
  );
}
