import FadeIn from '../ui/FadeIn';
import SectionLabel from '../ui/SectionLabel';
import SectionTitle from '../ui/SectionTitle';
import { lifecycleSteps } from '../../data/sections';

export default function HowItWorksSection() {
  return (
    <section id="how" className="relative mx-auto max-w-[1200px] px-5 py-20 sm:px-8 sm:py-28">
      <FadeIn>
        <SectionLabel>The lifecycle</SectionLabel>
        <SectionTitle className="mt-4">Fourteen stages. One document.</SectionTitle>
        <p className="mt-4 max-w-xl text-lg text-muted-foreground">
          Each document — invoice, expense claim, PO, or payment — moves through the same deterministic pipeline.
          Observable at every step. Gated by six controls. Reversible until it pays.
        </p>
      </FadeIn>

      <div className="mt-14 grid auto-rows-fr grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {lifecycleSteps.map((step, i) => (
          <FadeIn key={step.n} delay={i * 0.04} className="h-full">
            <div className="group relative flex h-full min-h-[11rem] flex-col rounded-2xl border border-card-border bg-card p-6 shadow-sm hover-elevate">
              <div className="flex items-baseline justify-between">
                <span className="font-mono text-sm text-primary">{step.n}</span>
                <span className="h-1.5 w-1.5 rounded-full bg-primary/40 transition-colors group-hover:bg-primary" />
              </div>
              <h3 className="mt-4 text-lg font-medium text-foreground">{step.title}</h3>
              <p className="mt-2 flex-1 text-sm leading-relaxed text-muted-foreground">{step.desc}</p>
              <div className="mt-5 h-px w-full shrink-0 ledgerline-gradient opacity-40" />
            </div>
          </FadeIn>
        ))}
      </div>
    </section>
  );
}
