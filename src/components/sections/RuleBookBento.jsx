import { useEffect, useState } from 'react';
import { motion } from 'framer-motion';
import {
  AlertTriangle,
  BookOpen,
  FileText,
  Fingerprint,
  Folder,
  Link2,
  Phone,
  Plus,
  Search,
  Sparkles,
  Tags,
  Trash2,
} from 'lucide-react';
import { ruleBookBands } from '../../data/sections';
import AnimatedCounter from '../ui/AnimatedCounter';

const EASE = [0.22, 1, 0.36, 1];
const VISUAL_CYCLE_MS = 3600;
const LOOP_EASE = 'easeInOut';

const CATEGORY_MATCH_BARS = [
  { year: '2022', base: 120, top: 48 },
  { year: '2023', base: 185, top: 72 },
  { year: '2024', base: 240, top: 110 },
  { year: '2025', base: 310, top: 145 },
  { year: '2026', base: 420, top: 198 },
];

const BAND1_VISUAL_ITEMS = [
  { icon: Search, iconBg: 'rulebook-fisheye-icon-slate', label: 'vendor.id lookup' },
  { icon: Fingerprint, iconBg: 'rulebook-fisheye-icon-sky', label: ruleBookBands[0].points[0] },
  { icon: Tags, iconBg: 'rulebook-fisheye-icon-violet', label: ruleBookBands[0].points[1] },
  { icon: Folder, iconBg: 'rulebook-fisheye-icon-emerald', label: ruleBookBands[0].points[2] },
  { icon: FileText, iconBg: 'rulebook-fisheye-icon-amber', label: 'AWS-AU → Cloud Infrastructure' },
];

const ALIAS_TILES = [
  { icon: Search, squircle: 'rulebook-squircle-dark' },
  { icon: BookOpen, squircle: 'rulebook-squircle-charcoal' },
  { icon: Phone, squircle: 'rulebook-squircle-blue' },
  { icon: Sparkles, squircle: 'rulebook-squircle-ai', text: 'AI' },
  { icon: Tags, squircle: 'rulebook-squircle-gradient' },
  { icon: Fingerprint, squircle: 'rulebook-squircle-blue' },
  { icon: Folder, squircle: 'rulebook-squircle-charcoal' },
];

function Serif({ children, className = '' }) {
  return <span className={`font-[Georgia,'Times_New_Roman',serif] ${className}`}>{children}</span>;
}

function RuleBookCardMeta({ band, dark = false, className = '' }) {
  return (
    <div
      className={`flex flex-col justify-center px-3 py-3 sm:px-4 sm:py-3.5 ${dark ? 'rulebook-bento-dark' : 'rulebook-card-meta'} ${className}`}
    >
      <span className="font-mono text-[8px] uppercase tracking-[0.16em] text-muted-foreground/60">
        Band {band.n} · {band.headerValue}
      </span>
      <h3 className="mt-1 text-sm font-medium leading-snug tracking-[-0.02em] text-foreground sm:text-base">
        <Serif>{band.name}</Serif>
      </h3>
      <p className="mt-1 text-[11px] leading-relaxed text-muted-foreground">{band.points[0]}</p>
    </div>
  );
}

function VisualPane({ children, className = '', align = 'center', fill = false }) {
  const alignClass = fill
    ? 'items-stretch justify-stretch'
    : align === 'bottom'
      ? 'items-end justify-center pb-3 pt-1'
      : 'items-center justify-center';

  return (
    <div
      className={`rulebook-bento-light flex min-h-0 overflow-hidden ${fill ? 'h-full p-0' : 'px-2 py-2 sm:px-3'} ${alignClass} ${className}`}
    >
      <div className={`rulebook-visual-stack ${fill ? 'h-full w-full' : 'mx-auto w-full'}`}>{children}</div>
    </div>
  );
}

function RuleBookSplitCard({ band, dark = false, visual, visualFill = false }) {
  return (
    <article className="group flex h-full min-h-0 flex-col sm:flex-row">
      <RuleBookCardMeta band={band} dark={dark} className="shrink-0 sm:w-[52%] sm:border-r sm:border-card-border" />
      <VisualPane className="min-h-[180px] flex-1 sm:min-h-0 sm:w-[48%]" align="right" fill={visualFill}>
        {visual}
      </VisualPane>
    </article>
  );
}

function SquircleTile({ icon: Icon, squircle, text }) {
  return (
    <div className={`rulebook-squircle rulebook-squircle-sm shrink-0 ${squircle}`}>
      {text ? (
        <span className="text-[9px] font-bold text-foreground">{text}</span>
      ) : (
        <Icon className="h-3.5 w-3.5 text-white" strokeWidth={1.75} />
      )}
    </div>
  );
}

