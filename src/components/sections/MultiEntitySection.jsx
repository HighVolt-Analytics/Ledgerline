import { ArrowRight, Layers } from 'lucide-react';
import FadeIn from '../ui/FadeIn';
import SectionLabel from '../ui/SectionLabel';
import SectionTitle from '../ui/SectionTitle';
import { entities } from '../../data/sections';

const BUBBLES = [
  {
    entity: entities[0],
    variant: 'primary',
    positionClass: 'multi-entity-bubble-pos-primary',
    paddingClass: 'px-5',
    amountClass: 'text-[1.65rem] font-extralight leading-none tracking-[-0.05em]',
    labelClass: 'mt-2 text-[0.8rem] font-extralight leading-tight opacity-90',
    showArrow: true,
  },
  {
    entity: entities[1],
    variant: 'glass',
    positionClass: 'multi-entity-bubble-pos-secondary',
    paddingClass: 'px-4',
    amountClass: 'text-[1.4rem] font-extralight leading-none tracking-[-0.04em] text-white',
    labelClass: 'mt-1.5 text-[0.68rem] font-extralight leading-tight text-white/80',
    showArrow: false,
  },
  {
    entity: entities[2],
    variant: 'glass',
    positionClass: 'multi-entity-bubble-pos-tertiary',
    paddingClass: 'px-3',
    amountClass: 'text-[0.72rem] font-extralight leading-[1.08] tracking-[-0.03em] text-white',
    labelClass: 'mt-1 text-[0.55rem] font-extralight leading-tight text-white/75',
    showArrow: false,
  },
];

function EntityBubble({ entity, variant, positionClass, paddingClass, amountClass, labelClass, showArrow }) {
  const amount = `${entity.sym}${entity.total}`;
  const label = entity.name.split(' ')[0];
  const bubbleClass =
    variant === 'primary'
      ? `multi-entity-bubble-primary ${positionClass} ${paddingClass} flex flex-col items-center justify-center rounded-full box-border`
      : `multi-entity-bubble-glass ${positionClass} ${paddingClass} flex flex-col items-center justify-center rounded-full box-border`;

  return (
    <div className={bubbleClass} style={{ fontFamily: "'Inter', system-ui, sans-serif" }}>
      {showArrow && (
        <ArrowRight className="mb-2 h-4 w-4 opacity-80" strokeWidth={1.25} aria-hidden="true" />
      )}
      <span className={amountClass}>{amount}</span>
      <span className={labelClass}>{label}</span>
    </div>
  );
}

export default function MultiEntitySection() {
  return (
    <section className="mx-auto max-w-[1200px] px-5 py-20 sm:px-8 sm:py-28">
      <FadeIn>
        <div className="multi-entity-showcase">
          <div className="relative flex min-h-[400px] items-center justify-center bg-black px-6 py-12 lg:min-h-0 lg:px-10 lg:py-14">
            <div
              className="multi-entity-stats-icon-gradient absolute left-8 top-8 grid h-10 w-10 place-items-center rounded-xl"
              aria-hidden="true"
            >
              <Layers className="h-4 w-4" strokeWidth={1.25} />
            </div>

            <div className="relative mx-auto h-[320px] w-full max-w-[380px] sm:h-[340px]">
              {BUBBLES.map((bubble) => (
                <EntityBubble key={bubble.entity.name} {...bubble} />
              ))}
            </div>
          </div>

          <div className="multi-entity-content-panel">
            <div className="multi-entity-window-dots" aria-hidden="true">
              <span />
              <span />
              <span />
            </div>

            <SectionLabel>Multi-entity</SectionLabel>
            <SectionTitle className="mt-4">
              Three orgs.
              <br />
              Three currencies.
              <br />
              One login.
            </SectionTitle>
            <p className="mt-5 max-w-md text-base leading-relaxed text-muted-foreground sm:text-lg">
              Switch between entities without re-authenticating. Each org carries its own ledger map, tax regime,
              approval policy, and base currency — fully isolated, centrally governed.
            </p>

            <div className="multi-entity-featured-stat">
              <div className="flex items-baseline gap-2">
                <span className="multi-entity-featured-value tabular">3</span>
                <span className="multi-entity-featured-label">Entities</span>
              </div>
              <div className="multi-entity-progress" role="presentation">
                <div className="multi-entity-progress-fill" style={{ width: '100%' }} />
              </div>
              <p className="mt-2 font-mono text-[10px] uppercase tracking-[0.16em] text-muted-foreground">
                One login · fully isolated
              </p>
            </div>
          </div>
        </div>
      </FadeIn>
    </section>
  );
}
