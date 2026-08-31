export const TAX_RATE_TYPE_OPTIONS = [
  { value: "SALES", label: "Sales" },
  { value: "PURCHASES", label: "Purchases" },
  { value: "GST_FREE_SALES", label: "GST Free Sales" },
  { value: "EXEMPT_INCOME", label: "Exempt Income" },
  { value: "BAS_EXCLUDED", label: "BAS Excluded" },
  { value: "GST_FREE_EXPENSES", label: "GST Free Expenses" },
] as const;

export type TaxRateReportType = (typeof TAX_RATE_TYPE_OPTIONS)[number]["value"];

export function isTaxRateReportType(value: string): value is TaxRateReportType {
  return TAX_RATE_TYPE_OPTIONS.some((option) => option.value === value);
}

export function parseTaxRateInput(raw: string): number | null {
  const cleaned = raw.trim();
  if (!cleaned) return null;
  const value = Number(cleaned);
  if (!Number.isFinite(value)) return null;
  return value;
}

export function taxRateTypeLabel(value: string): string {
  return TAX_RATE_TYPE_OPTIONS.find((option) => option.value === value)?.label ?? value;
}

export function totalTaxRate(components: { rate: number }[]): number {
  const sum = components.reduce((acc, item) => acc + (Number(item.rate) || 0), 0);
  return Math.round(sum * 10000) / 10000;
}

export function formatTaxPercent(rate: number): string {
  return `${rate.toFixed(2)} %`;
}