function AliasMarqueeRow({ tiles, direction, className = '' }) {
  const loop = [...tiles, ...tiles, ...tiles, ...tiles];

  return (
    <div className={`received-marquee-mask overflow-hidden ${className}`}>
      <div
        className={`flex w-max gap-2 ${
          direction === 'left' ? 'received-marquee-animate-left' : 'received-marquee-animate-right'
        }`}
        style={{ animationDuration: '20s' }}
      >
        {loop.map((tile, i) => (
          <SquircleTile key={`${tile.squircle}-${i}`} {...tile} />
        ))}
      </div>
    </div>
  );
}

function Band1VendorList({ activeIndex }) {
  return (
    <div className="rulebook-vendor-list">
      {BAND1_VISUAL_ITEMS.map((item, i) => {
        const Icon = item.icon;
        const isActive = i === activeIndex;

        return (
          <motion.div
            key={item.label}
            className={`rulebook-vendor-row ${isActive ? 'rulebook-vendor-row-active' : ''}`}
            animate={{ opacity: isActive ? 1 : 0.48 }}
            transition={{ duration: 0.35, ease: EASE }}
          >
            <span className={`rulebook-fisheye-icon ${item.iconBg} h-9 w-9 shrink-0`}>
              <Icon className="h-4 w-4 text-white" strokeWidth={1.75} />
            </span>
            <span className="min-w-0 flex-1 truncate text-[12px] font-medium leading-tight text-foreground sm:text-[13px]">
              {item.label}
            </span>
          </motion.div>
        );
      })}
    </div>
  );
}

function StackedBarChart({ bars, statValue, statCaption, compact = false }) {
  const maxValue = Math.max(...bars.map((b) => b.base + b.top));
  const yTicks = [90, 68, 45, 23];
  const chartH = compact ? 96 : 108;
  const barW = compact ? 28 : 34;
  const gap = compact ? 12 : 16;
  const startX = 34;
  const baseY = compact ? 118 : 128;
  const viewH = compact ? 136 : 148;

  return (
    <div className={`rulebook-stacked-chart ${compact ? 'rulebook-stacked-chart-compact' : ''}`}>
      <div className="rulebook-stacked-chart-panel">
        <svg viewBox={`0 0 248 ${viewH}`} className="h-full w-full" preserveAspectRatio="xMidYMid meet" aria-hidden>
          {yTicks.map((tick) => {
            const y = baseY - (tick / 90) * chartH;
            return (
              <g key={tick}>
                <line x1="28" y1={y} x2="238" y2={y} className="rulebook-stacked-grid" />
                <text x="22" y={y + 3} className="rulebook-stacked-axis" textAnchor="end">
                  {tick}
                </text>
              </g>
            );
          })}

          {bars.map((bar, i) => {
            const x = startX + i * (barW + gap);
            const baseH = (bar.base / maxValue) * chartH;
            const topH = (bar.top / maxValue) * chartH;
            const baseYPos = baseY - baseH;
            const topYPos = baseYPos - topH;
            const delay = 0.12 + i * 0.08;

            return (
              <g key={bar.year}>
                <motion.rect
                  x={x}
                  width={barW}
                  rx="5"
                  className="rulebook-stacked-bar-base"
                  initial={{ y: baseY, height: 0 }}
                  animate={{ y: baseYPos, height: baseH }}
                  transition={{ delay, duration: 0.55, ease: EASE }}
                />
                <motion.rect
                  x={x}
                  width={barW}
                  rx="5"
                  className="rulebook-stacked-bar-top"
                  initial={{ y: baseYPos, height: 0 }}
                  animate={{ y: topYPos, height: topH }}
                  transition={{ delay: delay + 0.12, duration: 0.55, ease: EASE }}
                />
                {!compact && (
                  <>
                    <motion.text
                      x={x + barW / 2}
                      y={baseYPos + baseH / 2 + 3}
                      className="rulebook-stacked-label"
                      initial={{ opacity: 0 }}
                      animate={{ opacity: 1 }}
                      transition={{ delay: delay + 0.35, duration: 0.3 }}
                    >
                      ${bar.base}M
                    </motion.text>
                    <motion.text
                      x={x + barW / 2}
                      y={topYPos + topH / 2 + 3}
                      className="rulebook-stacked-label"
                      initial={{ opacity: 0 }}
                      animate={{ opacity: 1 }}
                      transition={{ delay: delay + 0.45, duration: 0.3 }}
                    >
                      ${bar.top}M
                    </motion.text>
                  </>
                )}
                <text x={x + barW / 2} y={baseY + 12} className="rulebook-stacked-year" textAnchor="middle">
                  {bar.year}
                </text>
              </g>
            );
          })}
        </svg>
      </div>

      <div className="rulebook-stacked-stat">
        <span className="rulebook-stacked-stat-icon" aria-hidden>
          <svg viewBox="0 0 16 16" className="h-3.5 w-3.5">
            <path
              d="M2 11 L6 7 L9 9 L14 4"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.5"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
        </span>
        <div>
          <p className="rulebook-stacked-stat-value">
            +<AnimatedCounter to={statValue} suffix="%" duration={1800} />
          </p>
          <p className="rulebook-stacked-stat-caption">{statCaption}</p>
        </div>
      </div>
    </div>
  );
}

