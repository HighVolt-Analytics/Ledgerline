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

const KPI_ORDER: readonly KpiModuleColor[] = [
  "violet",
  "blue",
  "teal",
  "green",
  "sage",
  "cyan",
  "rust",
  "rose",
] as const;

/** Saturated chart/bar fills — light mode (and solid donut/ops accents). */
export const KPI_MODULE_CHART_LIGHT: Readonly<Record<KpiModuleColor, string>> = {
  violet: "#5b3a7d",
  blue: "#245e8d",
  teal: "#275c70",
  green: "#356344",
  sage: "#337362",
  cyan: "#3b6f73",
  rust: "#9c4e2a",
  rose: "#8b4560",
};

/** Brighter chart fills for dark mode (source bars, sparklines, etc.). */
export const KPI_MODULE_CHART_DARK: Readonly<Record<KpiModuleColor, string>> = {
  violet: "#c4a3e8",
  blue: "#7ec8f5",
  teal: "#7ed4e0",
  green: "#8dcf9a",
  sage: "#7ecfba",
  cyan: "#7ecdd3",
  rust: "#e0a07a",
  rose: "#d89aaf",
};

/** Indexed chart palette (reports, etc.) — saturated light-mode tones. */
export const KPI_MODULE_CHART_COLORS: readonly string[] = [
  KPI_MODULE_CHART_LIGHT.violet,
  KPI_MODULE_CHART_LIGHT.blue,
  KPI_MODULE_CHART_LIGHT.teal,
  KPI_MODULE_CHART_LIGHT.green,
  KPI_MODULE_CHART_LIGHT.sage,
  KPI_MODULE_CHART_LIGHT.cyan,
  KPI_MODULE_CHART_LIGHT.rust,
  KPI_MODULE_CHART_LIGHT.rose,
] as const;

/** Soft chart fills for light mode — richer than icon tiles, softer than dark accents. */
export const KPI_MODULE_TILE_LIGHT: Readonly<Record<KpiModuleColor, string>> = {
  violet: "#b895d9",
  blue: "#7eb8d9",
  teal: "#7ec8d4",
  green: "#7cbc8a",
  sage: "#7bc4b0",
  cyan: "#7dbfc6",
  rust: "#d4926a",
  rose: "#c8889c",
};

/** Solid KPI icon tile backgrounds (dark mode) — matches `.dark .kpi-module-icon--*`. */
export const KPI_MODULE_TILE_DARK: Readonly<Record<KpiModuleColor, string>> = {
  violet: "#5b3a7d",
  blue: "#245e8d",
  teal: "#275c70",
  green: "#356344",
  sage: "#337362",
  cyan: "#3b6f73",
  rust: "#9c4e2a",
  rose: "#8b4560",
};

/**
 * Theme-aware chart fill for source bars / sparklines / list dots / attention bars.
 * Light: original soft pastels. Dark: brighter accents.
 */
export function kpiModuleFill(
  color: KpiModuleColor,
  theme: "light" | "dark" = "light"
): string {
  return theme === "dark" ? KPI_MODULE_CHART_DARK[color] : KPI_MODULE_TILE_LIGHT[color];
}

/**
 * Donut / user-layer fills.
 * Light: soft pastels (same as original). Dark: deep saturated accents.
 */
export function kpiModuleSolidFill(
  color: KpiModuleColor,
  theme: "light" | "dark" = "light"
): string {
  return theme === "dark" ? KPI_MODULE_CHART_LIGHT[color] : KPI_MODULE_TILE_LIGHT[color];
}

export function kpiModuleIconClass(color: KpiModuleColor): string {
  return `kpi-module-icon kpi-module-icon--${color}`;
}

export function kpiModuleChartColor(index: number): string {
  return KPI_MODULE_CHART_COLORS[index % KPI_MODULE_CHART_COLORS.length]!;
}

export function kpiModuleColorAt(index: number): KpiModuleColor {
  return KPI_ORDER[index % KPI_ORDER.length]!;
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
