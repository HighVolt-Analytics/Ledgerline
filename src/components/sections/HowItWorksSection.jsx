import {
  BadgeCheck,
  Check,
  Clock,
  Fingerprint,
  GitCompare,
  Inbox,
  Link2,
  ListOrdered,
  ScanLine,
  Tags,
} from 'lucide-react';
import FadeIn from '../ui/FadeIn';
import SectionLabel from '../ui/SectionLabel';
import SectionTitle from '../ui/SectionTitle';
import LifecycleScrollSection from './LifecycleScrollSection';
import { getBentoGraphicConfig } from './BentoGraphics';
import { lifecycleSteps } from '../../data/sections';

const bentoSteps = lifecycleSteps.slice(0, 10);

const bentoIcons = [
  Inbox,
  ScanLine,
  Link2,
  Tags,
  Fingerprint,
  Clock,
  Check,
  GitCompare,
  ListOrdered,
  BadgeCheck,
];

const bentoLayout = [
  'lg:col-start-1 lg:col-end-3 lg:row-start-1 lg:row-end-3',
  'lg:col-start-3 lg:row-start-1',
  'lg:col-start-4 lg:row-start-1',
  'lg:col-start-3 lg:col-end-5 lg:row-start-2',
  'lg:col-start-1 lg:col-end-3 lg:row-start-3',
  'lg:col-start-3 lg:row-start-3',
  'lg:col-start-4 lg:row-start-3',
  'lg:col-start-1 lg:row-start-4',
  'lg:col-start-2 lg:row-start-4',
  'lg:col-start-3 lg:col-end-5 lg:row-start-4',
];

