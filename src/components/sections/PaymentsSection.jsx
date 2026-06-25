import { Check } from 'lucide-react';
import FadeIn from '../ui/FadeIn';
import SectionLabel from '../ui/SectionLabel';
import SectionTitle from '../ui/SectionTitle';
import PaymentInvoiceCard from './PaymentInvoiceCard';
import { paymentFeatures } from '../../data/sections';

export default function PaymentsSection() {
  return (
    <section id="payments" className="mx-auto max-w-[1200px] px-5 py-20 sm:px-8 sm:py-28">
      <div className="grid grid-cols-1 items-center gap-12 lg:grid-cols-2">
        <FadeIn>
          <SectionLabel>Payments · v4</SectionLabel>
          <SectionTitle className="mt-4">Approved invoices pay themselves.</SectionTitle>
          <p className="mt-5 max-w-md text-lg text-muted-foreground">
            Top the wallet once. Every approved invoice draws from it at the scheduled date — through the multi-tier
            approval chain, with segregation of duties enforced server-side. Stripe Connect under the hood; CFO
            accountability up top.
          </p>
          <ul className="mt-7 flex flex-col gap-3">
            {paymentFeatures.map((feature) => (
              <li key={feature} className="flex items-start gap-3 text-sm leading-relaxed text-foreground">
                <span className="mt-0.5 grid h-5 w-5 shrink-0 place-items-center rounded-full bg-primary/12 text-primary">
                  <Check className="h-3 w-3" />
                </span>
                {feature}
              </li>
            ))}
          </ul>
        </FadeIn>

        <FadeIn delay={0.1}>
          <PaymentInvoiceCard />
        </FadeIn>
      </div>
    </section>
  );
}
