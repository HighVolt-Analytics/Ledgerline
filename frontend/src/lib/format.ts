import { DEFAULT_TENANT_LOCALE } from "@/lib/tenantTime";

const CURRENCY_SYMBOLS: Record<string, string> = {
  AUD: "A$",
  USD: "US$",
  GBP: "£",
  NZD: "NZ$",
  EUR: "€",
  SGD: "S$",
  INR: "₹",
  AED: "د.إ",
};

/** Uppercase ISO code, or null when blank/unknown (never invents SGD). */
export function normalizeCurrencyCode(
  currency: string | null | undefined
): string | null {
  const code = (currency ?? "").trim().toUpperCase();
  return code || null;
}

export function currencySymbol(currency?: string | null): string {
  const code = normalizeCurrencyCode(currency);
  if (!code) return "";
  return CURRENCY_SYMBOLS[code] ?? code;
}

/** Compact axis labels — matches v3 `hR(amount, symbol)`. */
export function axisMoney(v: number, symbol: string): string {
  const abs = Math.abs(v);
  if (abs >= 1_000_000) return `${symbol}${(v / 1_000_000).toFixed(1)}M`;
  if (abs >= 1_000) return `${symbol}${(v / 1_000).toFixed(1)}k`;
  if (v === 0) return `${symbol}0`;
  return `${symbol}${v.toFixed(0)}`;
}

export function compactMoney(v: number, currency?: string | null): string {
  return axisMoney(v, currencySymbol(currency));
}

function formatPlainAmount(n: number, locale: string): string {
  return new Intl.NumberFormat(locale || DEFAULT_TENANT_LOCALE, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(n);
}

function formatAmountWithRawSymbol(n: number, symbol: string, locale: string): string {
  return `${symbol}${formatPlainAmount(n, locale)}`;
}

function formatMoneyWithSymbol(
  n: number,
  currency: string,
  locale: string
): string {
  const symbol = currencySymbol(currency);
  const parts = new Intl.NumberFormat(locale || DEFAULT_TENANT_LOCALE, {
    style: "currency",
    currency,
  }).formatToParts(n);
  return parts.map((part) => (part.type === "currency" ? symbol : part.value)).join("");
}

/**
 * Format money by priority: ISO code → raw display symbol (e.g. `$`) → plain amount.
 * Never invents a tenant default when currency is blank.
 */
export function money(
  v: string | number | null | undefined,
  currency: string | null | undefined = null,
  locale: string = DEFAULT_TENANT_LOCALE,
  displaySymbol?: string | null
): string {
  if (v == null || v === "") return "—";
  const n = typeof v === "string" ? parseFloat(v) : v;
  if (Number.isNaN(n)) return String(v);
  const loc = locale || DEFAULT_TENANT_LOCALE;
  const code = normalizeCurrencyCode(currency);
  const symbol = (displaySymbol ?? "").trim();
  try {
    if (code) return formatMoneyWithSymbol(n, code, loc);
    if (symbol) return formatAmountWithRawSymbol(n, symbol, loc);
    return formatPlainAmount(n, loc);
  } catch {
    return String(v);
  }
}

/** Prefer invoices.currency; fall back to extracted_fields.currency_symbol. */
export function currencyDisplaySymbol(
  currency: string | null | undefined,
  extractedFields?: Record<string, string | null | undefined> | null
): string | null {
  if (normalizeCurrencyCode(currency)) return null;
  const symbol = (extractedFields?.currency_symbol ?? "").trim();
  return symbol || null;
}

export function invoiceMoney(
  v: string | number | null | undefined,
  inv: {
    currency?: string | null;
    extracted_fields?: Record<string, string | null | undefined> | null;
  },
  locale: string = DEFAULT_TENANT_LOCALE
): string {
  return money(v, inv.currency, locale, currencyDisplaySymbol(inv.currency, inv.extracted_fields));
}

/** Format a multi-currency total map; single code or joined breakdown (no FX). */
export function formatMoneyByCurrencyMap(
  totals: Record<string, number>,
  locale: string = DEFAULT_TENANT_LOCALE
): string {
  const entries = Object.entries(totals)
    .map(([code, amount]) => [normalizeCurrencyCode(code) ?? "", amount] as const)
    .filter(([, amount]) => Number.isFinite(amount))
    .sort(([a], [b]) => a.localeCompare(b));
  if (entries.length === 0) return "—";
  return entries.map(([code, amount]) => money(amount, code || null, locale)).join(" · ");
}

/** Stable org document label (document register ref). */
export function documentDisplayRef(inv: {
  id: number;
  document_ref?: string | null;
}): string {
  const ref = inv.document_ref?.trim();
  if (ref) return ref;
  return `DOC-${inv.id}`;
}

/** Supplier invoice number when present (AP / three-way match). */
export function vendorInvoiceNo(inv: {
  invoice_no?: string | null;
}): string | null {
  const no = inv.invoice_no?.trim();
  return no || null;
}

/** List row: org ref primary, vendor invoice no when different. */
export function documentListLabel(inv: {
  id: number;
  document_ref?: string | null;
  invoice_no?: string | null;
}): string {
  const ref = documentDisplayRef(inv);
  const vendorNo = vendorInvoiceNo(inv);
  if (vendorNo && vendorNo !== ref) {
    return `${ref} · ${vendorNo}`;
  }
  return ref;
}

/** @deprecated Use documentDisplayRef — kept for search/back-compat only. */
export function vaultDocLabel(inv: { id: number; document_ref?: string | null }): string {
  return documentDisplayRef(inv);
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
