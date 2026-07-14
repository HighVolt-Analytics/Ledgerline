import { motion } from 'framer-motion';
import { ArrowRight, Play } from 'lucide-react';
import HeroFloatingVisual from './HeroFloatingVisual';
import { externalLinks } from '../../data/navigation';

const EASE = [0.16, 1, 0.3, 1];

export default function HeroSection() {
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
              <button className="inline-flex w-full items-center justify-center gap-2 rounded-xl border border-border bg-card/40 px-4 py-2.5 text-[13px] text-foreground hover-elevate active-elevate-2 sm:w-auto sm:px-6 sm:py-3.5 sm:text-sm">
                <Play className="h-3 w-3 fill-current sm:h-3.5 sm:w-3.5" />
                Watch 60s demo
              </button>
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

        <HeroFloatingVisual />
      </div>
    </section>
  );
}
