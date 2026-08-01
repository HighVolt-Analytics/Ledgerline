import { useEffect, useState } from "react";
import { Check, ExternalLink, HelpCircle, X } from "lucide-react";
import type { InvoiceStatus } from "@/api/types";
import { ApprovalPolicyNote } from "@/components/ApprovalPolicyNote";
import { ApproverChip } from "@/components/ApproverChip";
import { DocumentAuditTrail } from "@/components/DocumentAuditTrail";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { NumericInput } from "@/components/ui/numeric-input";
import { cn } from "@/lib/cn";
import { money } from "@/lib/format";
import type { ExpenseBudget, ExpenseClaim } from "@/lib/v4MockData";
import type { TeamExpenseKind } from "@/lib/v4RuleBookTypes";
import { BudgetUtilBar } from "./BudgetUtilBar";
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
  advanceBalance?: number;
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
  // (e.g. advance 1000 stuck on against-advance 250 after kind toggle).
  const [amount, setAmount] = useState(claim.amount);
  useEffect(() => {
    setAmount(claim.amount);
  }, [claim.id, claim.amount]);

  const editable =
    (claim.state === "New" || claim.state === "In Review") &&
    invoiceStatus !== "processed" &&
    invoiceStatus !== "rejected";
  const netAdvance = advanceBalance ?? claim.advanceBalance ?? 0;
  const claimAmount = Number.isFinite(amount) ? amount : claim.amount;
  const remainingAfterClaim = netAdvance - claimAmount;
  const againstAdvanceOver =
    claim.kind === "expense_against_advance" && claimAmount > netAdvance;
  const fmt = (n: number) => money(n, currency);

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
          <DetailField label="Advance left" value={fmt(netAdvance)} mono />
          {claim.kind === "expense_against_advance" ? (
            <>
              <DetailField label="This claim" value={fmt(claimAmount)} mono />
              <div>
                <div className="text-[11px] text-muted-foreground uppercase tracking-wide">
                  Remaining after claim
                </div>
                <div
                  className={cn(
                    "text-sm tnum",
                    againstAdvanceOver && "ds-warning-text font-medium"
                  )}
                  data-testid="claim-remaining-after-advance"
                >
                  {fmt(remainingAfterClaim)}
                  {againstAdvanceOver ? " — exceeds available advance" : ""}
                </div>
              </div>
            </>
          ) : null}
        </div>
      </div>

      {onChangeKind && (
        <ClaimKindField
          kind={claim.kind}
          expenseLedger={claim.category}
          advanceLedger={advanceLedger}
          settlementLedger={settlementLedger}
          disabled={busy || !editable}
          onChange={(kind) => void onChangeKind(kind)}
        />
      )}

      {!hasStoredFile && canApprove && (
        <p className="text-xs ds-warning-text mt-3">
          Upload a receipt before this claim can be approved.
        </p>
      )}

      {budget && (
        <Card className="p-3 mt-3 bg-muted/30">
          <div className="text-xs font-medium mb-1.5">
            {budget.category} — {budget.period} · {fmt(budget.used)} used of{" "}
            {fmt(budget.monthlyBudget)} ({Math.round((budget.used / budget.monthlyBudget) * 100)}
            %)
          </div>
          <BudgetUtilBar used={budget.used} total={budget.monthlyBudget} />
        </Card>
      )}

      <div className="mt-3">
        <div className="text-[11px] text-muted-foreground uppercase tracking-wide mb-1.5">
          Approval chain
        </div>
        <div className="flex flex-wrap gap-1.5">
          {claim.approvers.length > 0 ? (
            claim.approvers.map((a) => <ApproverChip key={a.id} {...a} />)
          ) : (
            <span className="text-xs text-muted-foreground">Awaiting approver assignment</span>
          )}
        </div>
        <div className="mt-1.5">
          <ApprovalPolicyNote />
        </div>
      </div>

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
        <Button
          size="sm"
          variant="outline"
          disabled={busy || !canRequestInfo}
          onClick={() => void onRequestInfo()}
          data-testid="button-info-claim"
        >
          <HelpCircle className="h-4 w-4 mr-1" /> Request more info
        </Button>
      </div>

      <DocumentAuditTrail
        docId={claim.documentRef ?? claim.id}
        invoiceId={invoiceId}
      />
    </div>
  );
}
