const STORAGE_KEY = 'ledgerlink-pricing-currency';

const REGION_CURRENCY = {
  in: 'INR',
  india: 'INR',
  sg: 'SGD',
  singapore: 'SGD',
  au: 'AUD',
  australia: 'AUD',
};

const COUNTRY_CURRENCY = {
  IN: 'INR',
  SG: 'SGD',
  AU: 'AUD',
};

export const PRICING_REGION_LABELS = {
  INR: 'India',
  SGD: 'Singapore',
  AUD: 'Australia',
};

export function getCurrencyFromRegionToken(token) {
  if (!token) return null;
  return REGION_CURRENCY[token.toLowerCase()] ?? null;
}

export function getCurrencyFromCountryCode(countryCode) {
  if (!countryCode) return null;
  return COUNTRY_CURRENCY[countryCode.toUpperCase()] ?? null;
}

function readCachedCurrency() {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const { currency } = JSON.parse(raw);
    return ['AUD', 'SGD', 'INR'].includes(currency) ? currency : null;
  } catch {
    return null;
  }
}

function writeCachedCurrency(currency) {
  try {
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify({ currency }));
  } catch {
    // Ignore storage failures (private browsing, etc.)
  }
}

export function detectCurrencyFromUrl() {
  if (typeof window === 'undefined') return null;

  const { hostname, pathname, search } = window.location;
  const params = new URLSearchParams(search);
  const regionParam = params.get('region') ?? params.get('country');

  const fromParam = getCurrencyFromRegionToken(regionParam);
  if (fromParam) return fromParam;

  const host = hostname.toLowerCase();
  const hostParts = host.split('.');

  if (hostParts.length > 2) {
    const subdomain = hostParts[0];
    const fromSubdomain = getCurrencyFromRegionToken(subdomain);
    if (fromSubdomain) return fromSubdomain;
  }

  if (host.endsWith('.in') || host === 'in') return 'INR';
  if (host.endsWith('.sg') || host === 'sg') return 'SGD';
  if (host.endsWith('.com.au') || host.endsWith('.au')) return 'AUD';

  const pathSegment = pathname.split('/').filter(Boolean)[0];
  return getCurrencyFromRegionToken(pathSegment);
}

async function detectCurrencyFromIp() {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 4000);

  try {
    const response = await fetch('https://ipapi.co/json/', {
      signal: controller.signal,
    });

    if (!response.ok) return 'AUD';

    const data = await response.json();
    return getCurrencyFromCountryCode(data.country_code) ?? 'AUD';
  } catch {
    return 'AUD';
  } finally {
    clearTimeout(timeout);
  }
}

export async function resolvePricingCurrency() {
  const cached = readCachedCurrency();
  if (cached) return cached;

  const fromUrl = detectCurrencyFromUrl();
  if (fromUrl) {
    writeCachedCurrency(fromUrl);
    return fromUrl;
  }

  const fromIp = await detectCurrencyFromIp();
  writeCachedCurrency(fromIp);
  return fromIp;
}
