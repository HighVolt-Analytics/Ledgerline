import { motion } from 'framer-motion';
import { ArrowRight, Play } from 'lucide-react';
import { useTheme } from '../../context/ThemeContext';
import { themeAssets } from '../../data/assets';

const EASE = [0.16, 1, 0.3, 1];

export default function HeroSection() {
  const { theme } = useTheme();

  return (
    <section id="top" className="relative overflow-hidden px-5 pb-16 pt-28 sm:px-8 sm:pb-20 sm:pt-36">
      <div className="hero-mesh pointer-events-none absolute inset-0 -z-10" aria-hidden="true" />
      <div className="grain-grid pointer-events-none absolute inset-0 -z-10" aria-hidden="true" />

      <div className="mx-auto grid max-w-[1200px] grid-cols-1 items-center gap-12 lg:grid-cols-2 lg:gap-16">
        <div className="text-left">
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
            className="mt-5 text-4xl font-medium leading-[0.95] tracking-[-0.04em] text-foreground sm:text-5xl md:text-6xl lg:text-7xl"
          >
            Invoices in.
            <br />
            <span className="text-glow">Ledgers out.</span>
          </motion.h1>

          <motion.p
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.7, ease: EASE, delay: 0.1 }}
            className="mt-3 text-xl font-medium leading-[1.05] tracking-[-0.03em] text-muted-foreground sm:text-2xl md:text-3xl"
          >
            Payments approved. Books reconciled.
          </motion.p>

          <motion.p
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.7, ease: EASE, delay: 0.14 }}
            className="mt-6 max-w-xl text-base leading-relaxed text-muted-foreground sm:text-lg"
          >
            The deterministic AI workflow that captures expenses from any channel, runs three-way match on every PO,
            enforces multi-tier approvals, and pays approved invoices from a single Stripe wallet — then posts the
            journal to your accounting platform.
          </motion.p>

          <motion.div
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.7, ease: EASE, delay: 0.22 }}
            className="mt-8 flex flex-col gap-3 sm:flex-row sm:items-center"
          >
            <button className="group inline-flex w-full items-center justify-center gap-2 rounded-xl bg-primary px-6 py-3.5 text-sm font-medium text-primary-foreground shadow-md transition-transform duration-200 hover:scale-[1.02] active:scale-100 sm:w-auto">
              Start free — 500 documents + wallet
              <ArrowRight className="h-4 w-4 transition-transform duration-200 group-hover:translate-x-0.5" />
            </button>
            <button className="inline-flex w-full items-center justify-center gap-2 rounded-xl border border-border bg-card/40 px-6 py-3.5 text-sm text-foreground hover-elevate active-elevate-2 sm:w-auto">
              <Play className="h-3.5 w-3.5 fill-current" />
              Watch 60s demo
            </button>
          </motion.div>

          <motion.p
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ duration: 0.7, ease: EASE, delay: 0.34 }}
            className="mt-6 max-w-xl font-mono text-[12px] leading-relaxed text-muted-foreground sm:text-[13px]"
          >
            Captures via WhatsApp · Viber · Email · Mobile · Pays via Stripe · Posts to Xero · QuickBooks · MYOB ·
            NetSuite
          </motion.p>
        </div>

        <motion.div
          initial={{ opacity: 0, x: 24 }}
          animate={{ opacity: 1, x: 0 }}
          transition={{ duration: 0.9, ease: EASE, delay: 0.2 }}
          className="relative mx-auto w-full lg:mx-0"
        >
          <div
            className="pointer-events-none absolute -inset-4 -z-10 rounded-3xl opacity-60 blur-3xl"
            style={{ background: 'radial-gradient(60% 60% at 50% 50%, hsl(var(--primary) / 0.25), transparent 70%)' }}
            aria-hidden="true"
          />
          <div
            className={`relative aspect-[16/9] w-full overflow-hidden rounded-2xl ${
              theme === 'light' ? 'bg-background' : 'bg-black'
            }`}
          >
            <img
              src={themeAssets[theme].heroBg}
              alt="Invoice capture to ledger posted — automated workflow"
              className="absolute inset-0 h-full w-full scale-[1.18] object-cover object-center"
            />
          </div>
        </motion.div>
      </div>
    </section>
  );
}
