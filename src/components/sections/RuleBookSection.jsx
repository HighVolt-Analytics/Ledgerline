import FadeIn from '../ui/FadeIn';
import SectionLabel from '../ui/SectionLabel';
import SectionTitle from '../ui/SectionTitle';
import { ruleBookBands } from '../../data/sections';

export default function RuleBookSection() {
  return (
    <section className="mx-auto max-w-[1200px] px-5 py-20 sm:px-8 sm:py-28">
      <FadeIn>
        <SectionLabel>Deterministic by design</SectionLabel>
        <SectionTitle className="mt-4">The Rule Book is why we win.</SectionTitle>
        <p className="mt-4 max-w-xl text-lg text-muted-foreground">
          Five priority bands. Deterministic. Auditable. No black-box ML deciding where your money goes.
        </p>
      </FadeIn>

      <div className="mt-14 grid grid-cols-1 gap-8 lg:grid-cols-5">
        <div className="flex flex-col gap-3 lg:col-span-3">
          {ruleBookBands.map((band, i) => (
            <FadeIn key={band.n} delay={i * 0.06}>
              <div
                className="flex items-center gap-4 rounded-xl border border-card-border bg-card p-4"
                style={{ borderColor: `hsl(var(--primary) / ${band.opacity * 0.4})` }}
              >
                <span
                  className="grid h-10 w-10 shrink-0 place-items-center rounded-lg font-mono text-lg"
                  style={{
                    background: `hsl(var(--primary) / ${band.opacity * 0.14})`,
                    color: 'hsl(var(--primary))',
                  }}
                >
                  {band.n}
                </span>
                <div className="min-w-0">
                  <div className="text-sm font-medium text-foreground">{band.name}</div>
                  <code className="mt-1 block truncate font-mono text-[12px] text-muted-foreground">{band.rule}</code>
                </div>
              </div>
            </FadeIn>
          ))}
        </div>

        <FadeIn delay={0.1} className="lg:col-span-2">
          <div className="rounded-2xl border border-card-border bg-card p-5 shadow-md">
            <div className="font-mono text-[10px] uppercase tracking-[0.18em] text-muted-foreground">Live evaluation</div>
            <div className="mt-4 space-y-3 font-mono text-[12px]">
              <Row label="document" value="INV-4417" />
              <Row label="vendor" value="Amazon Web Services" />
              <Row label="total" value="4,182.00 AUD" />
              <div className="h-px w-full ledgerline-gradient opacity-50" />
              <div className="flex justify-between">
                <span className="text-muted-foreground">matched band</span>
                <span className="rounded-full bg-primary/12 px-2 py-0.5 text-primary">Band 1</span>
              </div>
              <div className="rounded-lg bg-background/60 p-3 leading-relaxed text-foreground">
                vendor.id = &quot;AWS-AU&quot;
                <br />
                → ledger = &quot;Cloud Infrastructure&quot;
              </div>
              <div className="text-muted-foreground">posted to Xero · 21s</div>
            </div>
          </div>
        </FadeIn>
      </div>
    </section>
  );
}

function Row({ label, value }) {
  return (
    <div className="flex justify-between">
      <span className="text-muted-foreground">{label}</span>
      <span className="text-foreground">{value}</span>
    </div>
  );
}
