import { useState } from "react";
import {
  AlertTriangle,
  Check,
  CheckCircle2,
  ClipboardCheck,
  FileText,
  Send,
  Shield,
} from "lucide-react";
import { ApproverChip } from "@/components/ApproverChip";
import {
  PayProviderSelector,
  paypalPayoutsReady,
  type PayProvider,
} from "@/components/payments/PayPalProviderCard";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/cn";
import { usePermissions } from "@/hooks/usePermissions";
import {
  useCreatePaymentExecutionInstruction,
  useMarkPaymentPaidManual,
  useValidatePaymentExecutionReadiness,
} from "@/hooks/usePayments";
import {
  resolvePaypalRecipientMethodId,
  useCreatePayPalPayout,
  usePayPalReadiness,
} from "@/hooks/usePayPal";
import type { PaymentExecutionReadinessResponse } from "@/api/types";
import { money } from "@/lib/format";
import {
  paymentTierLabel,
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
        : methodType === "paypal"
          ? "PayPal"
          : methodType === "external_bank_phase2"
            ? "external bank"
            : methodType.replaceAll("_", " ");
  return `${typeLabel} (${statusLabel})`;
}

function executionReadinessBadge(
  status: PaymentRecord["executionReadinessStatus"]
): { label: string; variant: "default" | "secondary" | "outline"; destructive?: boolean } | null {
  switch (status) {
    case "ready_dry_run":
      return { label: "Ready check available", variant: "default" };
    case "manual_instruction_available":
      return { label: "Manual instruction available", variant: "default" };
    case "instruction_created":
      return { label: "Instruction created", variant: "secondary" };
    case "blocked_limit":
      return { label: "Over launch limit", variant: "outline", destructive: true };
    case "blocked_tenant_disabled":
      return { label: "Tenant execution disabled", variant: "outline", destructive: true };
    case "blocked_stripe_setup":
      return { label: "Blocked: Stripe setup", variant: "outline", destructive: true };
    case "blocked_vendor_payout_setup":
      return { label: "Blocked: vendor payout setup", variant: "outline", destructive: true };
    case "awaiting_approval":
      return { label: "Awaiting approval", variant: "secondary" };
    case "scheduled":
      return { label: "Scheduled", variant: "outline" };
    case "paid":
      return { label: "Paid", variant: "default" };
    case "failed":
      return { label: "Failed", variant: "outline", destructive: true };
    case "not_ready":
      return { label: "Not ready", variant: "outline" };
    default:
      return null;
  }
}

function ReadinessResultPanel({ result }: { result: PaymentExecutionReadinessResponse }) {
  return (
    <div
      className={cn(
        "mt-2 rounded-md border px-3 py-2 text-xs space-y-1.5",
        result.can_execute
          ? "border-primary/40 bg-primary/5 text-foreground"
          : "ds-warning-panel border ds-warning-text"
      )}
      data-testid={`payment-readiness-result-${result.payment_id}`}
    >
      <div className="flex items-center gap-1.5 font-medium">
        {result.can_execute ? (
          <>
            <CheckCircle2 className="h-3.5 w-3.5 text-primary" />
            Dry-run validation passed — no funds moved
          </>
        ) : (
          <>
            <AlertTriangle className="h-3.5 w-3.5" />
            Execution blocked (dry-run)
          </>
        )}
      </div>
      {result.blocking_reasons.length > 0 && (
        <ul className="list-disc pl-4 space-y-0.5">
          {result.blocking_reasons.map((reason) => (
            <li key={reason}>{reason}</li>
          ))}
        </ul>
      )}
      {result.warnings.length > 0 && (
        <ul className="list-disc pl-4 space-y-0.5 opacity-90">
          {result.warnings.map((warning) => (
            <li key={warning}>{warning}</li>
          ))}
        </ul>
      )}
      {result.recommended_action && (
        <p className="pt-0.5 opacity-90">{result.recommended_action}</p>
      )}
      {result.role_ready === false ? (
        <p className="opacity-90">Tenant Admin or Approver role required.</p>
      ) : null}
    </div>
  );
}

