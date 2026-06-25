import { useEffect, useState } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import FadeIn from '../ui/FadeIn';
import SectionLabel from '../ui/SectionLabel';
import SectionTitle from '../ui/SectionTitle';
import TimerRing from '../ui/TimerRing';
import { procurementRules } from '../../data/sections';
import { ProcurementVisual, procurementIcons } from './ProcurementGraphics';

const EASE = [0.22, 1, 0.36, 1];
const CYCLE_MS = 4500;
const SHOWCASE_HEIGHT = 'min-h-[520px] lg:h-[580px]';

export default function ProcurementSection() {
  const [activeIndex, setActiveIndex] = useState(0);
  const [cycleKey, setCycleKey] = useState(0);
  const activeRule = procurementRules[activeIndex];

  useEffect(() => {
    const timer = setInterval(() => {
      setActiveIndex((i) => (i + 1) % procurementRules.length);
      setCycleKey((k) => k + 1);
    }, CYCLE_MS);
    return () => clearInterval(timer);
  }, [activeIndex]);

  const handleSelect = (index) => {
    setActiveIndex(index);
    setCycleKey((k) => k + 1);
  };

  return (
    <section id="procurement" className="mx-auto max-w-[1200px] px-5 py-20 sm:px-8 sm:py-28">
      <FadeIn>
        <SectionLabel>Procurement · v4</SectionLabel>
        <SectionTitle className="mt-4">PO. GRN. Invoice. One number that has to agree.</SectionTitle>
        <p className="mt-4 max-w-xl text-lg text-muted-foreground">
          v4 adds the full purchase loop. The invoice no longer arrives alone — it arrives with a Purchase Order it has to
          match against a Goods Receipt Note. Variances above tolerance are routed, not rubber-stamped.
        </p>
      </FadeIn>

      <div className={`procurement-showcase mt-14 grid grid-cols-1 items-stretch gap-8 lg:grid-cols-2 lg:gap-10 ${SHOWCASE_HEIGHT}`}>
        <FadeIn className={`flex ${SHOWCASE_HEIGHT} flex-col`}>
          <ul
            className="flex h-full flex-col justify-between py-1"
            role="tablist"
            aria-label="Procurement match rules"
          >
            {procurementRules.map((rule, i) => {
              const Icon = procurementIcons[rule.id];
              const isActive = i === activeIndex;
              const isPast = i < activeIndex;

              return (
                <li key={rule.id} className="flex flex-1 items-center">
                  <button
                    type="button"
                    role="tab"
                    aria-selected={isActive}
                    aria-controls={`procurement-panel-${rule.id}`}
                    id={`procurement-tab-${rule.id}`}
                    onClick={() => handleSelect(i)}
                    className="flex w-full items-start gap-3 py-3 text-left transition-opacity duration-300 sm:gap-4 sm:py-4"
                  >
                    <span className="mt-1.5 shrink-0">
                      <TimerRing
                        isActive={isActive}
                        isPast={isPast}
                        durationMs={CYCLE_MS}
                        cycleKey={`${cycleKey}-${rule.id}`}
                      />
                    </span>
                    <span
                      className="grid h-10 w-10 shrink-0 place-items-center rounded-xl border border-card-border bg-muted/40 transition-colors duration-300"
                      style={
                        isActive
                          ? {
                              background: `hsl(var(--primary) / ${rule.opacity * 0.14})`,
                              borderColor: `hsl(var(--primary) / ${rule.opacity * 0.35})`,
                              color: 'hsl(var(--primary))',
                            }
                          : { color: 'hsl(var(--muted-foreground) / 0.55)' }
                      }
                    >
                      <Icon className="h-5 w-5" strokeWidth={1.75} aria-hidden="true" />
                    </span>
                    <div
                      className={`min-w-0 flex-1 pt-0.5 transition-opacity duration-300 ${
                        isActive ? 'opacity-100' : 'opacity-45'
                      }`}
                    >
                      <div
                        className={`text-base font-medium tracking-[-0.02em] transition-colors duration-300 ${
                          isActive ? 'text-foreground' : 'text-muted-foreground'
                        }`}
                      >
                        {rule.name}
                      </div>
                      <p
                        className={`mt-2 text-sm leading-relaxed transition-colors duration-300 ${
                          isActive ? 'text-muted-foreground' : 'text-muted-foreground/70'
                        }`}
                      >
                        {rule.desc}
                      </p>
                      <code
                        className={`mt-3 block font-mono text-[11px] leading-relaxed transition-colors duration-300 ${
                          isActive ? 'text-muted-foreground/80' : 'text-muted-foreground/50'
                        }`}
                      >
                        {rule.rule}
                      </code>
                    </div>
                  </button>
                </li>
              );
            })}
          </ul>
        </FadeIn>

        <FadeIn delay={0.08} className={SHOWCASE_HEIGHT}>
          <div
            className={`procurement-visual-panel ${SHOWCASE_HEIGHT} overflow-hidden`}
            role="tabpanel"
            id={`procurement-panel-${activeRule.id}`}
            aria-labelledby={`procurement-tab-${activeRule.id}`}
          >
            <AnimatePresence mode="wait">
              <motion.div
                key={activeRule.id}
                initial={{ opacity: 0, y: 16, scale: 0.97 }}
                animate={{ opacity: 1, y: 0, scale: 1 }}
                exit={{ opacity: 0, y: -10, scale: 0.98 }}
                transition={{ duration: 0.38, ease: EASE }}
                className="h-full"
              >
                <ProcurementVisual ruleId={activeRule.id} />
              </motion.div>
            </AnimatePresence>
          </div>
        </FadeIn>
      </div>
    </section>
  );
}
