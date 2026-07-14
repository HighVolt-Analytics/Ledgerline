import { useCallback, useEffect, useRef, useState } from 'react';
import {
  BadgeCheck,
  Check,
  ChevronLeft,
  ChevronRight,
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

const CARD_GAP = 16;
const CARD_COUNT = bentoSteps.length;
const AUTO_MS = 3500;
const TRANSITION_MS = 800;

function BentoCell({ step, Icon }) {
  const graphicConfig = getBentoGraphicConfig(step.title);
  const Graphic = graphicConfig?.component;
  const isImageCard = graphicConfig?.type === 'image';

  return (
    <div className="bento-carousel-card shrink-0">
      <div className="group relative flex h-full flex-col overflow-hidden rounded-2xl border border-card-border bg-card transition-colors duration-300 hover:bg-[hsl(220_25%_8%)]">
        <div
          className="pointer-events-none absolute inset-0 opacity-80"
          style={{
            background:
              'radial-gradient(ellipse 70% 55% at 100% 0%, hsl(var(--primary) / 0.09), transparent 50%)',
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

        <div className="relative z-10 flex min-h-0 flex-1 flex-col p-5 sm:p-6">
          <div className="flex items-start justify-between gap-3">
            <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl border border-primary/25 bg-primary/10 text-primary shadow-[0_0_20px_hsl(var(--primary)/0.12)] transition-all duration-300 group-hover:border-primary/40 group-hover:bg-primary/15">
              <Icon className="h-4 w-4" strokeWidth={1.75} aria-hidden="true" />
            </span>
            <span className="rounded-md border border-primary/20 bg-primary/5 px-2 py-0.5 font-mono text-[11px] font-medium text-primary">
              {step.n}
            </span>
          </div>

          <h3 className="mt-4 shrink-0 text-base font-medium tracking-[-0.02em] text-foreground transition-colors group-hover:text-foreground sm:text-[17px]">
            {step.title}
          </h3>
          <p className="mt-2 shrink-0 text-sm leading-relaxed text-muted-foreground">{step.desc}</p>

          {isImageCard && Graphic ? (
            <>
              <div className="min-h-0 flex-1" aria-hidden="true" />
              <div className="bento-card-graphic bento-card-graphic--image">
                <Graphic />
              </div>
            </>
          ) : Graphic ? (
            <div className="bento-card-graphic mt-4 min-h-0 flex-1">
              <Graphic />
            </div>
          ) : (
            <div className="flex-1" />
          )}

          <div className="bento-card-footer">
            <div className="h-px w-full shrink-0 ledgerline-gradient opacity-25 transition-opacity duration-300 group-hover:opacity-55" />
          </div>
        </div>
      </div>
    </div>
  );
}

function LifecycleCarousel() {
  const viewportRef = useRef(null);
  const trackRef = useRef(null);
  const pausedRef = useRef(false);
  const [index, setIndex] = useState(0);
  const [stepPx, setStepPx] = useState(316);
  const [instant, setInstant] = useState(false);

  const measure = useCallback(() => {
    const track = trackRef.current;
    const firstCard = track?.firstElementChild;
    if (!firstCard) return;
    setStepPx(firstCard.getBoundingClientRect().width + CARD_GAP);
  }, []);

  useEffect(() => {
    measure();
    const viewport = viewportRef.current;
    if (!viewport || typeof ResizeObserver === 'undefined') return undefined;
    const observer = new ResizeObserver(measure);
    observer.observe(viewport);
    return () => observer.disconnect();
  }, [measure]);

  // Seamless loop: after animating onto the duplicated first card, snap back to real first.
  useEffect(() => {
    if (index < CARD_COUNT) return undefined;

    const timer = window.setTimeout(() => {
      setInstant(true);
      setIndex(0);
      requestAnimationFrame(() => {
        requestAnimationFrame(() => setInstant(false));
      });
    }, TRANSITION_MS);

    return () => window.clearTimeout(timer);
  }, [index]);

  // Auto-advance one card at a time.
  useEffect(() => {
    const reduced =
      typeof window !== 'undefined' &&
      window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (reduced) return undefined;

    const timer = window.setInterval(() => {
      if (pausedRef.current) return;
      setIndex((current) => current + 1);
    }, AUTO_MS);

    return () => window.clearInterval(timer);
  }, []);

  const goNext = () => setIndex((current) => current + 1);

  const goPrev = () => {
    if (index === 0) {
      setInstant(true);
      setIndex(CARD_COUNT);
      requestAnimationFrame(() => {
        requestAnimationFrame(() => {
          setInstant(false);
          setIndex(CARD_COUNT - 1);
        });
      });
      return;
    }
    setIndex((current) => current - 1);
  };

  const loopSteps = [...bentoSteps, ...bentoSteps];

  return (
    <div
      className="mt-14"
      onMouseEnter={() => {
        pausedRef.current = true;
      }}
      onMouseLeave={() => {
        pausedRef.current = false;
      }}
    >
      <div className="mb-5 flex items-center justify-end gap-2">
        <button
          type="button"
          onClick={goPrev}
          className="flex h-10 w-10 items-center justify-center rounded-full border border-card-border bg-card text-foreground transition-colors hover:bg-muted"
          aria-label="Previous lifecycle stage"
        >
          <ChevronLeft className="h-5 w-5" strokeWidth={2} />
        </button>
        <button
          type="button"
          onClick={goNext}
          className="flex h-10 w-10 items-center justify-center rounded-full border border-card-border bg-primary text-primary-foreground transition-colors hover:bg-primary/90"
          aria-label="Next lifecycle stage"
        >
          <ChevronRight className="h-5 w-5" strokeWidth={2} />
        </button>
      </div>

      <div ref={viewportRef} className="bento-carousel-bleed overflow-hidden">
        <div
          ref={trackRef}
          className={`bento-carousel-track flex gap-4 px-5 sm:px-8 ${instant ? 'bento-carousel-track--instant' : ''}`}
          style={{ transform: `translate3d(-${index * stepPx}px, 0, 0)` }}
        >
          {loopSteps.map((step, i) => (
            <BentoCell key={`${step.n}-${i}`} step={step} Icon={bentoIcons[i % CARD_COUNT]} />
          ))}
        </div>
      </div>
    </div>
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

      <LifecycleCarousel />

      <div className="mt-20 lg:mt-24">
        <LifecycleScrollSection />
      </div>
    </section>
  );
}
