import { resolveApiBase } from "@/lib/apiBase";
import { COUNTRIES, CURRENCIES, type CountryOption, type CurrencyOption } from "@/data/orgSetup";

const BASE = resolveApiBase();

/** Dial codes for the 8 jurisdiction-pack countries only (do not invent for all ISO). */
const PACK_DIAL_CODES: Record<string, string> = {
  AU: "+61",
  US: "+1",
  GB: "+44",
  IN: "+91",
  SG: "+65",
  NZ: "+64",
  AE: "+971",
  DE: "+49",
};

export type MetaCurrency = {
  code: string;
  name: string;
  symbol: string;
  decimal_places: number;
};

export type MetaCountry = {
  code: string;
  name: string;
  default_currency: string;
  tax_label: string;
  statutory_tax_rate: number | null;
  timezone: string;
  locale: string;
  has_jurisdiction_pack: boolean;
};

async function parseEnvelope<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail || body.message || detail;
    } catch {
      /* ignore */
    }
    throw new Error(typeof detail === "string" ? detail : "Request failed");
  }
  const json = await res.json();
  return json.data as T;
}

export async function fetchMetaCurrencies(): Promise<MetaCurrency[]> {
  const res = await fetch(`${BASE}/api/meta/currencies`);
  return parseEnvelope<MetaCurrency[]>(res);
}

export async function fetchMetaCountries(): Promise<MetaCountry[]> {
  const res = await fetch(`${BASE}/api/meta/countries`);
  return parseEnvelope<MetaCountry[]>(res);
}

export function fallbackCurrencies(): CurrencyOption[] {
  return CURRENCIES;
}

export function fallbackCountries(): Array<
  CountryOption & {
    taxLabel: string;
    taxRate: number | null;
    defaultCurrency: string;
    timeZone?: string;
  }
> {
  return COUNTRIES.map((c) => ({
    ...c,
    taxRate: c.taxRate,
    taxLabel: c.taxLabel,
    defaultCurrency: c.defaultCurrency,
  }));
}

export function metaCurrenciesToOptions(rows: MetaCurrency[]): CurrencyOption[] {
  return rows.map((r) => ({
    code: r.code,
    name: r.name,
    symbol: r.symbol || r.code,
    decimalPlaces: r.decimal_places,
  }));
}

export function metaCountriesToOptions(rows: MetaCountry[]): Array<{
  code: string;
  name: string;
  defaultCurrency: string;
  locale: string;
  taxRate: number | null;
  taxLabel: string;
  dialCode: string;
  timeZone: string;
}> {
  return rows.map((r) => ({
    code: r.code,
    name: r.name,
    defaultCurrency: r.default_currency,
    locale: r.locale,
    taxRate: r.statutory_tax_rate,
    taxLabel: r.tax_label,
    dialCode: PACK_DIAL_CODES[r.code] ?? "",
    timeZone: r.timezone,
  }));
}