/** Card 1 — vendor rows listed one after another */
export function Band1TallCard() {
  const band = ruleBookBands[0];
  const [activeVisual, setActiveVisual] = useState(0);

  useEffect(() => {
    const timer = setInterval(() => {
      setActiveVisual((i) => (i + 1) % BAND1_VISUAL_ITEMS.length);
    }, VISUAL_CYCLE_MS);
    return () => clearInterval(timer);
  }, []);

  return (
    <article className="group flex h-full min-h-0 flex-col">
      <div className="rulebook-bento-light rulebook-bento-light-tall flex min-h-0 flex-1 items-center justify-center overflow-hidden px-3 py-3 sm:px-4">
        <Band1VendorList activeIndex={activeVisual} />
      </div>
      <div className="rulebook-bento-dark shrink-0 border-t border-card-border px-3 py-3 sm:px-4 sm:py-3.5">
        <span className="font-mono text-[8px] uppercase tracking-[0.16em] text-muted-foreground/50">
          Band {band.n} · {band.headerValue}
        </span>
        <h3 className="mt-1 text-sm font-medium leading-snug text-foreground sm:text-base">
          <Serif>{band.name}</Serif>
        </h3>
        <p className="mt-1 text-[11px] leading-relaxed text-muted-foreground">{band.points[0]}</p>
      </div>
    </article>
  );
}

/** Card 2 — marquee squircle icons at bottom (Band 2) */
function AliasMarqueeGraphic() {
  return (
    <div className="-mx-2 flex w-[calc(100%+1rem)] flex-col gap-2 sm:-mx-3 sm:w-[calc(100%+1.5rem)]" aria-hidden="true">
      <AliasMarqueeRow tiles={ALIAS_TILES} direction="left" />
      <AliasMarqueeRow tiles={[...ALIAS_TILES.slice(2), ...ALIAS_TILES.slice(0, 3)]} direction="right" className="-ml-1" />
    </div>
  );
}

export function Band2GridCard() {
  const band = ruleBookBands[1];
  return (
    <article className="group flex h-full min-h-0 flex-col">
      <RuleBookCardMeta band={band} className="min-h-0 flex-1" />
      <VisualPane align="bottom" className="shrink-0">
        <AliasMarqueeGraphic />
      </VisualPane>
    </article>
  );
}

/** Card 3 — stacked bar chart on right (Band 3) */
function CategoryBarChart() {
  return (
    <div className="rulebook-graph-fill rulebook-graph-fill-bars">
      <StackedBarChart bars={CATEGORY_MATCH_BARS} statValue={68} statCaption="Keyword match rate" compact />
      <div className="rulebook-graph-foot">
        <span className="rulebook-graph-pill">/freight|courier/</span>
        <span className="rulebook-graph-foot-arrow" aria-hidden>
          →
        </span>
        <span className="rulebook-graph-pill rulebook-graph-pill-active">Logistics</span>
      </div>
    </div>
  );
}

export function Band3SplitCard() {
  const band = ruleBookBands[2];
  return <RuleBookSplitCard band={band} dark visual={<CategoryBarChart />} visualFill />;
}

