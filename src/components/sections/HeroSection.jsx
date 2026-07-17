import { useState } from 'react';
import { motion } from 'framer-motion';
import { ArrowRight, Play } from 'lucide-react';
import HeroFloatingVisual from './HeroFloatingVisual';
import { externalLinks } from '../../data/navigation';

const EASE = [0.16, 1, 0.3, 1];
const SUPADEMO_ID = 'cmrm3tpec02v5qm3qxyu3iris';

export default function HeroSection() {
  const [tourOpen, setTourOpen] = useState(false);

  return (
    <section
      id="top"
      className="relative flex min-h-[100svh] flex-col justify-center overflow-x-hidden pb-10 pt-32 sm:min-h-0 sm:justify-start sm:pb-12 sm:pt-36"
    >
      <div className="relative z-10">
        <div className="hero-copy relative">
          <div className="hero-copy__grid pointer-events-none absolute inset-0" aria-hidden="true" />

          <div className="relative mx-auto max-w-6xl px-5 text-center sm:px-8">
            <motion.p
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.6, ease: EASE }}
              className="font-mono text-[12px] uppercase tracking-[0.28em] text-muted-foreground"
            >
              Invoice-to-payment automation
            </motion.p>

            <motion.h1
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.7, ease: EASE, delay: 0.06 }}
              className="mt-5 text-3xl font-medium leading-[1.02] tracking-[-0.04em] text-foreground sm:text-4xl md:text-5xl lg:text-6xl lg:whitespace-nowrap xl:text-[4.5rem]"
            >
              Invoice to pay,{' '}
              <span className="text-glow">fully automated.</span>
            </motion.h1>

            <motion.p
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.7, ease: EASE, delay: 0.14 }}
              className="mx-auto mt-6 max-w-5xl text-base leading-snug text-muted-foreground sm:text-lg sm:leading-snug"
            >
              Ledgerline captures every invoice, routes approvals, pays vendors in 130+ currencies,
              <br className="hidden sm:inline" />
              {' '}and reconciles to your ledger — so finance teams close the books faster with zero manual data entry.
            </motion.p>

            <motion.div
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.7, ease: EASE, delay: 0.22 }}
              className="mx-auto mt-7 flex w-full max-w-[300px] flex-col items-center justify-center gap-2.5 sm:mt-8 sm:max-w-none sm:flex-row sm:gap-3"
            >
              <a
                href={externalLinks.getStarted}
                className="group inline-flex w-full items-center justify-center gap-2 rounded-xl bg-primary px-4 py-2.5 text-[13px] font-medium text-primary-foreground shadow-md transition-transform duration-200 hover:scale-[1.02] active:scale-100 sm:w-auto sm:px-6 sm:py-3.5 sm:text-sm"
              >
                Start free tier today
                <ArrowRight className="h-3.5 w-3.5 transition-transform duration-200 group-hover:translate-x-0.5 sm:h-4 sm:w-4" />
              </a>
              <a
                href={externalLinks.demoVideo}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex w-full items-center justify-center gap-2 rounded-xl border border-border bg-card/40 px-4 py-2.5 text-[13px] text-foreground hover-elevate active-elevate-2 sm:w-auto sm:px-6 sm:py-3.5 sm:text-sm"
              >
                <Play className="h-3 w-3 fill-current sm:h-3.5 sm:w-3.5" />
                Watch 60s demo
              </a>
            </motion.div>

            <motion.p
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              transition={{ duration: 0.7, ease: EASE, delay: 0.34 }}
              className="mx-auto mt-6 max-w-2xl pb-2 font-mono text-[12px] leading-relaxed text-muted-foreground sm:text-[13px]"
            >
              Captures via WhatsApp · Viber · Email · Mobile · Pays via Stripe · Posts to Xero · QuickBooks · MYOB ·
              NetSuite
            </motion.p>
          </div>
        </div>

        {/* Exact Supademo demo size: 2880×1304 (crops their 40px embed padding) */}
        <motion.div
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.8, ease: EASE, delay: 0.28 }}
          className="relative z-10 mx-auto mt-10 w-[min(100%,90vw)] max-w-[1200px] px-4 sm:mt-12 sm:px-6"
        >
          <div
            className="relative w-full overflow-hidden rounded-2xl border border-border bg-black shadow-lg"
            style={{ aspectRatio: '2880 / 1304', maxHeight: '80vh' }}
          >
            {tourOpen ? (
              <iframe
                src={`https://app.supademo.com/embed/${SUPADEMO_ID}?embed_v=2`}
                title="Ledgerline interactive product tour"
                allow="clipboard-write"
                allowFullScreen
                className="absolute left-0 w-full border-0"
                style={{ top: '-40px', height: 'calc(100% + 80px)' }}
              />
            ) : (
              <button
                type="button"
                onClick={() => setTourOpen(true)}
                className="group absolute inset-0 h-full w-full overflow-hidden text-left outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-primary/60"
                aria-label="Try the interactive product tour"
              >
                <img
                  src={`https://app.supademo.com/api/demo/${SUPADEMO_ID}/image`}
                  alt="Ledgerline interactive product tour preview"
                  className="absolute inset-0 h-full w-full object-cover"
                  loading="lazy"
                  decoding="async"
                />
                <div className="absolute inset-0 bg-black/40" aria-hidden="true" />
                <div className="absolute inset-0 flex items-center justify-center">
                  <span className="inline-flex items-center gap-2 rounded-full bg-white px-5 py-2.5 text-sm font-semibold text-zinc-900 shadow-lg transition-transform duration-200 group-hover:scale-105 sm:px-6 sm:py-3 sm:text-[15px]">
                    <Play className="h-3.5 w-3.5 fill-current text-zinc-900 sm:h-4 sm:w-4" />
                    Try the tour
                  </span>
                </div>
              </button>
            )}
          </div>
        </motion.div>

        <HeroFloatingVisual />
      </div>
    </section>
  );
}
