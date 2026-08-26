import { useMemo, useState } from "react";
import {
  ClockCountdown,
  Files,
  Lightning,
  SquaresFour,
  WarningCircle,
} from "@phosphor-icons/react";
import { Link } from "react-router-dom";
import { Card } from "@/components/ui/card";
import { Select } from "@/components/ui/select";
import { useTheme } from "@/context/ThemeContext";
import { cn } from "@/lib/cn";
import {
  KPI_MODULE_CHART_LIGHT,
  kpiModuleFill,
  kpiModuleIconClass,
  type KpiModuleColor,
} from "@/lib/kpiModuleColors";

export type OpsMemberId = string;

export type OpsStatusKey =
  | "processed"
  | "posted"
  | "rejected"
  | "review_pending"
  | "approvals_pending";

export type OpsDocTypeRow = {
  id: string;
  label: string;
  counts: Record<OpsStatusKey, number>;
};

export type OpsMemberSnapshot = {
  id: OpsMemberId;
  label: string;
  documentsProcessed: number;
  timeSavedMinutes: number;
  automationRatePct: number;
  pendingActions: number;
  accuracyPct: number;
  byDocType: OpsDocTypeRow[];
};

const PERIOD_OPTIONS = [
  { value: "30d", label: "Last 30 days" },
  { value: "7d", label: "Last 7 days" },
  { value: "month", label: "This month" },
];

const DOC_TYPE_OPTIONS = [
  { value: "all", label: "All document types" },
  { value: "invoice", label: "Invoice" },
  { value: "advance", label: "Advance" },
  { value: "claim", label: "Claim" },
];

const STATUS_META: {
  key: OpsStatusKey;
  label: string;
  tone: KpiModuleColor;
  pending?: boolean;
}[] = [
  { key: "processed", label: "Processed", tone: "blue" },
  { key: "posted", label: "Posted", tone: "green" },
  { key: "rejected", label: "Rejected", tone: "rose" },
  { key: "review_pending", label: "Review Pending", tone: "violet", pending: true },
  { key: "approvals_pending", label: "Approvals Pending", tone: "rust", pending: true },
];

function emptyCounts(): Record<OpsStatusKey, number> {
  return {
    processed: 0,
    posted: 0,
    rejected: 0,
    review_pending: 0,
    approvals_pending: 0,
  };
}

function sumCounts(
  rows: OpsDocTypeRow[],
  docTypeId: string
): { label: string; counts: Record<OpsStatusKey, number> } {
  if (docTypeId !== "all") {
    const row = rows.find((r) => r.id === docTypeId);
    return {
      label: row?.label ?? "Documents",
      counts: row?.counts ?? emptyCounts(),
    };
  }
  const counts = emptyCounts();
  for (const row of rows) {
    for (const s of STATUS_META) {
      counts[s.key] += row.counts[s.key] ?? 0;
    }
  }
  return { label: "All document types", counts };
}

/** Empty ops rollup when overview has no operations payload yet. */
export const PLACEHOLDER_OPS_MEMBERS: OpsMemberSnapshot[] = [
  {
    id: "all",
    label: "All team members",
    documentsProcessed: 0,
    timeSavedMinutes: 0,
    automationRatePct: 0,
    pendingActions: 0,
    accuracyPct: 0,
    byDocType: [
      { id: "invoice", label: "Invoice", counts: emptyCounts() },
      { id: "advance", label: "Advance", counts: emptyCounts() },
      { id: "claim", label: "Claim", counts: emptyCounts() },
    ],
  },
];

function rowTotal(counts: Record<OpsStatusKey, number>): number {
  return STATUS_META.reduce((sum, s) => sum + (counts[s.key] ?? 0), 0);
}

