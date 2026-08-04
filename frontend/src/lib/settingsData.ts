/** Settings page constants — re-export org setup catalogs (single source of truth). */

import {
  COUNTRIES,
  CURRENCIES,
  INDUSTRIES,
  countryByCode as baseCountryByCode,
  currencyByCode,
  defaultCurrencyForCountry,
  type CountryOption,
  type CurrencyOption,
  type Industry,
} from "@/data/orgSetup.tsx";

export {
  COUNTRIES,
  CURRENCIES,
  INDUSTRIES,
  currencyByCode,
  defaultCurrencyForCountry,
};
export type { CountryOption, CurrencyOption, Industry };

const TIMEZONE_BY_COUNTRY: Record<string, string> = {
  AU: "Australia/Sydney",
  US: "America/New_York",
  GB: "Europe/London",
  IN: "Asia/Kolkata",
  SG: "Asia/Singapore",
  NZ: "Pacific/Auckland",
  AE: "Asia/Dubai",
  DE: "Europe/Berlin",
};

export type SettingsCountryOption = CountryOption & {
  timeZone: string;
  currency: string;
  symbol: string;
};

export function countryByCode(code: string): SettingsCountryOption {
  const base = baseCountryByCode(code);
  const currency = currencyByCode(base.defaultCurrency);
  return {
    ...base,
    currency: currency.code,
    symbol: currency.symbol,
    timeZone: TIMEZONE_BY_COUNTRY[base.code] ?? "Asia/Singapore",
  };
}

export type TeamMemberRow = {
  id: string;
  name: string;
  email: string;
  role: string;
};
