import { Check } from 'lucide-react';
import FadeIn from '../ui/FadeIn';
import SectionLabel from '../ui/SectionLabel';
import SectionTitle from '../ui/SectionTitle';
import { pricingPlans } from '../../data/pricing';

function PricingCard({ plan }) {
  const isPopular = plan.popular;
  const priceSuffix = plan.price === 'Free' || plan.price === 'Custom' ? '' : 'AUD';

  return (
    <div className={`pricing-card ${isPopular ? 'pricing-card--popular' : ''}`}>
      {isPopular && <span className="pricing-card-badge">Most popular</span>}

      <div>
        <h3 className="text-base font-semibold text-foreground">{plan.name}</h3>
        <p className="mt-1 text-xs text-muted-foreground">Credit pack</p>
      </div>

      <div className="mt-6 flex items-end gap-1.5">
        <span className="text-4xl font-semibold tracking-tight text-foreground">{plan.price}</span>
        {priceSuffix && <span className="mb-1 text-sm text-muted-foreground">/ {priceSuffix}</span>}
      </div>

      <p className="mt-3 text-sm leading-relaxed text-muted-foreground">{plan.best}</p>

      <div className="pricing-card-divider my-6" />

      <ul className="flex flex-1 flex-col gap-3">
        {plan.features.map((feature) => (
          <li key={feature} className="flex items-start gap-2.5 text-sm text-muted-foreground">
            <span className="pricing-check">
              <Check className="h-3 w-3" strokeWidth={3} />
            </span>
            <span>{feature}</span>
          </li>
        ))}
      </ul>

      <button
        type="button"
        className={`pricing-card-cta mt-8 w-full ${isPopular ? 'pricing-card-cta--popular' : ''}`}
      >
        {plan.cta}
      </button>
    </div>
  );
}

export default function PricingSection() {
  return (
    <section id="pricing" className="mx-auto max-w-[1200px] px-5 py-20 sm:px-8 sm:py-28">
      <FadeIn>
        <div className="text-center">
          <SectionLabel>Pricing</SectionLabel>
          <SectionTitle className="mt-4">Credit packs. No seat tax.</SectionTitle>
          <p className="mx-auto mt-4 max-w-xl text-lg text-muted-foreground">
            One credit posts one document end to end. Buy what you need; credits never expire.
          </p>
        </div>
      </FadeIn>

      <div className="mt-14 grid grid-cols-1 gap-6 overflow-visible sm:grid-cols-2 lg:grid-cols-4 lg:gap-5">
        {pricingPlans.map((plan, i) => (
          <FadeIn key={plan.name} delay={i * 0.07}>
            <PricingCard plan={plan} />
          </FadeIn>
        ))}
      </div>
    </section>
  );
}