function BentoCell({ step, layout, delay, Icon }) {
  const isLarge = layout.includes('row-end-3');
  const graphicConfig = getBentoGraphicConfig(step.title);
  const Graphic = graphicConfig?.component;
  const graphicPlacement = graphicConfig?.placement ?? 'below';

  return (
    <FadeIn delay={delay} className={`h-full ${layout}`}>
      <div
        className={`group relative flex h-full flex-col overflow-hidden bg-card p-5 transition-colors duration-300 hover:bg-[hsl(220_25%_8%)] sm:p-6 ${
          isLarge ? 'min-h-[220px] lg:min-h-0' : 'min-h-[148px]'
        }`}
      >
        <div
          className="pointer-events-none absolute inset-0 opacity-80"
          style={{
            background: isLarge
              ? 'radial-gradient(ellipse 80% 60% at 100% 0%, hsl(var(--primary) / 0.14), transparent 55%), radial-gradient(ellipse 60% 50% at 0% 100%, hsl(var(--primary) / 0.06), transparent 50%)'
              : 'radial-gradient(ellipse 70% 55% at 100% 0%, hsl(var(--primary) / 0.09), transparent 50%)',
          }}
          aria-hidden="true"
        />
        <div
          className="pointer-events-none absolute inset-0 opacity-[0.35]"
          style={{
            backgroundImage:
              'linear-gradient(hsl(var(--foreground) / 0.03) 1px, transparent 1px), linear-gradient(90deg, hsl(var(--foreground) / 0.03) 1px, transparent 1px)',
            backgroundSize: '24px 24px',
          }}
          aria-hidden="true"
        />

        <div className="relative z-10 flex flex-1 flex-col">
          <div className="flex items-start justify-between gap-3">
            <span
              className={`flex shrink-0 items-center justify-center rounded-xl border border-primary/25 bg-primary/10 text-primary shadow-[0_0_20px_hsl(var(--primary)/0.12)] transition-all duration-300 group-hover:border-primary/40 group-hover:bg-primary/15 ${
                isLarge ? 'h-11 w-11' : 'h-9 w-9'
              }`}
            >
              <Icon className={isLarge ? 'h-5 w-5' : 'h-4 w-4'} strokeWidth={1.75} aria-hidden="true" />
            </span>
            <span className="rounded-md border border-primary/20 bg-primary/5 px-2 py-0.5 font-mono text-[11px] font-medium text-primary">
              {step.n}
            </span>
          </div>

          {graphicPlacement === 'center' ? (
            <>
              <h3
                className={`mt-4 font-medium tracking-[-0.02em] text-foreground transition-colors group-hover:text-foreground ${
                  isLarge ? 'text-xl sm:text-2xl' : 'text-base sm:text-[17px]'
                }`}
              >
                {step.title}
              </h3>
              <p
                className={`mt-2 max-w-md leading-relaxed text-muted-foreground ${
                  isLarge ? 'text-sm sm:text-[15px]' : 'text-sm'
                }`}
              >
                {step.desc}
              </p>
              {Graphic ? (
                <div className="relative min-h-[148px] flex-1 sm:min-h-[168px]">
                  <div className="absolute inset-0 flex items-center justify-center">
                    <Graphic />
                  </div>
                </div>
              ) : (
                <div className="flex-1" />
              )}
            </>
          ) : graphicPlacement === 'right' ? (
            <div className="mt-4 flex flex-1 flex-col gap-4 lg:flex-row lg:items-center lg:gap-5">
              <div className="min-w-0 flex-1">
                <h3
                  className={`font-medium tracking-[-0.02em] text-foreground transition-colors group-hover:text-foreground ${
                    isLarge ? 'text-xl sm:text-2xl' : 'text-base sm:text-[17px]'
                  }`}
                >
                  {step.title}
                </h3>
                <p
                  className={`mt-2 leading-relaxed text-muted-foreground ${
                    isLarge ? 'text-sm sm:text-[15px]' : 'text-sm'
                  }`}
                >
                  {step.desc}
                </p>
              </div>
              {Graphic ? (
                <div className="relative min-h-[108px] w-full shrink-0 lg:w-[54%]">
                  <Graphic />
                </div>
              ) : null}
            </div>
          ) : (
            <>
              <h3
                className={`mt-4 font-medium tracking-[-0.02em] text-foreground transition-colors group-hover:text-foreground ${
                  isLarge ? 'text-xl sm:text-2xl' : 'text-base sm:text-[17px]'
                }`}
              >
                {step.title}
              </h3>
              <p
                className={`mt-2 leading-relaxed text-muted-foreground ${
                  isLarge ? 'text-sm sm:text-[15px]' : 'text-sm'
                }`}
              >
                {step.desc}
              </p>
              {Graphic ? (
                <div className="mt-8 flex min-h-0 flex-1 flex-col justify-end pb-1 sm:mt-10">
                  <Graphic />
                </div>
              ) : null}
            </>
          )}

          <div className="mt-auto pt-5">
            <div className="h-px w-full shrink-0 ledgerline-gradient opacity-25 transition-opacity duration-300 group-hover:opacity-55" />
          </div>
        </div>
      </div>
    </FadeIn>
  );
}

export default function HowItWorksSection() {
  return (
    <section id="how" className="relative mx-auto max-w-[1200px] px-5 py-20 sm:px-8 sm:py-28">
      <FadeIn>
        <SectionLabel>The lifecycle</SectionLabel>
        <SectionTitle className="mt-4">Fourteen stages. One document.</SectionTitle>
        <p className="mt-4 max-w-xl text-lg text-muted-foreground">
          Each document — invoice, expense claim, PO, or payment — moves through the same deterministic pipeline.
          Observable at every step. Gated by six controls. Reversible until it pays.
        </p>
      </FadeIn>

      <div className="mt-14 overflow-hidden rounded-2xl border border-card-border shadow-[0_24px_80px_hsl(var(--primary)/0.06)]">
        <div className="grid grid-cols-1 gap-px bg-card-border sm:grid-cols-2 lg:grid-cols-4 lg:grid-rows-4">
          {bentoSteps.map((step, i) => (
            <BentoCell
              key={step.n}
              step={step}
              layout={bentoLayout[i]}
              delay={i * 0.04}
              Icon={bentoIcons[i]}
            />
          ))}
        </div>
      </div>

      <div className="mt-20 lg:mt-24">
        <LifecycleScrollSection />
      </div>
    </section>
  );
}