/** Card 4 — fintech capsules with count-up numbers on right (Band 4) */
function ThresholdFintechVisual() {
  return (
    <div className="w-full space-y-1.5 px-0.5">
      <div className="flex gap-1.5">
        <div className="rulebook-fintech-capsule flex flex-1 items-center gap-1.5 px-2 py-1.5">
          <span className="rulebook-fintech-dot" />
          <div className="min-w-0">
            <p className="text-[7px] text-muted-foreground">Threshold</p>
            <p className="font-mono text-[9px] font-medium text-foreground">
              $<AnimatedCounter to={10000} separator duration={1600} />
            </p>
          </div>
        </div>
        <div className="rulebook-fintech-capsule flex flex-1 items-center gap-1.5 px-2 py-1.5">
          <span className="rulebook-fintech-dot rulebook-fintech-dot-warn" />
          <div className="min-w-0">
            <p className="text-[7px] text-muted-foreground">Amount</p>
            <p className="font-mono text-[9px] font-medium text-rose-400">
              $<AnimatedCounter to={10248} separator duration={2000} />
            </p>
          </div>
        </div>
      </div>
      <motion.div
        className="rulebook-fintech-earned mx-auto flex w-fit items-center gap-1 px-2.5 py-1"
        animate={{ scale: [1, 1.05, 1], opacity: [0.85, 1, 0.85] }}
        transition={{ duration: 1.8, repeat: Infinity, ease: LOOP_EASE }}
      >
        <Sparkles className="h-2.5 w-2.5 text-primary-foreground" />
        <span className="text-[8px] font-medium text-primary-foreground">Route: CFO approval</span>
      </motion.div>
      <div className="space-y-1">
        {[
          { name: 'Invoice total', cat: 'AUD', mark: 'G', counter: <AnimatedCounter to={10248} decimals={2} separator duration={2200} prefix="$" /> },
          { name: 'Policy check', cat: 'Approval', mark: 'S', counter: <span>Required</span> },
        ].map((row, i) => (
          <motion.div
            key={row.name}
            className="rulebook-fintech-row flex items-center gap-1.5 px-2 py-1.5"
            initial={{ opacity: 0, x: -4 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ delay: 0.3 + i * 0.15, duration: 0.4, ease: EASE }}
          >
            <span className="rulebook-fintech-logo">{row.mark}</span>
            <div className="min-w-0 flex-1">
              <p className="truncate text-[9px] font-medium text-foreground">{row.name}</p>
              <p className="text-[7px] text-muted-foreground">{row.cat}</p>
            </div>
            <span className="shrink-0 font-mono text-[8px] text-foreground">{row.counter}</span>
          </motion.div>
        ))}
      </div>
    </div>
  );
}

export function Band4WorkflowCard() {
  const band = ruleBookBands[3];
  return <RuleBookSplitCard band={band} dark visual={<ThresholdFintechVisual />} />;
}

/** Card 5 — workflow steps (Band 5) */
function WorkflowStepsVisual() {
  const [activeStep, setActiveStep] = useState(0);
  const steps = [
    { icon: Link2, label: 'Suspense ledger' },
    { icon: Folder, label: 'flag = review' },
    { icon: AlertTriangle, label: 'Manual queue' },
  ];

  useEffect(() => {
    const timer = setInterval(() => {
      setActiveStep((i) => (i + 1) % steps.length);
    }, 2200);
    return () => clearInterval(timer);
  }, [steps.length]);

  return (
    <div className="rulebook-workflow relative mx-auto w-full max-w-[210px]">
      <div className="rulebook-workflow-line" aria-hidden />
      <div className="relative space-y-1.5">
        {steps.map(({ icon: Icon, label }, i) => (
          <motion.div
            key={label}
            animate={{
              x: activeStep === i ? 3 : 0,
              opacity: activeStep === i ? 1 : 0.55,
              scale: activeStep === i ? 1.02 : 1,
            }}
            transition={{ duration: 0.45, ease: EASE }}
            className={`rulebook-workflow-step flex items-center gap-2 px-2.5 py-1.5 ${
              activeStep === i ? 'rulebook-workflow-step-active' : ''
            }`}
          >
            <Icon className="h-3.5 w-3.5 shrink-0 text-muted-foreground" strokeWidth={1.75} />
            <span className="min-w-0 flex-1 truncate text-[9px] font-medium text-foreground">{label}</span>
            <span className="rulebook-workflow-trash flex h-4 w-4 items-center justify-center rounded-md">
              <Trash2 className="h-2.5 w-2.5 text-muted-foreground/50" strokeWidth={1.75} />
            </span>
          </motion.div>
        ))}
      </div>
      <motion.div
        className="rulebook-flow-add mx-auto mt-1.5 flex h-6 w-6 items-center justify-center rounded-full"
        animate={{ rotate: [0, 90, 0], scale: [1, 1.1, 1] }}
        transition={{ duration: 3, repeat: Infinity, ease: LOOP_EASE }}
      >
        <Plus className="h-3 w-3 text-primary" strokeWidth={2} />
      </motion.div>
    </div>
  );
}

export function Band5ActionCard() {
  const band = ruleBookBands[4];
  return (
    <article className="group flex h-full min-h-0 flex-col">
      <RuleBookCardMeta band={band} className="min-h-0 flex-1" />
      <VisualPane align="bottom" className="shrink-0">
        <WorkflowStepsVisual />
      </VisualPane>
    </article>
  );
}

export const ruleBookBentoCards = [
  { component: Band1TallCard, layout: 'lg:col-start-1 lg:row-start-1 lg:row-span-2' },
  { component: Band2GridCard, layout: 'lg:col-start-2 lg:row-start-1' },
  { component: Band3SplitCard, layout: 'lg:col-start-3 lg:row-start-1' },
  { component: Band4WorkflowCard, layout: 'lg:col-start-2 lg:row-start-2' },
  { component: Band5ActionCard, layout: 'lg:col-start-3 lg:row-start-2' },
];
