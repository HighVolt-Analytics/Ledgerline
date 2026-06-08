import { ArrowRight } from 'lucide-react';
import FadeIn from '../ui/FadeIn';
import SectionLabel from '../ui/SectionLabel';
import SectionTitle from '../ui/SectionTitle';
import { pricingPlans } from '../../data/pricing';

export default function PricingSection() {
  return (
    <section id="pricing" className="mx-auto max-w-[1200px] px-5 py-20 sm:px-8 sm:py-28">
      <FadeIn>
        <SectionLabel>Pricing</SectionLabel>
        <SectionTitle className="mt-4">Credit packs. No seat tax.</SectionTitle>
        <p className="mt-4 max-w-xl text-lg text-muted-foreground">
          One credit posts one document end to end. Buy what you need; credits never expire.
        </p>
      </FadeIn>

      <div className="mt-14 grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-4">
        {pricingPlans.map((plan, i) => (
          <FadeIn key={plan.name} delay={i * 0.07}>
            <div
              className={`relative flex h-full flex-col rounded-2xl border p-6 ${
                plan.popular ? 'border-primary/50 bg-card shadow-lg' : 'border-card-border bg-card'
              }`}
            >
              {plan.popular && (
                <>
                  <div
                    className="pointer-events-none absolute -inset-px -z-10 rounded-2xl opacity-60 blur-md"
                    style={{ background: 'hsl(var(--primary) / 0.20)' }}
                    aria-hidden="true"
                  />
                  <span className="absolute -top-2.5 left-6 rounded-full bg-primary px-2.5 py-0.5 font-mono text-[10px] uppercase tracking-[0.16em] text-primary-foreground">
                    Most popular
                  </span>
                </>
              )}

              <div className="text-sm font-medium text-foreground">{plan.name}</div>
              <div className="mt-5 font-mono text-4xl font-medium tabular text-foreground">{plan.credits}</div>
              <div className="mt-1 font-mono text-[11px] uppercase tracking-[0.16em] text-muted-foreground">credits</div>

              <div className="mt-6 flex items-baseline gap-2">
                <span className="text-2xl font-medium text-foreground">{plan.price}</span>
                {plan.price !== 'Custom' && plan.price !== 'Free' && (
                  <span className="text-sm text-muted-foreground">AUD</span>
                )}
              </div>

              <div className="mt-1 font-mono text-[12px] text-muted-foreground">{plan.per}</div>
              <div className="mt-5 text-sm text-muted-foreground">{plan.best}</div>

              <button
                className={`mt-7 inline-flex items-center justify-center gap-1.5 rounded-xl px-4 py-3 text-sm font-medium transition-transform duration-200 hover:scale-[1.02] active:scale-100 ${
                  plan.popular
                    ? 'bg-primary text-primary-foreground shadow-sm'
                    : 'border border-border bg-card/40 text-foreground hover-elevate active-elevate-2'
                }`}
              >
                {plan.cta}
                <ArrowRight className="h-3.5 w-3.5" />
              </button>
            </div>
          </FadeIn>
        ))}
      </div>
    </section>
  );
}
