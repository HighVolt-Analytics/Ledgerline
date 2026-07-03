import type { BillingState, PlanInfo } from "@/api/types";

const STUDIO_MONTHLY_BY_REGION: Record<string, number> = {
  IN: 5000,
  SG: 500,
  AU: 250,
};

const STUDIO_PRICE_BY_REGION: Record<string, number> = {
  IN: 5000,
  SG: 50,
  AU: 50,
};

const TOPUP_FACTOR_BY_REGION: Record<string, number> = {
  IN: 1,
  SG: 10,
  AU: 5,
};

function defaultPlanInfo(region: string, plan: string): PlanInfo {
  const isStudio = plan === "studio";
  const isEnterprise = plan === "enterprise";
  return {
    plan,
    region,
    currency_code: region === "IN" ? "INR" : region === "AU" ? "AUD" : "SGD",
    monthly_credits: isStudio
      ? (STUDIO_MONTHLY_BY_REGION[region] ?? 500)
      : isEnterprise
        ? 0
        : 50,
    max_users: isStudio || isEnterprise ? 3 : 1,
    social_integration: isStudio || isEnterprise,
    email_integration: isStudio || isEnterprise,
    studio_monthly_price: STUDIO_PRICE_BY_REGION[region] ?? 50,
    credits_per_page: 5,
    topup_factor: TOPUP_FACTOR_BY_REGION[region] ?? 10,
  };
}

/** Normalize API payload (handles legacy billing shape without plan_info). */
export function normalizeBillingState(raw: BillingState | null | undefined): BillingState | null {
  if (!raw) return null;

  const legacy = raw as BillingState & {
    current_pack?: string;
    region?: string;
  };

  const plan =
    raw.plan ??
    (legacy.current_pack === "starter" || legacy.current_pack === "team"
      ? "studio"
      : "free");

  const region = raw.plan_info?.region ?? legacy.region ?? "SG";
  const planInfo = raw.plan_info ?? defaultPlanInfo(region, plan);

  return {
    balance: Number(raw.balance ?? 0),
    plan,
    credits_per_page: raw.credits_per_page ?? planInfo.credits_per_page ?? 5,
    credits_consumed: raw.credits_consumed ?? 0,
    plan_info: planInfo,
    billing_anchor_date: raw.billing_anchor_date ?? null,
    fy_days_remaining: raw.fy_days_remaining ?? null,
    can_upgrade_studio: raw.can_upgrade_studio ?? plan === "free",
    can_top_up: raw.can_top_up ?? plan !== "enterprise",
    is_enterprise: raw.is_enterprise ?? plan === "enterprise",
  };
}

export function studioMonthlyCredits(region: string): number {
  return STUDIO_MONTHLY_BY_REGION[region] ?? STUDIO_MONTHLY_BY_REGION.SG;
}
