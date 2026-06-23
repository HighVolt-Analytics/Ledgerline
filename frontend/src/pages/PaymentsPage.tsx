import { useMemo, useState } from "react";
import { Shield } from "lucide-react";
import { EmptyState } from "@/components/EmptyState";
import { KpiCard } from "@/components/KpiCard";
import { PageHeader } from "@/components/PageHeader";
import { PageTabPanel, PageTabs } from "@/components/PageTabs";
import { PaymentReceiptSheet } from "@/components/payments/PaymentReceiptSheet";
import { PaymentRow } from "@/components/payments/PaymentRow";
import { WalletCard } from "@/components/payments/WalletCard";
import { Card } from "@/components/ui/card";
import { usePaymentMutations, usePayments } from "@/hooks/usePayments";
import { useTenantTime } from "@/hooks/useTenantTime";
import { money } from "@/lib/format";
import { apiPaymentToRecord, paymentsKpis } from "@/lib/routePageAdapters";
import { paymentTierLabel, type PaymentRecord, type PaymentTab } from "@/lib/v4MockData";

const TABS: { value: PaymentTab; label: string; testid: string }[] = [
  { value: "queue", label: "Queue", testid: "tab-pay-queue" },
  { value: "awaiting", label: "Awaiting approval", testid: "tab-pay-awaiting" },
  { value: "scheduled", label: "Scheduled", testid: "tab-pay-scheduled" },
  { value: "paid", label: "Paid", testid: "tab-pay-paid" },
  { value: "failed", label: "Failed", testid: "tab-pay-failed" },
];

export function PaymentsPage() {
  const { timeZone } = useTenantTime();
  const { data: paymentRows = [], isLoading, isError } = usePayments();
  const { updateStatus } = usePaymentMutations();
  const [tab, setTab] = useState<PaymentTab>("queue");
  const [justPaidId, setJustPaidId] = useState<string | null>(null);
  const [receipt, setReceipt] = useState<PaymentRecord | null>(null);

  const payments = useMemo(() => paymentRows.map(apiPaymentToRecord), [paymentRows]);
  const kpis = paymentsKpis(payments, timeZone);
  const tabPayments = useMemo(
    () => payments.filter((p) => p.tab === tab),
    [payments, tab]
  );

  const advance = async (payment: PaymentRecord, status: string) => {
    await updateStatus(Number(payment.id), { status });
    if (status === "paid") {
      setJustPaidId(payment.id);
      setTimeout(() => setJustPaidId(null), 2000);
    }
  };

  return (
    <div>
      <PageHeader
        title="Payments"
        subtitle="Disbursement workflow for processed payables — tiered approval by amount with Stripe-ready scheduling."
      />

      <div className="grid gap-3 grid-cols-1 lg:grid-cols-[1fr_1fr_1fr_1.4fr] mb-5">
        <KpiCard
          label="Open payables"
          value={isLoading ? "…" : kpis.count}
          testid="kpi-pay-ready"
          delta={{ dir: "up", text: "workflow queue", good: true }}
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
            <span className="font-medium text-foreground">Payment controls active.</span> Payments
            are created when invoices reach <span className="text-foreground">processed</span> with
            a due date. Multi-tier approval scales with amount (
            {paymentTierLabel(500)}, {paymentTierLabel(5000)}, {paymentTierLabel(25000)},{" "}
            {paymentTierLabel(60000)}).
          </div>
        </div>
      </Card>

      <PageTabs value={tab} onChange={(v) => setTab(v as PaymentTab)} tabs={TABS} />

      <PageTabPanel value={tab} active={tab} className="mt-4">
        {isLoading ? (
          <div className="text-sm text-muted-foreground py-8">Loading payments…</div>
        ) : isError ? (
          <div className="text-sm text-destructive py-8">Could not load payments.</div>
        ) : tabPayments.length === 0 ? (
          <EmptyState
            title={`No ${tab} payments`}
            hint="Processed invoices with due dates create payment rows automatically."
          />
        ) : (
          <div className="space-y-2.5">
            {tabPayments.map((payment) => (
              <PaymentRow
                key={payment.id}
                payment={payment}
                justPaid={justPaidId === payment.id}
                onSubmit={() => void advance(payment, "awaiting")}
                onApprove={() => void advance(payment, "scheduled")}
                onPayNow={() => void advance(payment, "paid")}
                onReceipt={() => setReceipt(payment)}
              />
            ))}
          </div>
        )}
      </PageTabPanel>

      <PaymentReceiptSheet
        open={!!receipt}
        onClose={() => setReceipt(null)}
        payment={receipt}
      />
    </div>
  );
}