function InstructionPanel({ instruction }: { instruction: NonNullable<PaymentRecord["executionInstruction"]> }) {
  return (
    <div
      className="mt-2 rounded-md border border-primary/30 bg-primary/5 px-3 py-2 text-xs space-y-1"
      data-testid={`payment-instruction-panel-${instruction.id}`}
    >
      <div className="font-medium text-foreground">Manual payment instruction</div>
      <p className="text-muted-foreground">No funds are moved by LedgerLink.</p>
      <div className="grid gap-0.5 sm:grid-cols-2 pt-1">
        <span>
          Vendor: <span className="text-foreground">{instruction.vendorName}</span>
        </span>
        <span>
          Amount:{" "}
          <span className="text-foreground tnum">
            {money(instruction.amount, instruction.currency)} {instruction.currency}
          </span>
        </span>
        <span>
          Payout method:{" "}
          <span className="text-foreground">{instruction.vendorPayoutMethodLabel}</span>
        </span>
        {instruction.dueDate ? (
          <span>
            Due: <span className="text-foreground">{instruction.dueDate}</span>
          </span>
        ) : null}
        <span className="sm:col-span-2 font-mono text-[11px] text-muted-foreground">
          Reference: {instruction.instructionReference}
        </span>
      </div>
    </div>
  );
}

