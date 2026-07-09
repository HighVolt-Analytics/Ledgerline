import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "@/api/client";
import { pricingRegionForCountry, type PricingRegion } from "@/lib/pricingPlans";

/** Instant hint from browser — works offline and on localhost. */
export function browserCountryHint(): string | null {
  const offset = new Date().getTimezoneOffset();
  if (offset === -330) return "IN";
  if (offset === -480) return "SG";

  try {
    const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
    if (/^(Asia\/Kolkata|Asia\/Calcutta)$/i.test(tz)) return "IN";
    if (/^Asia\/Singapore$/i.test(tz)) return "SG";
    if (/^Australia\//i.test(tz)) return "AU";
  } catch {
    /* ignore */
  }

  const langs =
    typeof navigator !== "undefined"
      ? navigator.languages?.length
        ? [...navigator.languages]
        : [navigator.language]
      : [];

  for (const lang of langs) {
    const region = lang.split("-")[1]?.toUpperCase();
    if (region === "IN" || region === "SG" || region === "AU") return region;
  }

  return null;
}

async function detectCountryFromIp(): Promise<string | null> {
  try {
    const fromApi = await api.getGeoCountry();
    if (fromApi.country_code) return fromApi.country_code;
  } catch {
    /* try public fallbacks */
  }

  for (const url of ["https://ipwho.is/", "https://ipapi.co/json/"]) {
    try {
      const res = await fetch(url);
      if (!res.ok) continue;
      const data = (await res.json()) as { country_code?: string; countryCode?: string };
      const code = (data.country_code ?? data.countryCode)?.trim();
      if (code) return code.toUpperCase();
    } catch {
      /* next provider */
    }
  }

  return null;
}

/**
 * Resolve pricing region: URL → IP (API + fallbacks) → browser locale/timezone →
 * institution country → tenant billing region → SG default.
 */
export function usePricingRegion(options?: {
  tenantCountry?: string | null;
  institutionCountry?: string | null;
}) {
  const [searchParams] = useSearchParams();
  const [ipCountry, setIpCountry] = useState<string | null>(null);
  const browserHint = useMemo(() => browserCountryHint(), []);

  const urlCountry = searchParams.get("country") ?? searchParams.get("region");

  useEffect(() => {
    if (urlCountry) return;

    let cancelled = false;
    void detectCountryFromIp().then((code) => {
      if (!cancelled && code) setIpCountry(code);
    });

    return () => {
      cancelled = true;
    };
  }, [urlCountry]);

  const region = useMemo<PricingRegion>(() => {
    const country =
      urlCountry ??
      browserHint ??
      ipCountry ??
      options?.institutionCountry ??
      options?.tenantCountry ??
      "SG";
    return pricingRegionForCountry(country);
  }, [
    urlCountry,
    browserHint,
    ipCountry,
    options?.institutionCountry,
    options?.tenantCountry,
  ]);

  return { region, browserHint, ipCountry, urlCountry };
}
