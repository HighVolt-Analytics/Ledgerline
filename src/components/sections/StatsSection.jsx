import AnimatedCounter from '../ui/AnimatedCounter';
import FadeIn from '../ui/FadeIn';

const stats = [
  {
    render: () => <AnimatedCounter to={95} suffix="%+" />,
    label: 'First-pass classification accuracy',
  },
  {
    render: () => (
      <>
        {'<'}
        <AnimatedCounter to={30} suffix="s" />
      </>
    ),
    label: 'Invoice → posted entry',
  },
  {
    render: () => <AnimatedCounter to={6} />,
    label: 'Control gates from receipt to payment',
  },
  {
    render: () => (
      <>
        <span className="mr-1">Δ=</span>$
        <AnimatedCounter to={0} decimals={2} />
      </>
    ),
    label: 'Reconciliation Δ invariant',
  },
];

export default function StatsSection() {
  return (
    <section className="mx-auto max-w-[1200px] px-5 py-20 sm:px-8 sm:py-28">
      <div className="grid grid-cols-1 gap-x-8 gap-y-12 sm:grid-cols-2 lg:grid-cols-4">
        {stats.map((stat, i) => (
          <FadeIn key={stat.label} delay={i * 0.08} className="text-center lg:text-left">
            <div className="font-mono text-4xl font-medium tabular leading-none text-foreground sm:text-5xl lg:text-[3.5rem] xl:text-[4rem] whitespace-nowrap">
              {stat.render()}
            </div>
            <div className="mx-auto mt-4 max-w-[12rem] font-mono text-[11px] uppercase tracking-[0.18em] text-muted-foreground lg:mx-0">
              {stat.label}
            </div>
          </FadeIn>
        ))}
      </div>
    </section>
  );
}
