/** Dashboard KPI module icon colors — design system accent palette. */
export type KpiModuleColor =
  | "violet"
  | "blue"
  | "teal"
  | "green"
  | "sage"
  | "cyan"
  | "rust"
  | "rose";

/** Icon accent fills (light-mode foreground) — shared by charts and data viz. */
export const KPI_MODULE_CHART_COLORS: readonly string[] = [
  "#5b3a7d", // violet
  "#245e8d", // blue
  "#275c70", // teal
  "#356344", // green
  "#337362", // sage
  "#3b6f73", // cyan
  "#9c4e2a", // rust
  "#8b4560", // rose
] as const;

export function kpiModuleIconClass(color: KpiModuleColor): string {
  return `kpi-module-icon kpi-module-icon--${color}`;
}

export function kpiModuleChartColor(index: number): string {
  return KPI_MODULE_CHART_COLORS[index % KPI_MODULE_CHART_COLORS.length]!;
}

const STATUS_CHIP_BASE = "approvals-action-chip approvals-action-chip--static status-chip";

export function kpiStatusChipClass(color: KpiModuleColor): string {
  return `${STATUS_CHIP_BASE} approvals-action-chip--kpi-${color}`;
}

export function needsReviewStatusChipClass(): string {
  return kpiStatusChipClass("cyan");
}

export function warningStatusChipClass(): string {
  return kpiStatusChipClass("rust");
}

export function approvalStatusChipClass(
  tone: "review" | "approve" | "pending" | "post" | "edit" | "reject" | "delete" | "muted"
): string {
  return `${STATUS_CHIP_BASE} approvals-action-chip--${tone}`;
}
