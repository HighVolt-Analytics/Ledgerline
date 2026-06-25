import { useRef } from 'react';
import {
  ArrowRight,
  Calendar,
  CheckCircle2,
  CreditCard,
  Plus,
  Send,
} from 'lucide-react';
import { motion, useScroll, useTransform } from 'framer-motion';
import { lifecycleSteps } from '../../data/sections';

const timelineSteps = lifecycleSteps.slice(10);
const STEP_COUNT = timelineSteps.length;
const COLUMN_HEIGHT = 'h-[min(80vh,720px)]';
const SCROLL_VH_PER_STEP = 50;

const timelineIcons = {
  Scheduled: Calendar,
  Paid: CreditCard,
  Posted: Send,
  Reconciled: CheckCircle2,
};

const erpLogos = [
  { abbr: 'Xe', className: 'bg-[#13B5EA]/20 text-[#13B5EA]' },
  { abbr: 'qb', className: 'bg-[#2CA01C]/20 text-[#2CA01C]' },
  { abbr: 'My', className: 'bg-[#6D2077]/20 text-[#B565D8]' },
  { abbr: 'N', className: 'bg-[#E87722]/20 text-[#E87722]' },
];

function LeftTrustCard() {
  return (
    <div className="rounded-2xl border border-card-border bg-card p-6 shadow-[0_12px_40px_rgba(0,0,0,0.35)] sm:p-7">
      <div className="flex items-center">
        {erpLogos.map(({ abbr, className }) => (
          <span
            key={abbr}
            className={`flex h-10 w-10 items-center justify-center rounded-full border-2 border-card font-mono text-[10px] font-medium ${className} -ml-2 first:ml-0`}
          >
            {abbr}
          </span>
        ))}
        <span className="-ml-2 flex h-10 w-10 items-center justify-center rounded-full border-2 border-card bg-muted text-foreground">
          <Plus className="h-4 w-4" strokeWidth={2} aria-hidden="true" />
        </span>
      </div>
      <p className="mt-5 text-base font-medium leading-snug tracking-[-0.01em] text-foreground sm:text-lg">
        Posts to Xero, QuickBooks,
        <br />
        MYOB &amp; NetSuite
      </p>
      <button
        type="button"
        className="group mt-6 inline-flex items-center gap-2 rounded-full bg-primary px-5 py-2.5 text-sm font-medium text-primary-foreground shadow-[0_0_24px_hsl(var(--primary)/0.25)] transition-transform duration-200 hover:scale-[1.02] active:scale-100"
      >
        Start free — 500 documents
        <ArrowRight className="h-4 w-4 transition-transform duration-200 group-hover:translate-x-0.5" />
      </button>
    </div>
  );
}

function TimelineDot({ progress, segmentStart, segmentEnd, alwaysOn }) {
  const popEnd = segmentStart + (segmentEnd - segmentStart) * 0.35;
  const opacity = useTransform(
    progress,
    alwaysOn ? [0, 1] : [segmentStart, popEnd],
    alwaysOn ? [1, 1] : [0, 1],
  );
  const scale = useTransform(
    progress,
    alwaysOn ? [0, 1] : [segmentStart, popEnd],
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
  const segmentStart = index / total;
  const segmentEnd = (index + 1) / total;

  const opacity = useTransform(
    progress,
    [segmentStart, segmentEnd, 1],
    [index === 0 ? 1 : 0, 1, 1],
  );
  const y = useTransform(progress, [segmentStart, segmentEnd], [12, 0]);
  const scale = useTransform(progress, [segmentStart, segmentEnd], [0.99, 1]);

  return (
    <div className="grid h-full grid-cols-[24px_minmax(0,1fr)] items-center gap-x-5 sm:gap-x-6">
      <div className="flex h-full items-center justify-center">
        <TimelineDot
          progress={progress}
          segmentStart={segmentStart}
          segmentEnd={segmentEnd}
          alwaysOn={index === 0}
        />
      </div>

      <motion.div className="min-w-0" style={{ opacity, y, scale }}>
        <div className="rounded-xl border border-card-border bg-card p-4 shadow-[0_8px_32px_rgba(0,0,0,0.35)] sm:p-5">
          <div className="flex items-start gap-3 sm:gap-4">
            <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-primary/40 bg-primary text-primary-foreground sm:h-10 sm:w-10">
              <Icon className="h-4 w-4 sm:h-5 sm:w-5" strokeWidth={2} aria-hidden="true" />
            </span>
            <div className="min-w-0">
              <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5 sm:gap-x-3">
                <span className="font-mono text-xs text-primary">{step.n}</span>
                <h3 className="text-base font-medium text-foreground sm:text-lg">{step.title}</h3>
              </div>
              <p className="mt-1.5 text-sm leading-relaxed text-muted-foreground">{step.desc}</p>
            </div>
          </div>
        </div>
      </motion.div>
    </div>
  );
}

function ScrollingTimeline({ progress }) {
  const lineScale = useTransform(progress, [0, 1], [0.08, 1]);

  return (
    <div className={`relative ${COLUMN_HEIGHT}`}>
      <div className="pointer-events-none absolute bottom-4 left-3 top-4 w-0 -translate-x-1/2" aria-hidden="true">
        <div className="absolute left-0 top-0 h-full w-[2px] -translate-x-1/2 rounded-full bg-primary/15" />
        <motion.div
          className="absolute left-0 top-0 w-[2px] origin-top -translate-x-1/2 rounded-full bg-gradient-to-b from-primary via-primary/70 to-primary/30 shadow-[0_0_12px_hsl(var(--primary)/0.5)]"
          style={{ height: '100%', scaleY: lineScale }}
        />
      </div>

      <div className="flex h-full flex-col justify-between py-1">
        {timelineSteps.map((step, i) => (
          <div key={step.n} className="min-h-0 flex-1 py-1 first:pt-0 last:pb-0">
            <TimelineRow step={step} index={i} total={STEP_COUNT} progress={progress} />
          </div>
        ))}
      </div>
    </div>
  );
}

export default function LifecycleScrollSection() {
  const containerRef = useRef(null);

  const { scrollYProgress } = useScroll({
    target: containerRef,
    offset: ['start start', 'end start'],
  });

  const scrollHeightVh = (STEP_COUNT - 1) * SCROLL_VH_PER_STEP + 100;

  return (
    <div
      ref={containerRef}
      className="relative"
      style={{ height: `${scrollHeightVh}vh` }}
    >
      <div className="sticky top-0 flex h-screen items-center">
        <div className="mx-auto grid w-full max-w-[1200px] grid-cols-1 items-stretch gap-10 px-5 sm:px-8 lg:grid-cols-2 lg:gap-16">
          <div className={`flex flex-col justify-between ${COLUMN_HEIGHT}`}>
            <div>
              <h3 className="text-2xl font-medium leading-tight tracking-[-0.03em] text-foreground sm:text-3xl lg:text-4xl">
                From schedule to reconciliation
              </h3>
              <p className="mt-4 max-w-md text-base leading-relaxed text-muted-foreground">
                Once approved, payments execute on your timeline — then post to your ledger and reconcile automatically.
                No manual journal entries. No end-of-month surprises.
              </p>
            </div>

            <div className="mt-8 lg:mt-0">
              <LeftTrustCard />
            </div>
          </div>

          <ScrollingTimeline progress={scrollYProgress} />
        </div>
      </div>
    </div>
  );
}
