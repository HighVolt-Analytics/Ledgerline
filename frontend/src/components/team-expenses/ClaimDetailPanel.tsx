import { useEffect, useState } from "react";
import { Check, ExternalLink, HelpCircle, X } from "lucide-react";
import type { InvoiceStatus } from "@/api/types";
import { DocumentAuditTrail } from "@/components/DocumentAuditTrail";
import { Button } from "@/components/ui/button";
import { NumericInput } from "@/components/ui/numeric-input";
import { cn } from "@/lib/cn";
import { money } from "@/lib/format";
import type { ExpenseBudget, ExpenseClaim } from "@/lib/v4MockData";
import type { TeamExpenseKind } from "@/lib/v4RuleBookTypes";
import {
  ClaimAdvanceBlock,
  ClaimApprovalChainBlock,
  ClaimBudgetBlock,
} from "@/components/team-expenses/InvoiceClaimReviewSection";
import { ClaimKindField } from "./ClaimKindField";
import { ExpenseStateBadge } from "./ExpenseBadges";
import { ReceiptThumb } from "./ReceiptThumb";

function DetailField({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div>
      <div className="text-[11px] text-muted-foreground uppercase tracking-wide">{label}</div>
      <div className={cn("text-sm", mono && "tnum")}>{value}</div>
    </div>
  );
}

function ClaimAmountInput({
  value,
  onChange,
  disabled,
}: {
  value: number;
  onChange: (n: number) => void;
  disabled: boolean;
}) {
  return (
    <div>
      <div className="text-[11px] text-muted-foreground uppercase tracking-wide">Amount</div>
      <NumericInput
        value={value}
        onValueChange={(n) => onChange(n ?? 0)}
        disabled={disabled}
        className="h-8 text-sm"
        data-testid="input-claim-amount"
      />
    </div>
  );
}

