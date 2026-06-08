import FadeIn from '../ui/FadeIn';
import SectionLabel from '../ui/SectionLabel';
import SectionTitle from '../ui/SectionTitle';
import { entities } from '../../data/sections';

export default function MultiEntitySection() {
  return (
    <section className="mx-auto max-w-[1200px] px-5 py-20 sm:px-8 sm:py-28">
      <div className="grid grid-cols-1 items-center gap-12 lg:grid-cols-2">
        <FadeIn>
          <SectionLabel>Multi-entity</SectionLabel>
          <SectionTitle className="mt-4">
            Three orgs.
            <br />
            Three currencies.
            <br />
            One login.
          </SectionTitle>
          <p className="mt-5 max-w-md text-lg text-muted-foreground">
            Switch between entities without re-authenticating. Each org carries its own ledger map, tax regime, approval
            policy, and base currency — fully isolated, centrally governed.
          </p>
        </FadeIn>

        <div className="relative mx-auto w-full max-w-md">
          {entities.map((entity, i) => (
            <FadeIn key={entity.name} delay={i * 0.1}>
              <div
                className="group mb-[-1rem] rounded-2xl border border-card-border bg-card p-5 shadow-lg transition-transform duration-200 hover:-translate-y-2"
                style={{ position: 'relative', zIndex: entities.length - i }}
              >
                <div className="flex items-start justify-between">
                  <div>
                    <div className="text-base font-medium text-foreground">{entity.name}</div>
                    <div className="mt-1 font-mono text-[11px] uppercase tracking-[0.14em] text-muted-foreground">
                      {entity.tag}
                    </div>
                  </div>
                  <div className="font-mono text-2xl text-muted-foreground/40">{entity.sym}</div>
                </div>
                <div className="mt-4 font-mono text-xl tabular text-foreground">
                  {entity.sym}
                  {entity.total}
                </div>
              </div>
            </FadeIn>
          ))}
          <div className="h-4" />
        </div>
      </div>
    </section>
  );
}
