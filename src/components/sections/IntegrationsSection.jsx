import FadeIn from '../ui/FadeIn';
import SectionLabel from '../ui/SectionLabel';
import SectionTitle from '../ui/SectionTitle';
import { integrations } from '../../data/sections';

export default function IntegrationsSection() {
  return (
    <section className="mx-auto max-w-[1200px] px-5 py-20 sm:px-8 sm:py-28">
      <FadeIn>
        <SectionLabel>Integrations</SectionLabel>
        <SectionTitle className="mt-4">Captures from where work happens. Posts to where money lives.</SectionTitle>
      </FadeIn>

      <div className="mt-12 grid grid-cols-2 gap-px overflow-hidden rounded-2xl border border-card-border bg-card-border sm:grid-cols-3 lg:grid-cols-4">
        {integrations.map((name, i) => (
          <FadeIn key={name} delay={i * 0.03}>
            <div className="group flex flex-col items-center justify-center gap-3 bg-card px-4 py-9 hover-elevate">
              <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-primary/10 font-mono text-[10px] font-medium text-primary">
                {name.slice(0, 2).toUpperCase()}
              </div>
              <span className="text-sm text-muted-foreground">{name}</span>
            </div>
          </FadeIn>
        ))}
      </div>
    </section>
  );
}
