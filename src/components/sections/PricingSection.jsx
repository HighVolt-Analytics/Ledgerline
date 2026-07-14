import { Check, X } from 'lucide-react';
import FadeIn from '../ui/FadeIn';
import SectionLabel from '../ui/SectionLabel';
import SectionTitle from '../ui/SectionTitle';
import usePricingRegion from '../../hooks/usePricingRegion';
import { externalLinks } from '../../data/navigation';
import { pricingByCurrency } from '../../data/pricing';

function getCtaHref(cta) {
  if (cta === 'Get started') return externalLinks.getStarted;
  if (cta === 'Get it now') return externalLinks.signup;
  return null;
}

function PricingCard({ plan }) {
  const isPopular = plan.popular;
  const isContact = plan.price === 'Contact us';
  const includedFeatures = plan.features.filter((feature) => feature.included);
  const excludedFeatures = plan.features.filter((feature) => !feature.included);
  const orderedFeatures = [...includedFeatures, ...excludedFeatures];

  return (
    <div className={`pricing-card ${isPopular ? 'pricing-card--popular' : ''}`}>
      {isPopular && <span className="pricing-card-badge">Most popular</span>}

      <div>
        <h3 className="text-base font-semibold text-foreground">{plan.name}</h3>
        <p className="mt-1 text-xs text-muted-foreground">{plan.credits} credits</p>
      </div>

      <div className="mt-6 flex items-end gap-1.5">
        {plan.price === 'Free' ? (
          <span className="text-4xl font-semibold tracking-tight text-foreground">Free</span>
        ) : isContact ? (
          <span className="text-3xl font-semibold tracking-tight text-foreground">Contact us</span>
        ) : (
          <span className="text-4xl font-semibold tracking-tight text-foreground">{plan.price}</span>
        )}
        {plan.priceNote && !isContact && (
          <span className="mb-1 text-sm text-muted-foreground">{plan.priceNote}</span>
        )}
      </div>

      <p className="mt-3 text-sm leading-relaxed text-muted-foreground">{plan.pagesSummary}</p>

      <div className="pricing-card-divider my-6" />

      <ul className="flex flex-1 flex-col gap-3">
        {orderedFeatures.map((feature) => (
          <li
            key={feature.label}
            className="flex items-start gap-2.5 text-sm text-muted-foreground"
          >
            <span className={`pricing-check ${feature.included ? '' : 'pricing-check--excluded'}`}>
              {feature.included ? (
                <Check className="h-3 w-3" strokeWidth={3} />
              ) : (
                <X className="h-3 w-3" strokeWidth={3} />
              )}
            </span>
            <span>{feature.label}</span>
          </li>
        ))}
      </ul>

      {getCtaHref(plan.cta) ? (
        <a
          href={getCtaHref(plan.cta)}
          className={`pricing-card-cta mt-8 w-full ${isPopular ? 'pricing-card-cta--popular' : ''}`}
        >
          {plan.cta}
        </a>
      ) : (
        <button
          type="button"
          className={`pricing-card-cta mt-8 w-full ${isPopular ? 'pricing-card-cta--popular' : ''}`}
        >
          {plan.cta}
        </button>
      )}
    </div>
  );
}

export default function PricingSection() {
  const { currency, regionLabel, isLoading } = usePricingRegion();
  const plans = pricingByCurrency[currency];

  return (
    <section id="pricing" className="mx-auto max-w-[1200px] px-5 py-20 sm:px-8 sm:py-28">
      <FadeIn>
        <div className="text-center">
          <SectionLabel>Pricing</SectionLabel>
          <SectionTitle className="mt-4">Plans that scale with your volume</SectionTitle>
          <p className="mx-auto mt-4 max-w-xl text-lg text-muted-foreground">
            Start free, upgrade when you need more pages, access, and integrations.
          </p>
          <p className="mt-3 text-sm text-muted-foreground">
            {isLoading ? 'Detecting your region…' : `Prices shown for ${regionLabel} (${currency})`}
          </p>
        </div>
      </FadeIn>

      <div className="mt-14 grid grid-cols-1 gap-6 overflow-visible lg:grid-cols-3 lg:gap-5">
        {plans.map((plan, i) => (
          <FadeIn key={`${currency}-${plan.name}`} delay={i * 0.07}>
            <PricingCard plan={plan} />
          </FadeIn>
        ))}
      </div>
    </section>
  );
}
