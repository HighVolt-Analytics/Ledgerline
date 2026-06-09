const CURRENCY_SYMBOLS: Record<string, string> = {
  AUD: "A$",
  USD: "$",
  GBP: "£",
  NZD: "NZ$",
  EUR: "€",
  SGD: "S$",
  INR: "₹",
  AED: "د.إ",
};

export function currencySymbol(currency = "AUD"): string {
  return CURRENCY_SYMBOLS[currency] ?? currency;
}

/** Compact axis labels — matches v3 `hR(amount, symbol)`. */
export function axisMoney(v: number, symbol: string): string {
  const abs = Math.abs(v);
  if (abs >= 1_000_000) return `${symbol}${(v / 1_000_000).toFixed(1)}M`;
  if (abs >= 1_000) return `${symbol}${(v / 1_000).toFixed(1)}k`;
  if (v === 0) return `${symbol}0`;
  return `${symbol}${v.toFixed(0)}`;
}

export function compactMoney(v: number, currency = "AUD"): string {
  return axisMoney(v, currencySymbol(currency));
}

export function money(
  v: string | number | null | undefined,
  currency = "AUD"
): string {
  if (v == null || v === "") return "—";
  const n = typeof v === "string" ? parseFloat(v) : v;
  if (Number.isNaN(n)) return String(v);
  try {
    return new Intl.NumberFormat("en-AU", {
      style: "currency",
      currency: currency || "AUD",
    }).format(n);
  } catch {
    return String(v);
  }
}

export function invId(id: number): string {
  return `INV-${String(id).padStart(3, "0")}`;
}

/** Human-readable vault document id (matches inbox / matrix list style). */
export function vaultDocLabel(id: number): string {
  return `DOC-2026-${String(id).padStart(4, "0")}`;
}

export function vaultDocSubtitle(inv: {
  invoice_no: string | null;
  invoice_date: string | null;
  account_name?: string | null;
  cost_centre?: string | null;
}): string {
  const parts = [
    inv.invoice_no,
    inv.invoice_date,
    inv.account_name ?? inv.cost_centre,
  ].filter((part) => part && String(part).trim());
  return parts.length > 0 ? parts.join(" · ") : "—";
}

export function statusLabel(s: string): string {
  return s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

export function formatDuration(seconds: number | null | undefined): string {
  if (seconds == null || Number.isNaN(seconds)) return "—";
  if (seconds < 60) return `${Math.round(seconds)} sec`;
  if (seconds < 3600) return `${(seconds / 60).toFixed(1)} min`;
  return `${(seconds / 3600).toFixed(1)} hr`;
}

export function toNumber(v: string | number | null | undefined): number {
  if (v == null || v === "") return 0;
  const n = typeof v === "number" ? v : parseFloat(v);
  return Number.isNaN(n) ? 0 : n;
}

export function formatQty(v: string | number | null | undefined): string {
  if (v == null || v === "") return "—";
  const n = typeof v === "number" ? v : parseFloat(v);
  if (Number.isNaN(n)) return String(v);
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 }).format(
    Math.round(n)
  );
}

/** Australian ABN / tax ID — `XX XXX XXX XXX`. */
export function formatTaxId(value: string | null | undefined): string {
  if (!value?.trim()) return "—";
  const digits = value.replace(/\D/g, "");
  if (digits.length === 11) {
    return `${digits.slice(0, 2)} ${digits.slice(2, 5)} ${digits.slice(5, 8)} ${digits.slice(8)}`;
  }
  return value.trim();
}