function StackedStatusBar({
  docLabel,
  counts,
  fills,
}: {
  docLabel: string;
  counts: Record<OpsStatusKey, number>;
  fills: Record<KpiModuleColor, string>;
}) {
  const total = rowTotal(counts);
  const segments = STATUS_META.map((s) => ({
    ...s,
    value: counts[s.key] ?? 0,
  })).filter((s) => s.value > 0);

  if (segments.length === 0) {
    return <div className="h-10 w-full rounded-md bg-muted/50" />;
  }

  return (
    <div
      className="flex w-full items-start gap-1.5"
      role="img"
      aria-label={`${docLabel}: ${segments.map((s) => `${s.label} ${s.value}`).join(", ")}`}
      data-testid="ops-stacked-bars"
    >
      {segments.map((seg) => {
        const pct = total > 0 ? Math.round((seg.value / total) * 100) : 0;
        return (
          <div
            key={seg.key}
            className="group relative min-w-[2.75rem]"
            style={{ flexGrow: seg.value, flexBasis: 0 }}
          >
            <div
              className="relative flex h-10 w-full items-center justify-center overflow-hidden rounded-md"
              style={{ backgroundColor: fills[seg.tone] }}
            >
              <span className="ops-stacked-bar-value relative z-[1] text-sm font-semibold tnum tabular-nums">
                {seg.value.toLocaleString()}
              </span>
            </div>
            <p className="mt-2 px-0.5 text-center text-[11px] font-medium text-muted-foreground truncate leading-tight">
              {seg.label}
            </p>

            <div
              className={cn(
                "pointer-events-none absolute left-1/2 top-full z-20 mt-1 hidden w-52 -translate-x-1/2",
                "rounded-md border border-border bg-popover p-2.5 text-xs shadow-md",
                "group-hover:block group-focus-within:block"
              )}
              role="tooltip"
            >
              <p className="font-semibold text-foreground mb-1.5">
                {docLabel} · {seg.label}
              </p>
              <ul className="space-y-0.5 text-muted-foreground tnum">
                <li className="flex justify-between gap-3">
                  <span>This status</span>
                  <span
                    className={cn(
                      "font-medium",
                      seg.pending ? "ds-warning-text" : "text-foreground"
                    )}
                  >
                    {seg.value.toLocaleString()}
                  </span>
                </li>
                <li className="flex justify-between gap-3">
                  <span>Share</span>
                  <span className="font-medium text-foreground">{pct}%</span>
                </li>
                <li className="flex justify-between gap-3 pt-1 mt-0.5 border-t border-border/60 font-medium text-foreground">
                  <span>Total</span>
                  <span>{total.toLocaleString()}</span>
                </li>
              </ul>
            </div>
          </div>
        );
      })}
    </div>
  );
}

