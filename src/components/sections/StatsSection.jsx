import AnimatedCounter from '../ui/AnimatedCounter';
import FadeIn from '../ui/FadeIn';

const stats = [
  {
    tag: 'Classification accuracy',
    render: () => <AnimatedCounter to={95} suffix="%+" />,
    description: 'First-pass ledger assignment without manual review',
  },
  {
    tag: 'Time to post',
    render: () => (
      <>
        {'<'}
        <AnimatedCounter to={30} suffix="s" />
      </>
    ),
    description: 'From approved invoice to journal entry in your ledger',
  },
  {
    tag: 'Control gates',
    render: () => <AnimatedCounter to={6} />,
    description: 'Enforcement points from receipt through payment',
  },
  {
    tag: 'Reconciliation delta',
    render: () => (
      <>
        Δ=<AnimatedCounter to={0} prefix="$" decimals={2} />
      </>
    ),
    description: 'Daily batch proves debits, credits, and payments balance',
  },
];

function StatBlock({ tag, render, description, delay }) {
  return (
    <FadeIn delay={delay}>
      <div>
        <p className="font-mono text-[11px] uppercase tracking-[0.14em] text-muted-foreground">
          <span className="mr-1.5 text-foreground/50">•</span>
          {tag}
        </p>
        <div className="mt-3 border-t border-border" />
        <div className="mt-5 text-4xl font-medium leading-none tracking-[-0.03em] text-foreground sm:text-5xl lg:text-[3rem] xl:text-[3.25rem]">
          {render()}
        </div>
        <p className="mt-4 max-w-[15rem] text-sm leading-relaxed text-muted-foreground">{description}</p>
      </div>
    </FadeIn>
  );
}

export default function StatsSection() {
  const leftCol = [stats[0], stats[2]];
  const rightCol = [stats[1], stats[3]];

  return (
    <section className="mx-auto max-w-[1200px] px-5 py-20 sm:px-8 sm:py-28">
      <div className="grid grid-cols-1 items-center gap-12 lg:grid-cols-[minmax(0,1fr)_minmax(0,2fr)] lg:gap-0">
        <FadeIn className="lg:pr-10 xl:pr-14">
          <div className="flex items-center gap-4">
            <p className="font-mono text-[11px] uppercase tracking-[0.2em] text-muted-foreground">By the numbers</p>
            <div className="h-px flex-1 bg-border lg:hidden" />
          </div>
          <h2 className="mt-6 max-w-sm text-3xl font-medium leading-[1.1] tracking-[-0.03em] text-foreground sm:text-4xl lg:text-[2.5rem] xl:text-[2.75rem]">
            Built for finance teams that can&apos;t afford manual errors
          </h2>
          <p className="mt-5 max-w-sm text-base leading-relaxed text-muted-foreground">
            Every metric reflects how Ledgerline runs invoice-to-pay — classified, controlled, and reconciled without
            re-keying.
          </p>
        </FadeIn>

        <div className="grid grid-cols-1 border-border sm:grid-cols-2 lg:border-l lg:pl-10 xl:pl-14">
          <div className="flex flex-col gap-14 border-border sm:border-r sm:pr-10 lg:gap-16 lg:pr-12 xl:pr-14">
            {leftCol.map((stat, i) => (
              <StatBlock key={stat.tag} {...stat} delay={0.1 + i * 0.08} />
            ))}
          </div>
          <div className="mt-14 flex flex-col gap-14 sm:mt-0 sm:pl-10 lg:gap-16 lg:pl-12 xl:pl-14">
            {rightCol.map((stat, i) => (
              <StatBlock key={stat.tag} {...stat} delay={0.18 + i * 0.08} />
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}
