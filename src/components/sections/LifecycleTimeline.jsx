import { useRef } from 'react';
import {
  Calendar,
  CheckCircle2,
  CreditCard,
  Send,
} from 'lucide-react';
import { motion, useScroll, useSpring, useTransform } from 'framer-motion';
import { lifecycleSteps } from '../../data/sections';

const timelineSteps = lifecycleSteps.slice(10);

const timelineIcons = {
  Scheduled: Calendar,
  Paid: CreditCard,
  Posted: Send,
  Reconciled: CheckCircle2,
};

function TimelineDot({ progress, revealAt, alwaysOn }) {
  const opacity = useTransform(
    progress,
    alwaysOn ? [0, 0.05] : [revealAt - 0.02, revealAt + 0.07],
    alwaysOn ? [1, 1] : [0, 1],
  );
  const scale = useTransform(
    progress,
    alwaysOn ? [0, 0.05] : [revealAt - 0.02, revealAt + 0.07],
    alwaysOn ? [1, 1] : [0.35, 1],
  );

  return (
    <motion.span
      className="block h-3 w-3 shrink-0 rounded-full bg-primary shadow-[0_0_16px_hsl(var(--primary)/0.9),0_0_6px_hsl(var(--primary)/0.55)]"
      style={{ opacity, scale }}
      aria-hidden="true"
    />
  );
}

function TimelineRow({ step, index, total, progress }) {
  const Icon = timelineIcons[step.title] || CheckCircle2;
  const segment = 1 / total;
  const start = Math.max(0, index * segment - segment * 0.1);
  const end = Math.min(1, start + segment * 0.85);

  const opacity = useTransform(progress, [start, end], [0, 1]);
  const y = useTransform(progress, [start, end], [28, 0]);
  const scale = useTransform(progress, [start, end], [0.98, 1]);

  return (
    <div className="grid grid-cols-[24px_minmax(0,1fr)] items-start gap-x-5 sm:gap-x-6">
      <div className="flex justify-center pt-5 sm:pt-6">
        <div className="flex h-10 items-center justify-center">
          <TimelineDot progress={progress} revealAt={start} alwaysOn={index === 0} />
        </div>
      </div>

      <motion.div style={{ opacity, y, scale }}>
        <div className="rounded-xl border border-card-border bg-card p-5 shadow-[0_8px_32px_rgba(0,0,0,0.35)] sm:p-6">
          <div className="flex items-start gap-4">
            <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg border border-primary/40 bg-primary text-primary-foreground">
              <Icon className="h-5 w-5" strokeWidth={2} aria-hidden="true" />
            </span>
            <div>
              <div className="flex items-baseline gap-3">
                <span className="font-mono text-xs text-primary">{step.n}</span>
                <h3 className="text-lg font-medium text-foreground">{step.title}</h3>
              </div>
              <p className="mt-2 text-sm leading-relaxed text-muted-foreground">{step.desc}</p>
            </div>
          </div>
        </div>
      </motion.div>
    </div>
  );
}

export default function LifecycleTimeline() {
  const containerRef = useRef(null);

  const { scrollYProgress } = useScroll({
    target: containerRef,
    offset: ['start 0.88', 'end 0.42'],
  });

  const progress = useSpring(scrollYProgress, {
    stiffness: 65,
    damping: 26,
    mass: 0.4,
    restDelta: 0.0008,
  });

  const lineScale = useTransform(progress, [0, 1], [0, 1]);

  return (
    <div ref={containerRef} className="relative">
      <div className="pointer-events-none absolute bottom-0 left-3 top-0 w-0 -translate-x-1/2" aria-hidden="true">
        <div className="absolute left-0 top-10 h-[calc(100%-2.5rem)] w-[2px] -translate-x-1/2 rounded-full bg-primary/15" />

        <motion.div
          className="absolute left-0 top-10 w-[2px] origin-top -translate-x-1/2 rounded-full bg-gradient-to-b from-primary via-primary/70 to-primary/0 shadow-[0_0_12px_hsl(var(--primary)/0.5)]"
          style={{
            height: 'calc(100% - 2.5rem)',
            scaleY: lineScale,
          }}
        />
      </div>

      <div className="space-y-8 sm:space-y-10">
        {timelineSteps.map((step, i) => (
          <TimelineRow
            key={step.n}
            step={step}
            index={i}
            total={timelineSteps.length}
            progress={progress}
          />
        ))}
      </div>
    </div>
  );
}
