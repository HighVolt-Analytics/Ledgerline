/** v3 dashboard uses 6-point decorative sparklines ending at the current KPI value. */
export const V3_SPARK_POINTS = 6;

export type V3SparkMode = "count" | "seconds" | "money";

function padToPoints(source: number[], points: number, fallback: number): number[] {
  const out = source.slice(-points);
  while (out.length < points) {
    out.unshift(out[0] ?? fallback);
  }
  return out;
}

/**
 * Build spark data in the same shape as Ledgerline v3 mock dashboard cards.
 * Uses real daily series when available, but always ends on the displayed KPI value.
 */
export function toV3SparkSeries(
  daily: number[] | undefined,
  endValue: number,
  mode: V3SparkMode = "count",
): number[] | undefined {
  const raw = (daily ?? []).map((n) => Math.max(0, n));

  if (mode === "money") {
    const slice = padToPoints(raw, V3_SPARK_POINTS, 0);
    if (slice.every((v) => v === 0)) return undefined;
    const min = Math.min(...slice);
    const max = Math.max(...slice);
    if (max === min) return [2, 3, 4, 5, 6, 7];
    return slice.map((v) => Math.round(3 + ((v - min) / (max - min)) * 5));
  }

  if (mode === "seconds") {
    const sec = Math.max(0, Math.round(endValue));
    if (sec === 0 && raw.every((v) => v === 0)) return undefined;
    const series = padToPoints(raw.length ? raw : [sec], V3_SPARK_POINTS, sec);
    series[V3_SPARK_POINTS - 1] = sec;
    return series;
  }

  const end = Math.max(0, Math.round(endValue));
  if (end === 0 && raw.every((v) => v === 0)) return undefined;
  const series = padToPoints(raw.length ? raw : [end], V3_SPARK_POINTS, Math.max(0, end - 1));
  series[V3_SPARK_POINTS - 1] = end;
  return series;
}
