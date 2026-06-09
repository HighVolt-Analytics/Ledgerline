import { Shield } from "lucide-react";
import { EmptyState } from "@/components/EmptyState";
import { KpiCard } from "@/components/KpiCard";
import { PageHeader } from "@/components/PageHeader";
import { PayableInvoiceRow } from "@/components/payments/PayableInvoiceRow";
import { WalletCard } from "@/components/payments/WalletCard";
import { Card } from "@/components/ui/card";
import { usePayablesQueue } from "@/hooks/useRoutedInvoices";
import { money } from "@/lib/format";
import { payablesKpis } from "@/lib/routePageAdapters";
import { paymentTierLabel } from "@/lib/v4MockData";

export function PaymentsPage() {
  const { data: payables = [], isLoading, isError } = usePayablesQueue();

  const kpis = payablesKpis(payables);

  return (
    <div>
      <PageHeader
        title="Payments"
        subtitle="Open payables from processed invoices with due dates. Disbursement approval tiers connect in a later phase."
      />

      <div className="grid gap-3 grid-cols-1 lg:grid-cols-[1fr_1fr_1fr_1.4fr] mb-5">
        <KpiCard
          label="Open Payables"
          value={isLoading ? "…" : kpis.count}
          testid="kpi-pay-ready"
          delta={{ dir: "up", text: "processed + due", good: true }}
        />
        <KpiCard
          label="Due within 7 days"
          value={isLoading ? "…" : kpis.dueSoon}
          testid="kpi-pay-awaiting"
          delta={
            !isLoading && kpis.dueSoon > 0 ? { dir: "flat", text: "coming due" } : undefined
          }
        />
        <KpiCard
          label="Queue total"
          value={isLoading ? "…" : money(kpis.total)}
          testid="kpi-pay-paid"
        />
        <WalletCard />
      </div>

      <Card className="p-3 mb-5 border-primary/30 bg-primary/5">
        <div className="flex items-start gap-2.5">
          <Shield className="h-4 w-4 text-primary mt-0.5 shrink-0" />
          <div className="text-xs text-muted-foreground">
            <span className="font-medium text-foreground">Payment controls active.</span> Payables
            appear when an invoice is <span className="text-foreground">processed</span> and has a{" "}
            <span className="text-foreground">due date</span>. Multi-tier approval scales with amount
            ({paymentTierLabel(500)}, {paymentTierLabel(5000)}, {paymentTierLabel(25000)},{" "}
            {paymentTierLabel(60000)}). Stripe disbursement workflow is shown separately via the
            wallet card.
          </div>
        </div>
      </Card>

      <div className="mb-3 flex items-center justify-between gap-2">
        <h2 className="text-sm font-semibold">Payables queue</h2>
        {!isLoading && kpis.overdue > 0 ? (
          <span className="text-xs text-destructive tnum">{kpis.overdue} overdue</span>
        ) : null}
      </div>

      {isLoading ? (
        <div className="text-sm text-muted-foreground py-8">Loading payables…</div>
      ) : isError ? (
        <div className="text-sm text-destructive py-8">Could not load payables queue.</div>
      ) : payables.length === 0 ? (
        <EmptyState
          title="No open payables"
          hint="Processed invoices with a due date appear here. Check the inbox for documents still in the pipeline."
        />
      ) : (
        <div className="space-y-2.5">
          {payables.map((invoice) => (
            <PayableInvoiceRow key={invoice.id} invoice={invoice} />
          ))}
        </div>
      )}
    </div>
  );
}