export function ClaimDetailPanel({
  claim,
  invoiceId,
  invoiceStatus,
  hasStoredFile,
  budget,
  busy = false,
  canApprove,
  canReject,
  canRequestInfo,
  advanceLedger = "",
  settlementLedger = "",
  advanceBalance,
  /** When false, advance shows honest gap instead of a silent 0. Default true when balance provided. */
  advanceMatched,
  /** Show budget gap when no budget row (Expenses Management). Team Expenses uses onChangeKind. */
  showBudgetGap = false,
  currency,
  onApprove,
  onReject,
  onRequestInfo,
  onChangeKind,
  onOpenInvoice,
}: {
  claim: ExpenseClaim;
  invoiceId: number;
  invoiceStatus: InvoiceStatus;
  hasStoredFile: boolean;
  budget?: ExpenseBudget;
  busy?: boolean;
  canApprove: boolean;
  canReject: boolean;
  canRequestInfo: boolean;
  advanceLedger?: string;
  settlementLedger?: string;
  advanceBalance?: number | null;
  advanceMatched?: boolean;
  showBudgetGap?: boolean;
  /** Document currency when set; otherwise org/institution currency. */
  currency: string;
  onApprove: () => void | Promise<void>;
  onReject: () => void | Promise<void>;
  onRequestInfo: () => void | Promise<void>;
  /** Team Expenses only — omit on routes that do not post advance journals. */
  onChangeKind?: (kind: TeamExpenseKind) => void | Promise<void>;
  onOpenInvoice?: () => void;
}) {
  // Must reset when switching claims — useState alone keeps the prior claim's amount
  // after kind toggle.
  const [amount, setAmount] = useState(claim.amount);
  useEffect(() => {
    setAmount(claim.amount);
  }, [claim.id, claim.amount]);

  const editable =
    (claim.state === "New" || claim.state === "In Review") &&
    invoiceStatus !== "processed" &&
    invoiceStatus !== "rejected";
  const rawAdvance =
    advanceBalance !== undefined ? advanceBalance : claim.advanceBalance;
  const netAdvance =
    rawAdvance != null && Number.isFinite(Number(rawAdvance))
      ? Number(rawAdvance)
      : 0;
  const claimAmount = Number.isFinite(amount) ? amount : claim.amount;
  const fmt = (n: number) => money(n, currency);
  const employeeMatched =
    advanceMatched ?? Boolean(claim.employeeId?.trim());

  return (
    <div>
      <div className="flex items-center justify-between gap-2 mb-3">
        <div>
          <div className="text-sm font-semibold tnum">
            {claim.documentRef ?? claim.id} · {claim.submitter}
          </div>
          <div className="text-xs text-muted-foreground">
            via {claim.channel} · {claim.submittedTs}
          </div>
        </div>
        <div className="flex items-center gap-2">
          {onOpenInvoice && (
            <Button
              type="button"
              size="sm"
              variant="ghost"
              className="h-7 text-xs"
              onClick={onOpenInvoice}
              data-testid="button-open-claim-invoice"
            >
              <ExternalLink className="h-3.5 w-3.5 mr-1" />
              Full document
            </Button>
          )}
          <ExpenseStateBadge state={claim.state} />
        </div>
      </div>

      <div className="grid grid-cols-[140px_1fr] gap-3">
        <ReceiptThumb
          merchant={claim.merchant}
          date={claim.date}
          amount={claim.amount}
          gst={claim.gst}
          currency={currency}
        />
        <div className="space-y-2 text-sm min-w-0">
          <DetailField label="Employee name" value={claim.submitter} />
          <DetailField label="Employee ID" value={claim.employeeId || "—"} mono />
          <DetailField label="Division" value={claim.division || "—"} />
          <DetailField label="Location" value={claim.location || "—"} />
          <DetailField label="Category" value={claim.category} />
          <ClaimAmountInput value={claimAmount} onChange={setAmount} disabled={!editable} />
          <DetailField label="Date" value={claim.date} />
          <DetailField label="GST" value={fmt(claim.gst)} mono />
          <DetailField label="Business purpose" value={claim.purpose} />
          <DetailField label="Project tag" value={claim.projectTag} mono />
        </div>
      </div>

      {onChangeKind && (
        <ClaimKindField
          kind={claim.kind}
          expenseLedger={claim.category}
          advanceLedger={advanceLedger}
          settlementLedger={settlementLedger}
          claimAmount={claimAmount}
          advanceAvailable={netAdvance}
          disabled={busy || !editable}
          onChange={(kind) => void onChangeKind(kind)}
        />
      )}

      {!hasStoredFile && canApprove && (
        <p className="text-xs ds-warning-text mt-3">
          Upload a receipt before this claim can be approved.
        </p>
      )}

      {onChangeKind ? (
        <ClaimAdvanceBlock
          matched={employeeMatched}
          advanceBalance={rawAdvance}
          currency={currency}
        />
      ) : null}

      {budget ? (
        <ClaimBudgetBlock
          category={budget.category}
          period={budget.period}
          allocated={budget.monthlyBudget}
          consumed={budget.used}
          currency={currency}
        />
      ) : onChangeKind || showBudgetGap ? (
        <ClaimBudgetBlock
          category={claim.category}
          allocated={null}
          consumed={null}
          currency={currency}
        />
      ) : null}

      <ClaimApprovalChainBlock approvers={claim.approvers} />

      <div className="flex flex-wrap gap-2 mt-4">
        <Button
          size="sm"
          disabled={busy || !canApprove || !hasStoredFile}
          onClick={() => void onApprove()}
          data-testid="button-approve-claim"
        >
          <Check className="h-4 w-4 mr-1" /> Approve
        </Button>
        <Button
          size="sm"
          variant="outline"
          className="border-destructive/40 text-destructive"
          disabled={busy || !canReject}
          onClick={() => void onReject()}
          data-testid="button-reject-claim"
        >
          <X className="h-4 w-4 mr-1" /> Reject with reason
        </Button>
        {canRequestInfo ? (
        <Button
          size="sm"
          variant="outline"
          disabled={busy}
          onClick={() => void onRequestInfo()}
          data-testid="button-info-claim"
        >
          <HelpCircle className="h-4 w-4 mr-1" /> Request more info
        </Button>
        ) : null}
      </div>

      <DocumentAuditTrail
        docId={claim.documentRef ?? claim.id}
        invoiceId={invoiceId}
      />
    </div>
  );
}
