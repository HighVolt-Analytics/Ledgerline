import { Check } from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/cn";
import { signupPrimaryCtaLabel } from "@/lib/signupForm";
import {
  plansForRegion,
  pricingRegionLabel,
  type PlanId,
  type PricingRegion,
} from "@/lib/pricingPlans";

type SignupPlanStepProps = {
  region: PricingRegion;
  busy?: boolean;
  planDisabledReason: (plan: PlanId) => string | null;
  onChoosePlan: (plan: PlanId) => void;
};

export function SignupPlanStep({
  region,
  busy = false,
  planDisabledReason,
  onChoosePlan,
}: SignupPlanStepProps) {
  const plans = plansForRegion(region);

  return (
    <div className="signup-plan-stack">
      <div className="signup-plan-grid">
        {plans.map((plan) => {
          const disabledReason = planDisabledReason(plan.id);
          const disabled = busy || Boolean(disabledReason);

          return (
            <article
              key={plan.id}
              className={cn(
                "billing-pricing-card signup-plan-card signup-plan-card--action",
                plan.featured && "billing-pricing-card--featured"
              )}
              data-testid={`signup-plan-${plan.id}`}
            >
              {plan.badge ? (
                <p className="billing-pricing-card__badge">{plan.badge}</p>
              ) : (
                <span className="billing-pricing-card__badge-spacer" aria-hidden />
              )}

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

              <Button
                type="button"
                className="signup-plan-card__cta"
                data-testid={`signup-plan-cta-${plan.id}`}
                disabled={disabled}
                onClick={() => onChoosePlan(plan.id)}
              >
                {signupPrimaryCtaLabel(plan.id, busy)}
              </Button>

              {disabledReason ? (
                <p
                  className="signup-plan-card__disabled-reason"
                  data-testid={`signup-plan-disabled-${plan.id}`}
                >
                  {disabledReason}
                </p>
              ) : null}
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
