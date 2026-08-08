import {
  ClockCountdown,
  CurrencyDollar,
  Files,
  Lightning,
  Timer,
} from "@phosphor-icons/react";
import { KpiCard } from "@/components/KpiCard";

export type ExecutiveKpiDeltaView = {
  dir: "up" | "down" | "flat";
  text: string;
  good: boolean;
};

export type ExecutiveKpisView = {
  documentsProcessed: number;
  documentsDelta: ExecutiveKpiDeltaView | undefined;
  timeSavedMinutes: number;
  timeSavedHoursLabel: string;
  avgTimeSavedPerDoc: number;
  aiSavingsPct: number;
  aiSavingsDelta: ExecutiveKpiDeltaView | undefined;
  costSaved: number;
};

/** Fallback when overview has not yet returned executive KPIs. */
export const PLACEHOLDER_EXECUTIVE_KPIS: ExecutiveKpisView = {
  documentsProcessed: 0,
  documentsDelta: undefined,
  timeSavedMinutes: 0,
  timeSavedHoursLabel: "0.0 hours recovered",
  avgTimeSavedPerDoc: 0,
  aiSavingsPct: 0,
  aiSavingsDelta: undefined,
  costSaved: 0,
};

function formatMinutes(minutes: number): string {
  return `${minutes.toLocaleString()} min`;
}

export function ExecutiveKpiRow({
  currencySymbol = "$",
  kpis = PLACEHOLDER_EXECUTIVE_KPIS,
}: {
  currencySymbol?: string;
  kpis?: ExecutiveKpisView;
}) {
  const k = kpis;

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
