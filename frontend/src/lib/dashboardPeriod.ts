export const DASHBOARD_PERIODS = ["fy_ytd", "mtd", "fq_ytd", "r12"] as const;

export type DashboardPeriod = (typeof DASHBOARD_PERIODS)[number];

export const DEFAULT_DASHBOARD_PERIOD: DashboardPeriod = "fy_ytd";

export const DASHBOARD_PERIOD_OPTIONS: { value: DashboardPeriod; label: string }[] = [
  { value: "fy_ytd", label: "Financial year YTD" },
  { value: "mtd", label: "Month to date" },
  { value: "fq_ytd", label: "Quarter to date" },
  { value: "r12", label: "Rolling 12 months" },
];

export function isDashboardPeriod(value: string): value is DashboardPeriod {
  return (DASHBOARD_PERIODS as readonly string[]).includes(value);
}

export function dashboardPeriodQuery(period: DashboardPeriod): string {
  return `period=${encodeURIComponent(period)}`;
}
