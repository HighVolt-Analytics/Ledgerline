const fmt0 = new Intl.NumberFormat("en-AU", { maximumFractionDigits: 0 });
const fmt1 = new Intl.NumberFormat("en-AU", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
const fmt2 = new Intl.NumberFormat("en-AU", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

export function cfoN0(v: number) {
  return fmt0.format(Math.round(v));
}

export function cfoN1(v: number) {
  return fmt1.format(v);
}

export function cfoN2(v: number) {
  return fmt2.format(v);
}

export function cfoPct(v: number, decimals: 1 | 2 = 1) {
  return (decimals === 2 ? fmt2 : fmt1).format(v) + "%";
}

export function cfoCompact(v: number) {
  const a = Math.abs(v);
  if (a >= 1e6) return (v / 1e6).toFixed(a >= 1e7 ? 1 : 2) + "m";
  if (a >= 1e3) return (v / 1e3).toFixed(a >= 1e4 ? 0 : 1).replace(/\.0$/, "") + "k";
  return cfoN0(v);
}

export function cfoMoney(v: number, symbol = "A$") {
  return `${symbol}${cfoN0(v)}`;
}

export function cfoRag(utilisedPct: number): "g" | "a" | "r" {
  if (utilisedPct > 100) return "r";
  if (utilisedPct >= 90) return "a";
  return "g";
}

export function cfoRagLabel(utilisedPct: number) {
  if (utilisedPct > 100) return "Over budget";
  if (utilisedPct >= 90) return "Watch";
  return "On track";
}

export function cfoAxisCompact(v: number) {
  return cfoCompact(v);
}