export function PaymentRow({
  payment: p,
  justPaid,
  paymentsExecutionEnabled = false,
  manualExecutionEnabled = false,
  approveBusy = false,
  selectable = false,
  selected = false,
  onToggleSelect,
  onSubmit,
  onApprove,
  onPayNow,
  onReceipt,
}: {
  payment: PaymentRecord;
  justPaid: boolean;
  paymentsExecutionEnabled?: boolean;
  manualExecutionEnabled?: boolean;
  approveBusy?: boolean;
  /** Show a selection checkbox (used on the Scheduled tab for batch bank-file export). */
  selectable?: boolean;
  selected?: boolean;
  onToggleSelect?: () => void;
  onSubmit: () => void;
  onApprove: () => void;
  onPayNow: () => void;
  onReceipt: () => void;
}) {
  const validateReadiness = useValidatePaymentExecutionReadiness();
  const createInstruction = useCreatePaymentExecutionInstruction();
  const markPaidManual = useMarkPaymentPaidManual();
  const createPaypalPayout = useCreatePayPalPayout();
  const { data: paypalReadiness } = usePayPalReadiness();
  const { permissions } = usePermissions();
  const canExecuteManual =
    permissions == null || permissions.permissions.Approve === true;
  const [readinessResult, setReadinessResult] = useState<PaymentExecutionReadinessResponse | null>(
    null
  );
  const [showMarkPaid, setShowMarkPaid] = useState(false);
  const [manualReference, setManualReference] = useState("");
  const [manualProofReference, setManualProofReference] = useState("");
  const [manualPaidDate, setManualPaidDate] = useState(
    () => new Date().toISOString().slice(0, 10)
  );
  const [manualNote, setManualNote] = useState("");
  const [actionError, setActionError] = useState<string | null>(null);
  const [payProvider, setPayProvider] = useState<PayProvider>("stripe");

  const badge = executionReadinessBadge(p.executionReadinessStatus);
  const showValidate = p.tab !== "paid" && p.tab !== "failed";
  const showProviderSelector = p.tab === "scheduled" || p.tab === "awaiting";
  const paypalEnabled = paypalPayoutsReady(paypalReadiness);
  const canCreateInstruction =
    p.tab === "scheduled" &&
    payProvider === "stripe" &&
    manualExecutionEnabled &&
    canExecuteManual &&
    !p.executionInstruction &&
    p.executionReadinessStatus === "manual_instruction_available";
  const canMarkPaidManual =
    p.tab === "scheduled" &&
    payProvider === "stripe" &&
    !!p.executionInstruction &&
    canExecuteManual;
  const canPayWithPaypal =
    p.tab === "scheduled" && payProvider === "paypal" && paypalEnabled && canExecuteManual;

  const handleValidate = async () => {
    setReadinessResult(null);
    try {
      const result = await validateReadiness.mutateAsync(Number(p.id));
      setReadinessResult(result);
    } catch {
      setReadinessResult(null);
    }
  };

  const handleCreateInstruction = async () => {
    setActionError(null);
    try {
      await createInstruction.mutateAsync(Number(p.id));
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Could not create payment instruction");
    }
  };

  const handleMarkPaidManual = async () => {
    const reference = manualReference.trim();
    const proofReference = manualProofReference.trim();
    if (!reference) {
      setActionError("Payment/reference number is required");
      return;
    }
    if (!proofReference) {
      setActionError("Proof/reference is required");
      return;
    }
    if (!manualPaidDate) {
      setActionError("Paid date is required");
      return;
    }
    const confirmed = window.confirm(
      "This records the payment as paid in LedgerLink only. Funds must be paid externally by the client. LedgerLink does not move money.\n\nContinue?"
    );
    if (!confirmed) return;

    setActionError(null);
    try {
      await markPaidManual.mutateAsync({
        paymentId: Number(p.id),
        body: {
          reference,
          paid_date: manualPaidDate,
          proof_reference: proofReference,
          note: manualNote.trim() || undefined,
        },
      });
      setShowMarkPaid(false);
      setManualReference("");
      setManualProofReference("");
      setManualNote("");
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Could not mark payment paid");
    }
  };

  const handlePayWithPaypal = async () => {
    setActionError(null);
    try {
      let recipientMethodId = await resolvePaypalRecipientMethodId(p.vendor);
      if (recipientMethodId == null) {
        const prompted = window.prompt(
          "No PayPal payout method found for this vendor. Enter the vendor PayPal payout method id:"
        );
        const parsed = prompted ? Number(prompted.trim()) : NaN;
        if (!Number.isFinite(parsed) || parsed <= 0) {
          setActionError("A PayPal recipient method id is required");
          return;
        }
        recipientMethodId = parsed;
      }

      const confirmed = window.confirm(
        `Submit a PayPal payout for ${money(p.amount, p.currency)} to ${p.vendor}?`
      );
      if (!confirmed) return;

      const attempt = await createPaypalPayout.mutateAsync({
        payable_id: Number(p.id),
        recipient_method_id: recipientMethodId,
      });
      if (attempt.status === "failed") {
        setActionError(attempt.failure_message || "PayPal payout failed");
      }
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Could not create PayPal payout");
    }
  };

  return (
    <Card
      className={cn(
        "p-3.5 transition-colors duration-500",
        justPaid && "bg-primary/10 border-primary/40"
      )}
      data-testid={`payment-row-${p.id}`}
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-start gap-2.5 min-w-0">
          {selectable ? (
            <input
              type="checkbox"
              className="mt-1 h-4 w-4 shrink-0 accent-primary"
              checked={selected}
              onChange={() => onToggleSelect?.()}
              aria-label={`Select payment ${p.id} for batch export`}
              data-testid={`payment-select-${p.id}`}
            />
          ) : null}
          <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-medium text-sm">{p.id}</span>
            <span className="text-muted-foreground text-sm truncate">{p.vendor}</span>
            {badge ? (
              <Badge
                variant={badge.variant}
                className={cn(
                  "text-[10px] h-5 px-1.5",
                  badge.destructive &&
                    "border-destructive/40 text-destructive bg-destructive/10"
                )}
              >
                {badge.label}
              </Badge>
            ) : null}
          </div>
          <div className="text-xs text-muted-foreground mt-0.5">
            Source {p.invoiceId} · due {p.dueDate}
            {p.tab === "scheduled" && p.scheduledDate && <> · scheduled {p.scheduledDate}</>}
            {p.tab === "paid" && p.paidDate && <> · paid {p.paidDate}</>}
            {p.vendorPayoutStatus != null && p.vendorPayoutStatus !== undefined ? (
              <> · vendor payout: {formatVendorPayoutStatus(p.vendorPayoutStatus, p.vendorPayoutMethodType)}</>
            ) : null}
            {p.executionBlockingReason ? (
              <> · {p.executionBlockingReason}</>
            ) : null}
          </div>
          </div>
        </div>
        <div className="text-right">
          <div className="tnum font-semibold text-sm">
            {money(p.amount, p.currency)}
          </div>
          <div className="text-[10px] text-muted-foreground">{paymentTierLabel(p.amount)}</div>
        </div>
      </div>

      {p.approvers.length > 0 && (
        <div className="mt-2.5 flex flex-wrap gap-1.5">
          {p.approvers.map((a) => (
            <ApproverChip key={a.id} {...a} />
          ))}
        </div>
      )}

      <div className="mt-3 flex flex-wrap items-center gap-2">
        {showProviderSelector ? (
          <PayProviderSelector
            paymentId={p.id}
            value={payProvider}
            onChange={setPayProvider}
            paypalEnabled={paypalEnabled}
          />
        ) : null}

        {p.tab === "queue" && (
          <Button size="sm" className="h-7 text-xs" onClick={onSubmit} data-testid={`button-submit-${p.id}`}>
            <Send className="h-3.5 w-3.5 mr-1" />
            Submit for approval
          </Button>
        )}

        {p.tab === "awaiting" && (
          <Button
            size="sm"
            className="h-7 text-xs"
            onClick={onApprove}
            disabled={approveBusy}
            data-testid={`button-approve-pay-${p.id}`}
          >
            <Check className="h-3.5 w-3.5 mr-1" />
            {approveBusy ? "Approving…" : "Approve payment"}
          </Button>
        )}

        {showValidate && (
          <Button
            size="sm"
            variant="outline"
            className="h-7 text-xs"
            onClick={() => void handleValidate()}
            disabled={validateReadiness.isPending}
            data-testid={`button-validate-payment-${p.id}`}
          >
            <ClipboardCheck className="h-3.5 w-3.5 mr-1" />
            {validateReadiness.isPending ? "Validating…" : "Validate payment"}
          </Button>
        )}

        {canCreateInstruction && (
          <Button
            size="sm"
            variant="outline"
            className="h-7 text-xs"
            onClick={() => void handleCreateInstruction()}
            disabled={createInstruction.isPending}
            data-testid={`button-create-instruction-${p.id}`}
          >
            <FileText className="h-3.5 w-3.5 mr-1" />
            {createInstruction.isPending ? "Creating…" : "Create payment instruction"}
          </Button>
        )}

        {canMarkPaidManual && !showMarkPaid && (
          <Button
            size="sm"
            className="h-7 text-xs"
            onClick={() => setShowMarkPaid(true)}
            data-testid={`button-mark-paid-manual-${p.id}`}
          >
            <Check className="h-3.5 w-3.5 mr-1" />
            Mark paid manually
          </Button>
        )}

        {canPayWithPaypal ? (
          <Button
            size="sm"
            className="h-7 text-xs"
            onClick={() => void handlePayWithPaypal()}
            disabled={createPaypalPayout.isPending}
            data-testid={`button-pay-paypal-${p.id}`}
          >
            <Shield className="h-3.5 w-3.5 mr-1" />
            {createPaypalPayout.isPending ? "Submitting…" : "Pay with PayPal"}
          </Button>
        ) : null}

        {!canExecuteManual && p.tab === "scheduled" && manualExecutionEnabled ? (
          <span className="text-xs text-muted-foreground">
            Tenant Admin or Approver role required for payment execution.
          </span>
        ) : null}

        {p.tab === "scheduled" && paymentsExecutionEnabled && payProvider === "stripe" && (
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

        {p.tab === "paid" && (
          <>
            <span className="inline-flex items-center gap-1.5 text-xs text-primary">
              <Check className="h-3.5 w-3.5" /> Paid (workflow status)
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

      {showMarkPaid && canMarkPaidManual ? (
        <div
          className="mt-2 rounded-md border border-border/80 bg-muted/30 px-3 py-2.5 space-y-2"
          data-testid={`payment-mark-paid-form-${p.id}`}
        >
          <p className="text-xs text-muted-foreground">
            This records the payment as paid in LedgerLink only. Funds must be paid externally by
            the client. LedgerLink does not move money.
          </p>
          <Input
            value={manualReference}
            onChange={(e) => setManualReference(e.target.value)}
            placeholder="Payment/reference number (required)"
            className="h-8 text-xs"
            data-testid={`input-mark-paid-reference-${p.id}`}
          />
          <Input
            type="date"
            value={manualPaidDate}
            onChange={(e) => setManualPaidDate(e.target.value)}
            className="h-8 text-xs"
            data-testid={`input-mark-paid-date-${p.id}`}
          />
          <Input
            value={manualProofReference}
            onChange={(e) => setManualProofReference(e.target.value)}
            placeholder="Proof/reference (required)"
            className="h-8 text-xs"
            data-testid={`input-mark-paid-proof-${p.id}`}
          />
          <Input
            value={manualNote}
            onChange={(e) => setManualNote(e.target.value)}
            placeholder="Note (optional)"
            className="h-8 text-xs"
          />
          <div className="flex flex-wrap gap-2">
            <Button
              size="sm"
              className="h-7 text-xs"
              onClick={() => void handleMarkPaidManual()}
              disabled={markPaidManual.isPending}
            >
              {markPaidManual.isPending ? "Saving…" : "Confirm mark paid"}
            </Button>
            <Button
              size="sm"
              variant="ghost"
              className="h-7 text-xs"
              onClick={() => {
                setShowMarkPaid(false);
                setActionError(null);
              }}
            >
              Cancel
            </Button>
          </div>
        </div>
      ) : null}

      {actionError ? (
        <p className="mt-2 text-xs text-destructive">{actionError}</p>
      ) : null}

      {p.executionInstruction ? <InstructionPanel instruction={p.executionInstruction} /> : null}

      {readinessResult ? <ReadinessResultPanel result={readinessResult} /> : null}
    </Card>
  );
}
