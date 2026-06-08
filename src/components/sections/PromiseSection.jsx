import { useRef } from 'react';
import { motion, useInView } from 'framer-motion';

const EASE = [0.16, 1, 0.3, 1];

function BalanceBars({ label, count, delay }) {
  const ref = useRef(null);
  const inView = useInView(ref, { once: true, margin: '-15% 0px' });

  return (
    <div ref={ref} className="flex flex-col items-center gap-3">
      <div className="flex flex-col-reverse gap-1">
        {Array.from({ length: count }).map((_, i) => (
          <motion.div
            key={i}
            initial={{ opacity: 0, scaleX: 0.4 }}
            animate={inView ? { opacity: 1, scaleX: 1 } : {}}
            transition={{ duration: 0.4, ease: EASE, delay: delay + i * 0.05 }}
            className="h-3 w-20 rounded-sm sm:w-28"
            style={{ background: `hsl(178 85% 45% / ${0.35 + i * 0.1})` }}
          />
        ))}
      </div>
      <span className="font-mono text-[11px] uppercase tracking-[0.18em] text-white/55">{label}</span>
    </div>
  );
}

export default function PromiseSection() {
  return (
    <section className="dark relative overflow-hidden bg-background py-24 sm:py-32">
      <div
        className="pointer-events-none absolute inset-0 opacity-60"
        style={{ background: 'radial-gradient(50% 60% at 50% 40%, hsl(178 85% 45% / 0.12), transparent 70%)' }}
        aria-hidden="true"
      />

      <div className="relative mx-auto max-w-[1200px] px-5 text-center sm:px-8">
        <p className="font-mono text-[12px] uppercase tracking-[0.28em] text-white/50">The promise</p>
        <h2 className="mx-auto mt-5 max-w-3xl font-mono text-2xl font-medium leading-tight tracking-tight text-white sm:text-4xl">
          Σ debits = Σ credits = Σ invoices.
          <br />
          <span className="text-white/55">Every day. No exceptions.</span>
        </h2>

        <div className="mt-16 flex items-end justify-center gap-10 sm:gap-20">
          <BalanceBars label="Invoices" count={5} delay={0} />
          <BalanceBars label="Debits" count={5} delay={0.1} />
          <BalanceBars label="Credits" count={5} delay={0.2} />
        </div>

        <motion.div
          initial={{ opacity: 0.4 }}
          animate={{ opacity: [0.4, 1, 0.4] }}
          transition={{ duration: 3, repeat: Infinity, ease: 'easeInOut' }}
          className="mt-14 inline-flex items-center gap-2 rounded-full border border-[hsl(178_85%_45%/0.4)] px-5 py-2 font-mono text-sm"
          style={{ color: 'hsl(178 85% 55%)' }}
        >
          <span className="h-1.5 w-1.5 rounded-full" style={{ background: 'hsl(178 85% 55%)' }} />
          Δ = $0.00
        </motion.div>
      </div>
    </section>
  );
}
