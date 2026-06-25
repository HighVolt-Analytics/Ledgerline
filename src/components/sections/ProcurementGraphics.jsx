import { useEffect, useState } from 'react';
import { motion } from 'framer-motion';
import { AlertTriangle, Check, CircleHelp, GitCompare, Package, Scale, Truck } from 'lucide-react';

const EASE = [0.22, 1, 0.36, 1];

function PanelShell({ children }) {
  return (
    <div className="procurement-visual-shell flex h-full flex-col">
      <div className="procurement-visual-grid flex flex-1 items-center justify-center p-5 sm:p-8">
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5, ease: EASE }}
          className="w-full max-w-[360px]"
        >
          {children}
        </motion.div>
      </div>
    </div>
  );
}

function AnimatedNumber({ value, suffix = '', decimals = 0, className = '' }) {
  const [display, setDisplay] = useState(0);

  useEffect(() => {
    const start = performance.now();
    const duration = 900;
    let frame;

    const tick = (now) => {
      const t = Math.min((now - start) / duration, 1);
      const eased = 1 - (1 - t) ** 3;
      setDisplay(value * eased);
      if (t < 1) frame = requestAnimationFrame(tick);
    };

    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [value]);

  const formatted =
    decimals > 0 ? display.toFixed(decimals) : Math.round(display).toString();

  return (
    <span className={className}>
      {formatted}
      {suffix}
    </span>
  );
}

function DotRing({ percent, color = 'primary', size = 72 }) {
  const total = 24;
  const filled = Math.round((percent / 100) * total);
  const r = (size - 8) / 2;
  const cx = size / 2;
  const cy = size / 2;

  return (
    <svg width={size} height={size} className="shrink-0" aria-hidden="true">
      {Array.from({ length: total }).map((_, i) => {
        const angle = (i / total) * Math.PI * 2 - Math.PI / 2;
        const x = cx + r * Math.cos(angle);
        const y = cy + r * Math.sin(angle);
        const active = i < filled;

        return (
          <motion.circle
            key={i}
            cx={x}
            cy={y}
            r={2.2}
            initial={{ opacity: 0.2, scale: 0.6 }}
            animate={{
              opacity: active ? 1 : 0.18,
              scale: active ? 1 : 0.75,
            }}
            transition={{ delay: i * 0.025, duration: 0.35, ease: EASE }}
            className={active ? `fill-${color}` : 'fill-muted-foreground/30'}
            style={
              active
                ? { fill: color === 'amber' ? 'hsl(38 92% 55%)' : 'hsl(var(--primary))' }
                : undefined
            }
          />
        );
      })}
    </svg>
  );
}

function MetricCard({ children, className = '' }) {
  return (
    <div
      className={`procurement-metric-card overflow-hidden rounded-[1.35rem] border border-card-border bg-card shadow-[0_20px_50px_rgba(0,0,0,0.45)] ${className}`}
    >
      {children}
    </div>
  );
}

/** Dashboard-style card — quantity match */
export function QuantityMatchVisual() {
  return (
    <PanelShell>
      <MetricCard>
        <div className="border-b border-card-border px-5 py-4 sm:px-6">
          <p className="text-sm text-muted-foreground">
            match <span className="font-semibold text-foreground">quantityCheck</span>
          </p>
          <p className="mt-1 text-xs text-muted-foreground/80">
            PO-2026-0042 · 48 units · <span className="text-primary">0% variance</span>
          </p>
        </div>

        <div className="grid grid-cols-2 gap-4 px-5 py-5 sm:px-6">
          <div>
            <p className="text-xs text-muted-foreground">Qty Match Rate</p>
            <div className="mt-2 flex items-center gap-3">
              <DotRing percent={100} />
              <div>
                <p className="text-2xl font-semibold tracking-tight text-foreground">
                  <AnimatedNumber value={100} suffix="%" />
                </p>
                <p className="mt-0.5 text-[11px] text-primary">↗ all three aligned</p>
              </div>
            </div>
          </div>
          <div className="text-right">
            <p className="text-xs text-muted-foreground">Max tolerance</p>
            <p className="mt-2 text-2xl font-semibold tracking-tight text-foreground">
              <AnimatedNumber value={2} suffix="%" decimals={1} />
            </p>
            <p className="mt-0.5 inline-flex items-center justify-end gap-1 text-[11px] text-muted-foreground">
              within band <CircleHelp className="h-3 w-3 opacity-50" />
            </p>
          </div>
        </div>

        <div className="border-t border-card-border px-5 py-5 sm:px-6">
          <div className="flex items-end justify-between gap-3">
            <div>
              <p className="text-xl font-semibold tracking-tight text-foreground">
                <AnimatedNumber value={48} /> units <span className="text-muted-foreground">(100%)</span>
              </p>
              <p className="mt-1 flex items-center gap-1.5 text-xs text-muted-foreground">
                <Package className="h-3.5 w-3.5 text-primary" />
                Document quantities
              </p>
            </div>
            <span className="rounded-full bg-primary/12 px-2.5 py-1 text-[11px] font-medium text-primary">
              Matched
            </span>
          </div>

          <div className="mt-4 flex h-3 overflow-hidden rounded-full bg-muted">
            <motion.span
              className="h-full bg-primary"
              initial={{ width: 0 }}
              animate={{ width: '37%' }}
              transition={{ duration: 0.8, ease: EASE, delay: 0.15 }}
            />
            <motion.span
              className="h-full bg-primary/70"
              initial={{ width: 0 }}
              animate={{ width: '33%' }}
              transition={{ duration: 0.8, ease: EASE, delay: 0.3 }}
            />
            <motion.span
              className="h-full bg-primary/40"
              initial={{ width: 0 }}
              animate={{ width: '30%' }}
              transition={{ duration: 0.8, ease: EASE, delay: 0.45 }}
            />
          </div>

          <div className="mt-3 space-y-1.5 text-[11px] text-muted-foreground">
            <p className="flex items-center gap-2">
              <span className="h-2 w-2 rounded-full bg-primary" />
              PO qty 48 (37%)
            </p>
            <p className="flex items-center gap-2">
              <span className="h-2 w-2 rounded-full bg-primary/70" />
              GRN qty 48 (33%)
            </p>
            <p className="flex items-center gap-2">
              <span className="h-2 w-2 rounded-full bg-primary/40" />
              Invoice qty 48 (30%)
            </p>
          </div>
        </div>
      </MetricCard>
    </PanelShell>
  );
}

/** Dashboard-style card — price match */
export function PriceMatchVisual() {
  return (
    <PanelShell>
      <MetricCard>
        <div className="border-b border-card-border px-5 py-4 sm:px-6">
          <p className="text-sm text-muted-foreground">
            match <span className="font-semibold text-foreground">priceCheck</span>
          </p>
          <p className="mt-1 text-xs text-muted-foreground/80">
            Acme Logistics · $124.00/unit · <span className="text-primary">$0.00 delta</span>
          </p>
        </div>

        <div className="grid grid-cols-2 gap-4 px-5 py-5 sm:px-6">
          <div>
            <p className="text-xs text-muted-foreground">Price Alignment</p>
            <div className="mt-2 flex items-center gap-3">
              <DotRing percent={100} />
              <div>
                <p className="text-2xl font-semibold tracking-tight text-foreground">
                  <AnimatedNumber value={100} suffix="%" />
                </p>
                <p className="mt-0.5 text-[11px] text-primary">↗ within 3% band</p>
              </div>
            </div>
          </div>
          <div className="text-right">
            <p className="text-xs text-muted-foreground">Unit delta</p>
            <p className="mt-2 text-2xl font-semibold tracking-tight text-foreground">
              $<AnimatedNumber value={0} decimals={2} />
            </p>
            <p className="mt-0.5 inline-flex items-center justify-end gap-1 text-[11px] text-muted-foreground">
              PO vs invoice <CircleHelp className="h-3 w-3 opacity-50" />
            </p>
          </div>
        </div>

        <div className="border-t border-card-border px-5 py-5 sm:px-6">
          <div className="flex items-end justify-between gap-3">
            <div>
              <p className="text-xl font-semibold tracking-tight text-foreground">
                $5,952.00 <span className="text-muted-foreground">(100%)</span>
              </p>
              <p className="mt-1 flex items-center gap-1.5 text-xs text-muted-foreground">
                <Scale className="h-3.5 w-3.5 text-primary" />
                Line total verified
              </p>
            </div>
            <span className="rounded-full bg-primary/12 px-2.5 py-1 text-[11px] font-medium text-primary">
              Pass
            </span>
          </div>

          <div className="mt-4 flex h-3 overflow-hidden rounded-full bg-muted">
            <motion.span
              className="h-full bg-indigo-500"
              initial={{ width: 0 }}
              animate={{ width: '50%' }}
              transition={{ duration: 0.85, ease: EASE, delay: 0.1 }}
            />
            <motion.span
              className="h-full bg-indigo-400/80"
              initial={{ width: 0 }}
              animate={{ width: '50%' }}
              transition={{ duration: 0.85, ease: EASE, delay: 0.35 }}
            />
          </div>

          <div className="mt-3 space-y-1.5 text-[11px] text-muted-foreground">
            <p className="flex items-center gap-2">
              <span className="h-2 w-2 rounded-full bg-indigo-500" />
              PO price $124.00
            </p>
            <p className="flex items-center gap-2">
              <span className="h-2 w-2 rounded-full bg-indigo-400/80" />
              Invoice price $124.00
            </p>
            <p className="font-medium text-foreground/70">Total $5,952.00 · 48 units</p>
          </div>
        </div>
      </MetricCard>
    </PanelShell>
  );
}

/** Claim-style card — variance routing */
export function VarianceRoutingVisual() {
  const steps = ['PO', 'GRN', 'Qty', 'Route'];

  return (
    <PanelShell>
      <MetricCard className="relative">
        <div className="flex items-start gap-3 px-5 py-4 sm:px-6">
          <div className="grid h-11 w-11 shrink-0 place-items-center rounded-xl border border-card-border bg-muted/80">
            <Truck className="h-5 w-5 text-muted-foreground" strokeWidth={1.5} />
          </div>
          <div className="min-w-0 flex-1">
            <p className="text-sm font-semibold text-foreground">Steel brackets · 52qty</p>
            <p className="text-xs text-muted-foreground">from Acme Logistics</p>
          </div>
          <div className="text-right">
            <p className="text-sm font-semibold text-foreground">$6,448</p>
            <span className="mt-1 inline-flex items-center gap-1 rounded-full bg-amber-500/15 px-2 py-0.5 text-[10px] font-medium text-amber-400">
              <span className="h-1.5 w-1.5 rounded-full bg-amber-400" />
              Variance
            </span>
          </div>
        </div>

        <motion.div
          initial={{ opacity: 0, y: 12, scale: 0.96 }}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          transition={{ duration: 0.45, ease: EASE, delay: 0.2 }}
          className="procurement-float-card mx-4 mb-4 rounded-2xl border border-card-border bg-background/95 p-4 shadow-[0_16px_40px_rgba(0,0,0,0.5)] sm:mx-5"
        >
          <div className="flex items-center justify-between gap-2">
            <p className="text-xs font-medium text-foreground">Match progress</p>
            <p className="text-[10px] text-muted-foreground">Blocked at qty check</p>
          </div>

          <p className="mt-3 text-3xl font-semibold tracking-tight text-foreground">
            <AnimatedNumber value={67} suffix="%" />
          </p>

          <div className="relative mt-4 h-1.5 rounded-full bg-muted">
            <motion.div
              className="absolute inset-y-0 left-0 rounded-full bg-amber-400"
              initial={{ width: 0 }}
              animate={{ width: '67%' }}
              transition={{ duration: 1, ease: EASE, delay: 0.25 }}
            />
            <div className="absolute inset-0 flex items-center justify-between px-0">
              {steps.map((step, i) => {
                const done = i < 2;
                const current = i === 2;
                return (
                  <motion.span
                    key={step}
                    initial={{ scale: 0.6, opacity: 0 }}
                    animate={{ scale: 1, opacity: 1 }}
                    transition={{ delay: 0.35 + i * 0.1, duration: 0.3, ease: EASE }}
                    className={`relative z-10 flex h-5 w-5 items-center justify-center rounded-full border-2 text-[7px] font-bold ${
                      done
                        ? 'border-amber-400 bg-amber-400 text-background'
                        : current
                          ? 'border-amber-400 bg-background text-amber-400'
                          : 'border-muted-foreground/30 bg-card text-muted-foreground'
                    }`}
                  >
                    {done ? <Check className="h-2.5 w-2.5" strokeWidth={3} /> : i + 1}
                  </motion.span>
                );
              })}
            </div>
          </div>
        </motion.div>

        <div className="grid grid-cols-2 gap-4 border-t border-card-border px-5 py-4 sm:px-6">
          <div>
            <p className="text-[11px] text-muted-foreground">Case ID</p>
            <p className="mt-0.5 text-sm font-semibold text-foreground">PO-2026-0042</p>
          </div>
          <div>
            <p className="text-[11px] text-muted-foreground">Type</p>
            <p className="mt-0.5 text-sm font-semibold text-foreground">Qty variance</p>
          </div>
          <div className="col-span-2">
            <p className="text-[11px] text-muted-foreground">Description</p>
            <p className="mt-1 text-xs leading-relaxed text-foreground/85">
              Invoice quantity exceeds GRN by 4 units (+8.3%). Routed to buyer and finance — payment blocked until
              resolved.
            </p>
          </div>
        </div>

        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 0.6, duration: 0.4 }}
          className="mx-5 mb-5 flex items-center gap-2 rounded-xl border border-amber-500/20 bg-amber-500/8 px-3 py-2.5"
        >
          <AlertTriangle className="h-3.5 w-3.5 shrink-0 text-amber-400" />
          <p className="font-mono text-[10px] text-muted-foreground">
            flag = &quot;variance&quot; · route = &quot;buyer + finance&quot;
          </p>
        </motion.div>
      </MetricCard>
    </PanelShell>
  );
}

const visuals = {
  quantity: QuantityMatchVisual,
  price: PriceMatchVisual,
  variance: VarianceRoutingVisual,
};

export function ProcurementVisual({ ruleId }) {
  const Visual = visuals[ruleId] || QuantityMatchVisual;
  return <Visual />;
}

export const procurementIcons = {
  quantity: Package,
  price: Scale,
  variance: GitCompare,
};
