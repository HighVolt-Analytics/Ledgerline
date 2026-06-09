type ChartTooltipProps = {
  active?: boolean;
  payload?: readonly unknown[];
  label?: string | number;
  valueFormatter?: (value: number, name: string) => string;
};

export function ChartTooltip({
  active,
  payload,
  label,
  valueFormatter,
}: ChartTooltipProps) {
  if (!active || !payload?.length) return null;

  const row = payload[0] as {
    name?: string | number;
    value?: unknown;
    dataKey?: string | number;
    color?: string;
  };
  const raw = row.value;
  const dataKey = String(row.dataKey ?? row.name ?? "value");
  const heading =
    label != null && String(label) !== ""
      ? String(label)
      : row.name != null && String(row.name) !== ""
        ? String(row.name)
        : null;
  const numeric = typeof raw === "number" ? raw : Number(raw);
  const display =
    raw == null || Number.isNaN(numeric)
      ? "—"
      : valueFormatter
        ? valueFormatter(numeric, dataKey)
        : String(raw);
  const accent = row.color ?? "hsl(var(--chart-1))";

  return (
    <div className="chart-tooltip">
      {heading != null && <p className="chart-tooltip-label">{heading}</p>}
      <p className="chart-tooltip-value tnum" style={{ color: accent }}>
        {display}
      </p>
    </div>
  );
}
