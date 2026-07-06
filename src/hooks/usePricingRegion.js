import { useEffect, useState } from 'react';
import {
  PRICING_REGION_LABELS,
  detectCurrencyFromUrl,
  resolvePricingCurrency,
} from '../utils/pricingRegion';

export default function usePricingRegion() {
  const urlCurrency = detectCurrencyFromUrl();
  const [currency, setCurrency] = useState(urlCurrency ?? 'AUD');
  const [isLoading, setIsLoading] = useState(!urlCurrency);

  useEffect(() => {
    if (urlCurrency) return;

    let active = true;

    resolvePricingCurrency().then((resolved) => {
      if (active) {
        setCurrency(resolved);
        setIsLoading(false);
      }
    });

    return () => {
      active = false;
    };
  }, [urlCurrency]);

  return {
    currency,
    isLoading,
    regionLabel: PRICING_REGION_LABELS[currency],
  };
}
