import { GitCompare } from 'lucide-react';
import FadeIn from '../ui/FadeIn';
import SectionLabel from '../ui/SectionLabel';
import SectionTitle from '../ui/SectionTitle';
import { procurementRules } from '../../data/sections';

export default function ProcurementSection() {
  return (
    <section className="mx-auto max-w-[1200px] px-5 py-20 sm:px-8 sm:py-28">
      <FadeIn>
        <SectionLabel>Procurement · v4</SectionLabel>
        <SectionTitle className="mt-4">PO. GRN. Invoice. One number that has to agree.</SectionTitle>
        <p className="mt-4 max-w-xl text-lg text-muted-foreground">
          v4 adds the full purchase loop. The invoice no longer arrives alone — it arrives with a Purchase Order it has to
          match against a Goods Receipt Note. Variances above tolerance are routed, not rubber-stamped.
        </p>
      </FadeIn>

      <div className="mt-14 grid grid-cols-1 gap-8 lg:grid-cols-5">
        <div className="flex flex-col gap-3 lg:col-span-3">
          {procurementRules.map((rule, i) => (
            <FadeIn key={rule.name} delay={i * 0.06}>
              <div
                className="flex items-center gap-4 rounded-xl border border-card-border bg-card p-4"
                style={{ borderColor: `hsl(var(--primary) / ${rule.opacity * 0.4})` }}
              >
                <span
                  className="grid h-10 w-10 shrink-0 place-items-center rounded-lg"
                  style={{
                    background: `hsl(var(--primary) / ${rule.opacity * 0.14})`,
                    color: 'hsl(var(--primary))',
                  }}
                >
                  <GitCompare className="h-5 w-5" />
                </span>
                <div className="min-w-0">
                  <div className="text-sm font-medium text-foreground">{rule.name}</div>
                  <code className="mt-1 block truncate font-mono text-[12px] text-muted-foreground">{rule.rule}</code>
                </div>
              </div>
            </FadeIn>
          ))}
        </div>

        <FadeIn delay={0.1} className="lg:col-span-2">
          <div className="rounded-2xl border border-card-border bg-card p-5 shadow-md">
            <div className="font-mono text-[10px] uppercase tracking-[0.18em] text-muted-foreground">Match preview</div>
            <div className="mt-4 space-y-3 font-mono text-[12px]">
              <Row label="po" value="PO-2026-0042" />
              <Row label="vendor" value="Acme Logistics" />
              <div className="h-px w-full ledgerline-gradient opacity-50" />
              <Row label="po.qty" value="48" accent />
              <Row label="grn.qty" value="48" accent />
              <Row label="invoice.qty" value="48" accent />
              <div className="h-px w-full ledgerline-gradient opacity-50" />
              <Row label="po.price" value="$124.00" accent />
              <Row label="invoice.price" value="$124.00" accent />
              <div className="h-px w-full ledgerline-gradient opacity-50" />
              <div className="flex items-center justify-between">
                <span className="text-muted-foreground">match status</span>
                <span className="rounded-full bg-primary/12 px-2 py-0.5 text-primary whitespace-nowrap">
                  3-Way Matched · ready to pay
                </span>
              </div>
            </div>
          </div>
        </FadeIn>
      </div>
    </section>
  );
}

function Row({ label, value, accent = false }) {
  return (
    <div className="flex justify-between">
      <span className="text-muted-foreground">{label}</span>
      <span className={`tabular whitespace-nowrap ${accent ? 'text-primary' : 'text-foreground'}`}>{value}</span>
    </div>
  );
}
