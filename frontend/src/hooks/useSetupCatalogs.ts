import { useEffect, useState } from "react";
import {
  fallbackCountries,
  fallbackCurrencies,
  fetchMetaCountries,
  fetchMetaCurrencies,
  metaCountriesToOptions,
  metaCurrenciesToOptions,
} from "@/lib/metaApi";
import type { CurrencyOption } from "@/data/orgSetup";

export type SetupCountryOption = {
  code: string;
  name: string;
  defaultCurrency: string;
  locale: string;
  taxRate: number | null;
  taxLabel: string;
  dialCode: string;
  timeZone?: string;
  timeZones?: string[];
};

export function useSetupCatalogs() {
  const [countries, setCountries] = useState<SetupCountryOption[]>(() =>
    fallbackCountries().map((c) => ({
      code: c.code,
      name: c.name,
      defaultCurrency: c.defaultCurrency,
      locale: c.locale,
      taxRate: c.taxRate,
      taxLabel: c.taxLabel,
      dialCode: c.dialCode,
    }))
  );
  const [currencies, setCurrencies] = useState<CurrencyOption[]>(() => fallbackCurrencies());
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    void Promise.all([fetchMetaCountries(), fetchMetaCurrencies()])
      .then(([countryRows, currencyRows]) => {
        if (cancelled) return;
        setCountries(metaCountriesToOptions(countryRows));
        setCurrencies(metaCurrenciesToOptions(currencyRows));
        setError(null);
      })
      .catch((err) => {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : "Could not load country/currency lists");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return { countries, currencies, loading, error };
}
