import { Check, TrendingUp } from 'lucide-react';
import { recentInvoices } from '../../data/sections';
import VolumeChart from './VolumeChart';

function StatCard({ label, value, sub, accent = false }) {
  return (
    <div className={`rounded-xl border p-4 ${accent ? 'border-primary/40 bg-primary/5' : 'border-card-border bg-background/40'}`}>
      <div className="font-mono text-[10px] uppercase tracking-[0.16em] text-muted-foreground">{label}</div>
      <div className="mt-2 font-mono text-2xl font-medium tabular text-foreground">{value}</div>
      {sub && <div className="mt-1 text-[11px] text-muted-foreground">{sub}</div>}
    </div>
  );
}

export default function HeroDashboard() {
  return (
    <div className="overflow-hidden rounded-2xl border border-card-border bg-card/80 shadow-xl backdrop-blur-xl">
      <div className="flex items-center gap-2 border-b border-card-border px-4 py-3">
        <div className="flex gap-1.5">
          <span className="h-2.5 w-2.5 rounded-full bg-muted-foreground/30" />
          <span className="h-2.5 w-2.5 rounded-full bg-muted-foreground/30" />
          <span className="h-2.5 w-2.5 rounded-full bg-muted-foreground/30" />
        </div>
        <div className="ml-3 font-mono text-[11px] text-muted-foreground">ledgerline · acme hospitality au</div>
        <div className="ml-auto flex items-center gap-1.5 rounded-full border border-primary/30 bg-primary/10 px-2.5 py-1">
          <span className="h-1.5 w-1.5 rounded-full bg-primary" />
          <span className="font-mono text-[10px] text-primary">RECONCILED</span>
        </div>
      </div>

      <div className="p-4 sm:p-5">
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <StatCard label="Processed today" value="38,192" sub="AUD · 12 invoices" />
          <StatCard
            label="Reconciliation Δ"
            value="$0.00"
            sub={
              <span className="inline-flex items-center gap-1 text-primary">
                <Check className="h-3 w-3" /> balanced
              </span>
            }
            accent
          />
          <StatCard
            label="First-pass"
            value="96.4%"
            sub={
              <span className="inline-flex items-center gap-1">
                <TrendingUp className="h-3 w-3" />
                vs 91% last wk
              </span>
            }
          />
          <StatCard label="Avg time → post" value="24s" sub="median" />
        </div>

        <div className="mt-3 rounded-xl border border-card-border bg-background/40 p-4">
          <div className="flex items-center justify-between">
            <span className="font-mono text-[10px] uppercase tracking-[0.16em] text-muted-foreground">
              Volume · last 12 days
            </span>
            <span className="font-mono text-[11px] text-foreground">+34%</span>
          </div>
          <div className="mt-2">
            <VolumeChart />
          </div>
        </div>

        <div className="mt-3 rounded-xl border border-card-border bg-background/40">
          <div className="flex items-center gap-2 border-b border-card-border px-4 py-2.5">
            <span className="font-mono text-[10px] uppercase tracking-[0.16em] text-muted-foreground">Recent</span>
          </div>
          <div className="divide-y divide-card-border">
            {recentInvoices.map((inv) => (
              <div key={inv.id} className="grid grid-cols-12 items-center gap-2 px-4 py-2.5 text-[12px]">
                <span className="col-span-3 font-mono text-muted-foreground">{inv.id}</span>
                <span className="col-span-4 truncate text-foreground">{inv.vendor}</span>
                <span className="col-span-2 hidden truncate text-muted-foreground sm:block">{inv.ledger}</span>
                <span className="col-span-2 sm:col-span-1 text-right font-mono tabular text-foreground">{inv.amt}</span>
                <span className="col-span-3 sm:col-span-2 text-right">
                  <span
                    className={`inline-flex rounded-full px-2 py-0.5 font-mono text-[10px] ${
                      inv.state === 'Posted' ? 'bg-primary/12 text-primary' : 'bg-muted text-muted-foreground'
                    }`}
                  >
                    {inv.state}
                  </span>
                </span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
