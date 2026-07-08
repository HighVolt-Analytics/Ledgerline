import { Check } from "lucide-react";

import { cn } from "@/lib/cn";
import {
  plansForRegion,
  pricingRegionLabel,
  type PlanId,
  type PricingRegion,
} from "@/lib/pricingPlans";

type SignupPlanSelectorProps = {
  region: PricingRegion;
  selectedPlan: PlanId;
  busy?: boolean;
  onSelectPlan: (plan: PlanId) => void;
};

export function SignupPlanSelector({
  region,
  selectedPlan,
  busy = false,
  onSelectPlan,
}: SignupPlanSelectorProps) {
  const plans = plansForRegion(region);

  return (
    <div className="signup-plan-stack">
      <div
        className="signup-plan-grid"
        role="radiogroup"
        aria-label="Choose your plan"
      >
        {plans.map((plan) => {
          const isSelected = plan.id === selectedPlan;

          return (
            <article
              key={plan.id}
              role="radio"
              aria-checked={isSelected}
              tabIndex={busy ? -1 : 0}
              data-testid={`signup-plan-${plan.id}`}
              className={cn(
                "billing-pricing-card signup-plan-card",
                plan.featured && "billing-pricing-card--featured",
                isSelected && "signup-plan-card--selected"
              )}
              onClick={() => {
                if (busy) return;
                onSelectPlan(plan.id);
              }}
              onKeyDown={(event) => {
                if (busy) return;
                if (event.key === "Enter" || event.key === " ") {
                  event.preventDefault();
                  onSelectPlan(plan.id);
                }
              }}
            >
              <div className="signup-plan-card__header">
                {plan.badge ? (
                  <p className="billing-pricing-card__badge">{plan.badge}</p>
                ) : (
                  <span className="billing-pricing-card__badge-spacer" aria-hidden />
                )}
                {isSelected ? (
                  <span className="signup-plan-card__selected" aria-hidden>
                    <Check className="h-3.5 w-3.5" />
                    Selected
                  </span>
                ) : null}
              </div>

              <h3 className="billing-pricing-card__title">{plan.name}</h3>
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
            </article>
          );
        })}
      </div>
      <p className="billing-pricing-region-note">
        Prices in {pricingRegionLabel(region)}
      </p>
    </div>
  );
}
