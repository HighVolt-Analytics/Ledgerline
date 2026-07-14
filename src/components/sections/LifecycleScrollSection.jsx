import { useEffect, useState } from 'react';
import {
  ArrowRight,
  Calendar,
  CheckCircle2,
  CreditCard,
  Plus,
  Send,
} from 'lucide-react';
import { externalLinks } from '../../data/navigation';

const featurePoints = [
  {
    title: 'Scheduled',
    text: 'Approved payments queue for execution on the date you choose.',
    icon: Calendar,
  },
  {
    title: 'Paid',
    text: 'Funds execute via Stripe wallet with idempotent double-pay protection.',
    icon: CreditCard,
  },
  {
    title: 'Posted',
    text: 'Journal entries write to Xero, QuickBooks, MYOB, and NetSuite.',
    icon: Send,
  },
  {
    title: 'Reconciled',
    text: 'Daily batch proves Δ = 0 across debits, credits, invoices, and payments.',
    icon: CheckCircle2,
  },
];

const erpLogos = [
  { abbr: 'Xe', className: 'bg-[#13B5EA]/20 text-[#13B5EA]' },
  { abbr: 'qb', className: 'bg-[#2CA01C]/20 text-[#2CA01C]' },
  { abbr: 'My', className: 'bg-[#6D2077]/20 text-[#B565D8]' },
  { abbr: 'N', className: 'bg-[#E87722]/20 text-[#E87722]' },
];

const visualSlides = [
  {
    src: '/feature%20images/scheduled.png',
    alt: 'Payment scheduled for execution',
    fit: 'cover',
  },
  {
    src: '/feature%20images/paid.png?v=2',
    alt: 'Payment paid and settled',
    fit: 'contain',
    blend: 'paid',
  },
  {
    src: '/feature%20images/POSTED.png',
    alt: 'Payment posted to ledger',
    fit: 'cover',
    blend: 'posted',
  },
  {
    src: '/feature%20images/RECONCILE.png',
    alt: 'Payment reconciled',
    fit: 'cover',
    blend: 'reconcile',
  },
];

const SLIDE_MS = 4000;
const SLIDE_DURATION_MS = 800;

function LifecycleVisual() {
  const [index, setIndex] = useState(0);
  const [instant, setInstant] = useState(false);
  const slideCount = visualSlides.length;
  // Duplicate first slide at the end so loop can slide into it, then snap.
  const trackSlides = [...visualSlides, visualSlides[0]];

  useEffect(() => {
    visualSlides.forEach((slide) => {
      const img = new Image();
      img.src = slide.src;
    });
  }, []);

  useEffect(() => {
    const reduced =
      typeof window !== 'undefined' &&
      window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (reduced) return undefined;

    const timer = window.setInterval(() => {
      setIndex((current) => current + 1);
    }, SLIDE_MS);

    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    if (index < slideCount) return undefined;

    const timer = window.setTimeout(() => {
      setInstant(true);
      setIndex(0);
      requestAnimationFrame(() => {
        requestAnimationFrame(() => setInstant(false));
      });
    }, SLIDE_DURATION_MS);

    return () => window.clearTimeout(timer);
  }, [index, slideCount]);

  return (
    <div className="lifecycle-visual-card relative h-full min-h-[300px] overflow-hidden rounded-[1.75rem] border border-card-border shadow-[0_24px_64px_rgba(0,0,0,0.35)] sm:min-h-[360px]">
      <div className="lifecycle-showcase-dots pointer-events-none absolute inset-0 z-0" aria-hidden="true" />

      <div className="lifecycle-visual-viewport absolute inset-0 z-10 overflow-hidden">
        <div
          className={`lifecycle-visual-track flex h-full ${instant ? 'lifecycle-visual-track--instant' : ''}`}
          style={{
            width: `${trackSlides.length * 100}%`,
            transform: `translate3d(-${(index * 100) / trackSlides.length}%, 0, 0)`,
          }}
        >
          {trackSlides.map((slide, i) => (
            <div
              key={`${slide.src}-${i}`}
              className="lifecycle-visual-slide flex h-full shrink-0 items-center justify-center overflow-hidden"
              style={{ width: `${100 / trackSlides.length}%` }}
            >
              <img
                src={slide.src}
                alt={slide.alt}
                className={
                  slide.blend === 'posted' || slide.blend === 'reconcile'
                    ? 'lifecycle-visual-img--posted'
                    : slide.blend === 'paid'
                      ? 'lifecycle-visual-img--paid'
                      : 'h-full w-full object-cover object-center'
                }
                draggable={false}
              />
            </div>
          ))}
        </div>
      </div>

      <div className="lifecycle-visual-fade pointer-events-none absolute inset-0 z-20" aria-hidden="true" />
    </div>
  );
}

