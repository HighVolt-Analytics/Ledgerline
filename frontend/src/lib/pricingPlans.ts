/** Regional plan catalogue for pricing cards (display). */

export type PricingRegion = "IN" | "SG" | "AU";
export type PlanId = "free" | "studio" | "enterprise";

export type PlanCardModel = {
  id: PlanId;
  name: string;
  badge?: string;
  priceLabel: string;
  priceSuffix?: string;
  creditsLine?: string;
  features: string[];
  featured: boolean;
};

const CREDITS_PER_PAGE = 5;

const REGION_META: Record<
  PricingRegion,
  { symbol: string; currency: string; locale: string }
> = {
  IN: { symbol: "₹", currency: "INR", locale: "en-IN" },
  SG: { symbol: "S$", currency: "SGD", locale: "en-SG" },
  AU: { symbol: "A$", currency: "AUD", locale: "en-AU" },
};

/** India → IN, Singapore → SG, Australia → AU, all others → SG. */
export function pricingRegionForCountry(countryCode: string | null | undefined): PricingRegion {
  const code = (countryCode || "").trim().toUpperCase();
  if (code === "IN") return "IN";
  if (code === "SG") return "SG";
  if (code === "AU") return "AU";
  return "SG";
}

export function formatMoney(amount: number, region: PricingRegion): string {
  const { symbol, locale } = REGION_META[region];
  if (amount === 0) return `${symbol}0`;
  return `${symbol}${amount.toLocaleString(locale, { maximumFractionDigits: 0 })}`;
}

function pageCapacity(monthlyCredits: number): number {
  return Math.floor(monthlyCredits / CREDITS_PER_PAGE);
}

const STUDIO_BY_REGION: Record<
  PricingRegion,
  { monthlyPrice: number; monthlyCredits: number; pageCostLabel: string }
> = {
  IN: { monthlyPrice: 5000, monthlyCredits: 5000, pageCostLabel: "₹5 per page" },
  SG: { monthlyPrice: 50, monthlyCredits: 500, pageCostLabel: "S$0.10 per page" },
  AU: { monthlyPrice: 50, monthlyCredits: 250, pageCostLabel: "A$0.20 per page" },
};

export function plansForRegion(region: PricingRegion): PlanCardModel[] {
  const studio = STUDIO_BY_REGION[region];

  return [
    {
      id: "free",
      name: "Free",
      priceLabel: formatMoney(0, region),
      priceSuffix: "/ month",
      creditsLine: "50 credits every month",
      features: [
        `${pageCapacity(50)} pages per month`,
        "1 user seat",
        "Document upload",
        "5 credits per page",
      ],
      featured: false,
    },
    {
      id: "studio",
      name: "Studio",
      badge: "Most popular",
      priceLabel: formatMoney(studio.monthlyPrice, region),
      priceSuffix: "/ month",
      creditsLine: `${studio.monthlyCredits.toLocaleString()} credits every month`,
      features: [
        `${pageCapacity(studio.monthlyCredits)} pages per month`,
        "3 user seats",
        "Social media integration",
        "Email integration",
        studio.pageCostLabel,
      ],
      featured: true,
    },
    {
      id: "enterprise",
      name: "Enterprise",
      priceLabel: "Contact us",
      creditsLine: "Custom credit volume",
      features: [
        "Unlimited scale",
        "Social media integration",
        "Email integration",
        "Dedicated account support",
      ],
      featured: false,
    },
  ];
}

export function pricingRegionLabel(region: PricingRegion): string {
  return { IN: "India (INR)", SG: "Singapore (SGD)", AU: "Australia (AUD)" }[region];
}
