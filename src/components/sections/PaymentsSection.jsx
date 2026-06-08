import { Check } from 'lucide-react';
import FadeIn from '../ui/FadeIn';
import SectionLabel from '../ui/SectionLabel';
import SectionTitle from '../ui/SectionTitle';
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
          <div className="rounded-2xl border border-card-border bg-card p-6 shadow-md">
            <div className="font-mono text-[11px] uppercase tracking-[0.16em] text-muted-foreground">
              Stripe Wallet · org-1 Acme Hospitality
            </div>
            <div className="mt-5 font-mono text-4xl font-medium tabular text-foreground sm:text-5xl">
              <span className="whitespace-nowrap">A$ 24,580.00</span>
            </div>
            <div className="mt-1 text-sm text-muted-foreground">available for payment</div>
            <div className="mt-6 h-px w-full ledgerline-gradient opacity-60" />
            <div className="mt-6 space-y-3 font-mono text-[12px]">
              <WalletRow label="Awaiting approval: 7" value="A$ 18,420.00" />
              <WalletRow label="Approved · ready: 4" value="A$ 6,150.00" accent />
              <WalletRow label="Paid this month: 23" value="A$ 41,230.00" />
            </div>
            <div className="mt-6 inline-flex items-center gap-2 rounded-full border border-border bg-card/40 px-3.5 py-1.5 font-mono text-[11px] text-muted-foreground">
              Top up · Withdraw
            </div>
          </div>
        </FadeIn>
      </div>
    </section>
  );
}

function WalletRow({ label, value, accent = false }) {
  return (
    <div className="flex items-center justify-between">
      <span className="text-muted-foreground">{label}</span>
      <span className={`tabular whitespace-nowrap ${accent ? 'text-primary' : 'text-foreground'}`}>{value}</span>
    </div>
  );
}