export function OperationsLayer({
  members,
  windows,
  className,
}: {
  members?: OpsMemberSnapshot[];
  /** Prefer period-scoped windows from overview (`7d` | `30d` | `month`). */
  windows?: Record<string, OpsMemberSnapshot[]>;
  className?: string;
}) {
  const { theme } = useTheme();
  const [memberId, setMemberId] = useState<OpsMemberId>("all");
  const [period, setPeriod] = useState("30d");
  const [docTypeId, setDocTypeId] = useState("all");

  const periodMembers = useMemo(() => {
    if (windows) {
      return windows[period] ?? windows["30d"] ?? windows["month"] ?? PLACEHOLDER_OPS_MEMBERS;
    }
    return members ?? PLACEHOLDER_OPS_MEMBERS;
  }, [windows, members, period]);

  const memberOptions = useMemo(
    () =>
      periodMembers.map((m) => ({
        value: m.id,
        label: m.label,
      })),
    [periodMembers]
  );

  const snapshot = useMemo(() => {
    const found = periodMembers.find((m) => m.id === memberId);
    return found ?? periodMembers[0] ?? PLACEHOLDER_OPS_MEMBERS[0]!;
  }, [periodMembers, memberId]);

  const fills = useMemo(() => {
    const map = {} as Record<KpiModuleColor, string>;
    for (const tone of [
      "violet",
      "blue",
      "teal",
      "green",
      "sage",
      "cyan",
      "rust",
      "rose",
    ] as const) {
      // Light: original soft pastels. Dark: deep accents for white labels.
      map[tone] =
        theme === "dark" ? KPI_MODULE_CHART_LIGHT[tone] : kpiModuleFill(tone, "light");
    }
    return map;
  }, [theme]);

  const activeBar = useMemo(
    () => sumCounts(snapshot.byDocType, docTypeId),
    [snapshot.byDocType, docTypeId]
  );

  const docsTotal = rowTotal(activeBar.counts);

  return (
    <Card
      className={cn("dash-card--elevated p-4 mb-6", className)}
      data-testid="dashboard-operations"
    >
      <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
        <h3 className="text-sm font-semibold inline-flex items-center gap-2">
          <SquaresFour size={16} weight="duotone" className="text-muted-foreground" aria-hidden />
          Operations
        </h3>
        <div className="flex flex-wrap items-center gap-2">
          <Select
            value={memberOptions.some((o) => o.value === memberId) ? memberId : "all"}
            onValueChange={(v) => setMemberId(v)}
            options={memberOptions}
            className="w-[170px] h-8 text-xs"
            size="sm"
            data-testid="select-ops-member"
          />
          <Select
            value={docTypeId}
            onValueChange={setDocTypeId}
            options={DOC_TYPE_OPTIONS}
            className="w-[160px] h-8 text-xs"
            size="sm"
            data-testid="select-ops-doc-type"
          />
          <Select
            value={period}
            onValueChange={setPeriod}
            options={PERIOD_OPTIONS}
            className="w-[140px] h-8 text-xs"
            size="sm"
            data-testid="select-ops-period"
          />
        </div>
      </div>

      <div
        className="grid gap-3 grid-cols-2 lg:grid-cols-4 mb-5"
        data-testid="ops-kpi-strip"
      >
        <div className="rounded-lg border border-border/50 bg-muted/20 px-3 py-2.5">
          <div className="flex items-center justify-between gap-2">
            <p className="text-[11px] text-muted-foreground">Documents Processed</p>
            <span className={cn(kpiModuleIconClass("blue"), "!h-6 !w-6")} aria-hidden>
              <Files size={13} weight="duotone" />
            </span>
          </div>
          <p className="text-lg font-semibold tnum tabular-nums mt-0.5">
            {snapshot.documentsProcessed.toLocaleString()}
          </p>
        </div>
        <div className="rounded-lg border border-border/50 bg-muted/20 px-3 py-2.5">
          <div className="flex items-center justify-between gap-2">
            <p className="text-[11px] text-muted-foreground">Time Saved</p>
            <span className={cn(kpiModuleIconClass("teal"), "!h-6 !w-6")} aria-hidden>
              <ClockCountdown size={13} weight="duotone" />
            </span>
          </div>
          <p className="text-lg font-semibold tnum tabular-nums mt-0.5">
            {snapshot.timeSavedMinutes.toLocaleString()} min
          </p>
        </div>
        <div className="rounded-lg border border-border/50 bg-muted/20 px-3 py-2.5">
          <div className="flex items-center justify-between gap-2">
            <p className="text-[11px] text-muted-foreground">Automation Rate</p>
            <span className={cn(kpiModuleIconClass("violet"), "!h-6 !w-6")} aria-hidden>
              <Lightning size={13} weight="duotone" />
            </span>
          </div>
          <p className="text-lg font-semibold tnum tabular-nums mt-0.5">
            {snapshot.automationRatePct}%
          </p>
        </div>
        <div className="rounded-lg border border-border/50 bg-muted/20 px-3 py-2.5">
          <div className="flex items-center justify-between gap-2">
            <p className="text-[11px] text-muted-foreground">Pending Actions</p>
            <span className={cn(kpiModuleIconClass("rust"), "!h-6 !w-6")} aria-hidden>
              <WarningCircle size={13} weight="duotone" />
            </span>
          </div>
          <p className="text-lg font-semibold tnum tabular-nums mt-0.5 ds-warning-text">
            {snapshot.pendingActions.toLocaleString()}
          </p>
        </div>
      </div>

      <div>
        <div className="flex flex-wrap items-center justify-between gap-2 mb-3">
          <p className="text-base font-semibold tnum tabular-nums">
            {docsTotal.toLocaleString()}{" "}
            <span className="font-medium text-muted-foreground">Documents</span>
          </p>
          <Link
            to="/upload"
            className="inline-flex h-8 items-center gap-1.5 rounded-full border border-border/70 bg-background px-3 text-xs font-medium text-muted-foreground hover:text-foreground hover-elevate"
            data-testid="ops-view-detail"
          >
            <SquaresFour size={14} weight="duotone" aria-hidden />
            View detail
          </Link>
        </div>

        <div className="pb-1">
          <StackedStatusBar
            docLabel={activeBar.label}
            counts={activeBar.counts}
            fills={fills}
          />
        </div>
      </div>
    </Card>
  );
}