function FeaturePoint({ point }) {
  const Icon = point.icon;

  return (
    <div className="lifecycle-feature-point flex items-start gap-3 rounded-xl border border-card-border bg-muted/40 px-3.5 py-3.5 sm:gap-3.5 sm:px-4">
      <span className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-primary text-primary-foreground shadow-[0_0_18px_hsl(var(--primary)/0.28)]">
        <Icon className="h-4 w-4" strokeWidth={2} aria-hidden="true" />
      </span>
      <div className="min-w-0">
        <p className="text-xs font-medium leading-snug tracking-[-0.01em] text-foreground">{point.title}</p>
        <p className="mt-0.5 text-xs leading-snug text-muted-foreground">{point.text}</p>
      </div>
    </div>
  );
}

function ErpPostsCard() {
  return (
    <div className="rounded-2xl border border-card-border bg-card p-5 shadow-[0_12px_40px_rgba(0,0,0,0.35)] sm:p-6">
      <div className="flex items-center">
        {erpLogos.map(({ abbr, className }) => (
          <span
            key={abbr}
            className={`-ml-2 flex h-10 w-10 first:ml-0 items-center justify-center rounded-full border-2 border-card font-mono text-[10px] font-medium ${className}`}
          >
            {abbr}
          </span>
        ))}
        <span className="-ml-2 flex h-10 w-10 items-center justify-center rounded-full border-2 border-card bg-muted text-foreground">
          <Plus className="h-4 w-4" strokeWidth={2} aria-hidden="true" />
        </span>
      </div>
      <p className="mt-4 text-sm leading-relaxed text-muted-foreground">
        Posts to Xero, QuickBooks, MYOB &amp; NetSuite
      </p>
    </div>
  );
}

export default function LifecycleScrollSection() {
  return (
    <div className="grid grid-cols-1 items-stretch gap-10 lg:grid-cols-2 lg:gap-14">
      <LifecycleVisual />

      <div className="flex flex-col justify-center">
        <h3 className="max-w-md text-2xl font-medium leading-tight tracking-[-0.03em] text-foreground sm:text-3xl lg:text-4xl">
          From schedule to reconciliation
        </h3>

        <div className="mt-8 grid grid-cols-1 gap-3 sm:grid-cols-2 sm:gap-3.5">
          {featurePoints.map((point) => (
            <FeaturePoint key={point.title} point={point} />
          ))}
        </div>

        <div className="mt-6">
          <ErpPostsCard />
        </div>

        <a
          href={externalLinks.getStarted}
          className="group mt-6 inline-flex w-fit items-center gap-2 rounded-full bg-primary px-5 py-2.5 text-sm font-medium text-primary-foreground shadow-[0_0_24px_hsl(var(--primary)/0.25)] transition-transform duration-200 hover:scale-[1.02] active:scale-100"
        >
          Start free tier today
          <ArrowRight className="h-4 w-4 transition-transform duration-200 group-hover:translate-x-0.5" />
        </a>
      </div>
    </div>
  );
}
