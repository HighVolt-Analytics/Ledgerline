import {
  AlertTriangle,
  Check,
  Clock,
  Lock,
  Send,
  Shield,
} from "lucide-react";
import { ApproverChip } from "@/components/ApproverChip";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { cn } from "@/lib/cn";
import {
  fmtAud,
  paymentApproverCount,
  paymentTierLabel,
  SANDBOX_CURRENT_USER,
  type PaymentRecord,
} from "@/lib/v4MockData";

function formatVendorPayoutStatus(
  status: string,
  methodType: string | undefined
): string {
  const statusLabel =
    status === "not_configured"
      ? "not configured"
      : status === "verified"
        ? "verified"
        : status;
  if (!methodType) return statusLabel;
  const typeLabel =
    methodType === "manual_bank"
      ? "manual bank"
      : methodType === "stripe_connected_account"
        ? "Stripe account"
        : methodType === "external_bank_phase2"
          ? "external bank"
          : methodType.replaceAll("_", " ");
  return `${typeLabel} (${statusLabel})`;
}

export function PaymentRow({
  payment: p,
  justPaid,
  stripePayoutsReady = false,
  onSubmit,
  onApprove,
  onPayNow,
  onReceipt,
}: {
  payment: PaymentRecord;
  justPaid: boolean;
  stripePayoutsReady?: boolean;
  onSubmit: () => void;
  onApprove: () => void;
  onPayNow: () => void;
  onReceipt: () => void;
}) {
  const user = SANDBOX_CURRENT_USER;
  const invoiceApprover = p.invoiceApprovedBy === user.id;
  const pending = p.approvers.find((a) => a.state === "pending");
  const canApprove = Boolean(pending && pending.id === user.id);

  return (
    <Card
      className={cn(
        "p-3.5 transition-colors duration-500",
        justPaid && "bg-primary/10 border-primary/40"
      )}
      data-testid={`payment-row-${p.id}`}
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className="font-medium text-sm">{p.id}</span>
            <span className="text-muted-foreground text-sm truncate">{p.vendor}</span>
          </div>
          <div className="text-xs text-muted-foreground mt-0.5">
            Source {p.invoiceId} · due {p.dueDate}
            {p.tab === "scheduled" && p.scheduledDate && <> · scheduled {p.scheduledDate}</>}
            {p.tab === "paid" && p.paidDate && <> · paid {p.paidDate}</>}
            {p.vendorPayoutStatus != null && p.vendorPayoutStatus !== undefined ? (
              <> · vendor payout: {formatVendorPayoutStatus(p.vendorPayoutStatus, p.vendorPayoutMethodType)}</>
            ) : null}
          </div>
        </div>
        <div className="text-right">
          <div className="tnum font-semibold text-sm">{fmtAud(p.amount)}</div>
          <div className="text-[10px] text-muted-foreground">{paymentTierLabel(p.amount)}</div>
        </div>
      </div>

      {p.approvers.length > 0 && (
        <div className="mt-2.5 flex flex-wrap gap-1.5">
          {p.approvers.map((a) => {
            const disabled = a.id === user.id && invoiceApprover && a.state === "pending";
            return (
              <ApproverChip
                key={a.id}
                {...a}
                disabled={disabled}
                disabledTitle="You approved this invoice — payment approval must come from another authorised approver."
              />
            );
          })}
        </div>
      )}

      {invoiceApprover && (p.tab === "awaiting" || p.tab === "queue") && (
        <div className="mt-2 flex items-center gap-1.5 text-[11px] text-[hsl(36_80%_38%)] dark:text-[hsl(43_74%_62%)]">
          <Lock className="h-3.5 w-3.5" />
          Segregation of duties: you approved invoice {p.invoiceId}; payment approval must come from
          another approver.
        </div>
      )}

      <div className="mt-3 flex flex-wrap items-center gap-2">
        {p.tab === "queue" && (
          <Button size="sm" className="h-7 text-xs" onClick={onSubmit} data-testid={`button-submit-${p.id}`}>
            <Send className="h-3.5 w-3.5 mr-1" />
            Submit for approval ({paymentApproverCount(p.amount)}{" "}
            {paymentApproverCount(p.amount) === 1 ? "approver" : "approvers"})
          </Button>
        )}

        {p.tab === "awaiting" &&
          (canApprove && !invoiceApprover ? (
            <Button
              size="sm"
              className="h-7 text-xs"
              onClick={onApprove}
              data-testid={`button-approve-pay-${p.id}`}
            >
              <Check className="h-3.5 w-3.5 mr-1" /> Approve payment ({pending?.role})
            </Button>
          ) : canApprove && invoiceApprover ? (
            <Button
              size="sm"
              variant="outline"
              className="h-7 text-xs"
              disabled
              title="You approved this invoice — payment approval must come from another authorised approver."
              data-testid={`button-approve-pay-${p.id}`}
            >
              <Lock className="h-3.5 w-3.5 mr-1" /> Approve payment
            </Button>
          ) : (
            <Button
              size="sm"
              variant="outline"
              className="h-7 text-xs"
              disabled
              title={`Next approver in chain: ${pending?.name} (${pending?.role}).`}
              data-testid={`button-approve-pay-${p.id}`}
            >
              <Clock className="h-3.5 w-3.5 mr-1" /> Awaiting {pending?.name.split(" ")[0]}
            </Button>
          ))}

        {p.tab === "scheduled" && (
          <Button
            size="sm"
            className="h-7 text-xs"
            onClick={onPayNow}
            disabled={justPaid}
            data-testid={`button-pay-now-${p.id}`}
          >
            <Shield className="h-3.5 w-3.5 mr-1" />
            {justPaid ? "Processing…" : "Pay Now"}
          </Button>
        )}

        {p.tab === "scheduled" && !stripePayoutsReady && (
          <p
            className="text-[11px] text-muted-foreground w-full basis-full"
            data-testid={`stripe-payout-guard-${p.id}`}
          >
            Real Stripe payouts are disabled until Stripe readiness is complete.
          </p>
        )}

        {p.tab === "paid" && (
          <>
            <span className="inline-flex items-center gap-1.5 text-xs text-primary">
              <Check className="h-3.5 w-3.5" /> Paid via Stripe Wallet
            </span>
            <Button
              size="sm"
              variant="outline"
              className="h-7 text-xs"
              onClick={onReceipt}
              data-testid={`button-receipt-${p.id}`}
            >
              View receipt
            </Button>
            {p.paymentIntent && (
              <span className="text-[11px] text-muted-foreground font-mono">{p.paymentIntent}</span>
            )}
          </>
        )}

        {p.tab === "failed" && p.failureReason && (
          <span className="inline-flex items-center gap-1.5 text-xs text-destructive">
            <AlertTriangle className="h-3.5 w-3.5" /> {p.failureReason}
          </span>
        )}
      </div>
    </Card>
  );
}
