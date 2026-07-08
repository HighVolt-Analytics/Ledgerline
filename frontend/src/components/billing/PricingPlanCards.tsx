import { Check } from "lucide-react";
import { cn } from "@/lib/cn";
import {
  plansForRegion,
  pricingRegionLabel,
  type PlanId,
  type PricingRegion,
} from "@/lib/pricingPlans";

type PricingPlanCardsProps = {
  region: PricingRegion;
  currentPlan: PlanId;
  canUpgradeStudio?: boolean;
  busy?: boolean;
  allowFreeSelect?: boolean;
  onSelectPlan: (plan: PlanId) => void;
};

function ctaLabel(plan: PlanId, currentPlan: PlanId, allowFreeSelect: boolean): string {
  if (plan === currentPlan && !allowFreeSelect) return "Current plan";
  if (plan === "free") return allowFreeSelect ? "Choose Free" : "Downgrade";
  if (plan === "studio") return "Upgrade to Studio";
  return "Contact sales";
}

export function PricingPlanCards({
  region,
  currentPlan,
  canUpgradeStudio = false,
  busy = false,
  allowFreeSelect = false,
  onSelectPlan,
}: PricingPlanCardsProps) {
  const plans = plansForRegion(region);

  return (
    <div className="billing-pricing-stack">
      <div className="billing-pricing-grid billing-pricing-grid--three billing-pricing-grid--modal">
        {plans.map((plan) => {
          const isCurrent = plan.id === currentPlan;
          const isStudio = plan.id === "studio";
          const isEnterprise = plan.id === "enterprise";
          const isFree = plan.id === "free";
          const disabled =
            busy ||
            isCurrent ||
            (isFree && !allowFreeSelect) ||
            (isStudio && (!canUpgradeStudio || currentPlan !== "free"));

          return (
            <article
              key={plan.id}
              className={cn(
                "billing-pricing-card",
                plan.featured && "billing-pricing-card--featured"
              )}
              data-testid={`pricing-card-${plan.id}`}
            >
              {plan.badge ? (
                <p className="billing-pricing-card__badge">{plan.badge}</p>
              ) : (
                <span className="billing-pricing-card__badge-spacer" aria-hidden />
              )}
              <h4 className="billing-pricing-card__title">{plan.name}</h4>
              <p className="billing-pricing-card__price">
                {plan.priceLabel}
                {plan.priceSuffix ? (
                  <span className="text-base font-medium opacity-70">{plan.priceSuffix}</span>
                ) : null}
              </p>
              {plan.creditsLine ? (
                <p className="billing-pricing-card__credits">{plan.creditsLine}</p>
              ) : null}
              <ul className="billing-pricing-card__features">
                {plan.features.map((feature) => (
                  <li key={feature} className="billing-pricing-card__feature">
                    <Check className="billing-pricing-card__check" aria-hidden />
                    <span>{feature}</span>
                  </li>
                ))}
              </ul>
              <button
                type="button"
                className={cn(
                  "billing-pricing-card__cta",
                  plan.featured
                    ? "billing-pricing-card__cta--featured"
                    : "billing-pricing-card__cta--standard"
                )}
                disabled={disabled}
                data-testid={`pricing-cta-${plan.id}`}
                onClick={() => {
                  if (isEnterprise) {
                    window.location.href = "mailto:sales@ledgerline.com?subject=Enterprise%20plan";
                    return;
                  }
                  onSelectPlan(plan.id);
                }}
              >
                {ctaLabel(plan.id, currentPlan, allowFreeSelect)}
              </button>
            </article>
          );
        })}
      </div>
      <p className="billing-pricing-region-note">Prices in {pricingRegionLabel(region)}</p>
    </div>
  );
}
