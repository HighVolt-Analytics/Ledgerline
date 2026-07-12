import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { Check, Link2, X } from "lucide-react";
import { ApprovalPolicyNote } from "@/components/ApprovalPolicyNote";
import { DocumentAuditTrail } from "@/components/DocumentAuditTrail";
import { Card } from "@/components/ui/card";
import { cn } from "@/lib/cn";
import { money } from "@/lib/format";
import { type PaymentRecord } from "@/lib/v4MockData";

function ReceiptRow({
  label,
  value,
  mono,
  strong,
}: {
  label: string;
  value: string;
  mono?: boolean;
  strong?: boolean;
}) {
  return (
    <div className="flex items-center justify-between gap-2">
      <span className="text-muted-foreground text-xs uppercase tracking-wide">{label}</span>
      <span className={cn("text-sm text-right", mono && "font-mono", strong && "font-semibold tnum")}>
        {value}
      </span>
    </div>
  );
}

export function PaymentReceiptSheet({
  payment,
  open,
  onClose,
}: {
  payment: PaymentRecord | null;
  open: boolean;
  onClose: () => void;
}) {
  const [mounted, setMounted] = useState(false);
  const [sheetState, setSheetState] = useState<"open" | "closed">("closed");

  useEffect(() => {
    if (open && payment) {
      setMounted(true);
      setSheetState("closed");
      const frame = requestAnimationFrame(() => {
        requestAnimationFrame(() => setSheetState("open"));
      });
      return () => cancelAnimationFrame(frame);
    }
    setSheetState("closed");
    const timer = window.setTimeout(() => setMounted(false), 300);
    return () => window.clearTimeout(timer);
  }, [open, payment]);

  useEffect(() => {
    if (!mounted) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [mounted, onClose]);

  if (!mounted || !payment) return null;

  return createPortal(
    <div className="pointer-events-none" data-testid="drawer-payment-receipt">
      <button
        type="button"
        data-state={sheetState}
        className="invoice-drawer-backdrop pointer-events-auto"
        aria-label="Close"
        onClick={onClose}
      />
      <div
        role="dialog"
        aria-modal="true"
        data-state={sheetState}
        className="invoice-drawer-panel invoice-drawer-panel--sheet pointer-events-auto flex h-full flex-col gap-0 border-l border-border bg-card p-0 shadow-lg"
      >
        <div className="flex items-center justify-between px-5 py-3.5 border-b border-border shrink-0">
          <div>
            <h2 className="text-base font-semibold flex items-center gap-2">
              <Check className="h-5 w-5 text-primary" />
              Payment receipt
            </h2>
            <p className="text-xs text-muted-foreground mt-0.5">
              Stripe Wallet disbursement · {payment.vendor}
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-sm opacity-70 hover:opacity-100"
            aria-label="Close"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-5">
          <Card className="p-4 bg-muted/30 space-y-2 text-sm">
            <ReceiptRow label="Payment intent" value={payment.paymentIntent ?? "—"} mono />
            <ReceiptRow
              label="Amount"
              value={money(payment.amount, payment.currency)}
              strong
            />
            <ReceiptRow label="Source document" value={payment.invoiceId} />
            <ReceiptRow label="Paid" value={payment.paidDate ?? "—"} />
            <ReceiptRow
              label="Method"
              value={
                payment.currency?.trim()
                  ? `Stripe Wallet (${payment.currency.trim().toUpperCase()})`
                  : "Stripe Wallet"
              }
            />
            <ReceiptRow label="Status" value="Succeeded" />
          </Card>

          <div className="mt-4">
            <div className="text-[11px] text-muted-foreground uppercase tracking-wide mb-1.5">
              Journal entry preview
            </div>
            <Card className="overflow-hidden">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-xs text-muted-foreground bg-muted/50 text-left">
                    <th className="px-3 py-1.5 font-medium">Account</th>
                    <th className="px-3 py-1.5 font-medium text-right">Debit</th>
                    <th className="px-3 py-1.5 font-medium text-right">Credit</th>
                  </tr>
                </thead>
                <tbody>
                  <tr className="border-t border-border/60">
                    <td className="px-3 py-1.5">Accounts Payable</td>
                    <td className="px-3 py-1.5 text-right tnum">
                      {money(payment.amount, payment.currency)}
                    </td>
                    <td className="px-3 py-1.5 text-right tnum">—</td>
                  </tr>
                  <tr className="border-t border-border/60">
                    <td className="px-3 py-1.5">Stripe Wallet</td>
                    <td className="px-3 py-1.5 text-right tnum">—</td>
                    <td className="px-3 py-1.5 text-right tnum">
                      {money(payment.amount, payment.currency)}
                    </td>
                  </tr>
                </tbody>
              </table>
            </Card>
            <p className="text-[11px] text-muted-foreground mt-1.5">
              Dr Accounts Payable / Cr Stripe Wallet — clears the supplier liability against wallet funds.
            </p>
          </div>

          <div className="mt-3">
            <ApprovalPolicyNote />
          </div>

          <a
            href="/ledger-link"
            data-testid="link-view-in-ledger"
            className="inline-flex mt-3 w-full h-8 items-center justify-center rounded-md border border-input bg-background px-3 text-xs font-medium shadow-sm hover-elevate hover:bg-accent hover:text-accent-foreground"
          >
            <Link2 className="h-3.5 w-3.5 mr-1.5" />
            View in Accounting
          </a>

          <DocumentAuditTrail docId={payment.id} />
        </div>
      </div>
    </div>,
    document.body
  );
}
