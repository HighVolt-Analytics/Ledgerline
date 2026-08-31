import { ApprovalPolicyNote } from "@/components/ApprovalPolicyNote";
import { ApproverChip } from "@/components/ApproverChip";
import { Card } from "@/components/ui/card";
import { ClaimKindField } from "@/components/team-expenses/ClaimKindField";
import { BudgetUtilBar } from "@/components/team-expenses/BudgetUtilBar";
import {
  advanceBalanceDisplay,
  budgetUtilizationDisplay,
} from "@/lib/documentRowActions";
import { money } from "@/lib/format";
import { approvalChainToApproverSteps } from "@/lib/approvalQuorum";
import type { ApprovalChain } from "@/api/types";
import type { ApproverStep } from "@/lib/v4MockData";
import type { TeamExpenseKind } from "@/lib/v4RuleBookTypes";

export function ClaimApprovalChainBlock({
  approvalChain,
  approvers: approversProp,
}: {
  approvalChain?: ApprovalChain | null;
  approvers?: ApproverStep[];
}) {
  const approvers =
    approversProp ?? approvalChainToApproverSteps(approvalChain);
  return (
    <div className="mt-3" data-testid="claim-approval-chain">
      <div className="text-[11px] text-muted-foreground uppercase tracking-wide mb-1.5">
        Approval chain
      </div>
      <div className="flex flex-wrap gap-1.5">
        {approvers.length > 0 ? (
          approvers.map((a) => <ApproverChip key={a.id} {...a} />)
        ) : (
          <span className="text-xs text-muted-foreground">Awaiting first approval</span>
        )}
      </div>
      {approvers.some((a) => a.state === "pending") &&
      approvers.some((a) => a.state === "approved") ? (
        <p className="text-xs text-muted-foreground mt-1">
          {approvers.filter((a) => a.state === "approved").length} of {approvers.length}{" "}
          approved
        </p>
      ) : null}
      <div className="mt-1.5">
        <ApprovalPolicyNote />
      </div>
    </div>
  );
}

export function ClaimBudgetBlock({
  category,
  period = "MTD",
  allocated,
  consumed,
  currency,
}: {
  category: string;
  period?: string;
  allocated: number | null | undefined;
  consumed: number | null | undefined;
  currency: string;
}) {
  const display = budgetUtilizationDisplay(allocated, consumed);
  if (display.kind === "missing") {
    return (
      <Card className="p-3 mt-3 bg-muted/30" data-testid="claim-budget-gap">
        <div className="text-xs text-muted-foreground">{display.message}</div>
        {category ? (
          <div className="text-[11px] text-muted-foreground mt-1 truncate">{category}</div>
        ) : null}
      </Card>
    );
  }
  const fmt = (n: number) => money(n, currency);
  return (
    <Card className="p-3 mt-3 bg-muted/30" data-testid="claim-budget-bar">
      <div className="text-xs font-medium mb-1.5">
        {category || "Budget"} — {period} · {fmt(display.used)} used of {fmt(display.total)} (
        {display.pct}%)
      </div>
      <BudgetUtilBar used={display.used} total={display.total} />
    </Card>
  );
}

export function ClaimAdvanceBlock({
  matched,
  advanceBalance,
  advanceFloat,
  currency,
}: {
  matched: boolean;
  advanceBalance: number | null | undefined;
  advanceFloat?: number | null | undefined;
  currency: string;
}) {
  const display = advanceBalanceDisplay(matched, advanceBalance, advanceFloat);
  if (display.kind === "missing") {
    return (
      <div className="mt-3" data-testid="claim-advance-gap">
        <div className="text-[11px] text-muted-foreground uppercase tracking-wide mb-1">
          Advance
        </div>
        <p className="text-xs text-muted-foreground">{display.message}</p>
      </div>
    );
  }
  const fmt = (n: number) => money(n, currency);
  if (display.kind === "consumed") {
    return (
      <Card className="p-3 mt-3 bg-muted/30" data-testid="claim-advance-bar">
        <div className="text-xs font-medium mb-1.5">
          Advance — {fmt(display.used)} used of {fmt(display.total)} ({display.pct}%) ·{" "}
          {fmt(display.remaining)} left
        </div>
        <BudgetUtilBar used={display.used} total={display.total} />
      </Card>
    );
  }
  return (
    <div className="mt-3" data-testid="claim-advance-remaining">
      <div className="text-[11px] text-muted-foreground uppercase tracking-wide mb-1">
        Advance left
      </div>
      <div className="text-sm tnum">{fmt(display.remaining)}</div>
    </div>
  );
}

/** Team/Expenses claim review blocks for the invoice drawer Fields tab. */
export function InvoiceClaimReviewSection({
  showKind,
  kind,
  expenseLedger,
  advanceLedger,
  settlementLedger,
  claimAmount,
  advanceAvailable,
  kindDisabled,
  onChangeKind,
  showAdvance,
  matchedEmployee,
  advanceBalance,
  advanceFloat,
  showBudget,
  budgetCategory,
  budgetAllocated,
  budgetConsumed,
  currency,
  approvalChain,
}: {
  showKind?: boolean;
  kind?: TeamExpenseKind;
  expenseLedger?: string;
  advanceLedger?: string;
  settlementLedger?: string;
  claimAmount?: number;
  advanceAvailable?: number;
  kindDisabled?: boolean;
  onChangeKind?: (kind: TeamExpenseKind) => void | Promise<void>;
  showAdvance?: boolean;
  matchedEmployee?: boolean;
  advanceBalance?: number | null;
  advanceFloat?: number | null;
  showBudget?: boolean;
  budgetCategory?: string;
  budgetAllocated?: number | null;
  budgetConsumed?: number | null;
  currency: string;
  approvalChain?: ApprovalChain | null;
}) {
  return (
    <div className="mt-4 space-y-0" data-testid="invoice-claim-review">
      {showKind && kind && onChangeKind ? (
        <ClaimKindField
          kind={kind}
          expenseLedger={expenseLedger ?? ""}
          advanceLedger={advanceLedger ?? ""}
          settlementLedger={settlementLedger ?? ""}
          claimAmount={claimAmount ?? 0}
          advanceAvailable={advanceAvailable ?? 0}
          disabled={Boolean(kindDisabled)}
          onChange={(next) => void onChangeKind(next)}
        />
      ) : null}
      {showAdvance ? (
        <ClaimAdvanceBlock
          matched={Boolean(matchedEmployee)}
          advanceBalance={advanceBalance}
          advanceFloat={advanceFloat}
          currency={currency}
        />
      ) : null}
      {showBudget ? (
        <ClaimBudgetBlock
          category={budgetCategory ?? ""}
          allocated={budgetAllocated}
          consumed={budgetConsumed}
          currency={currency}
        />
      ) : null}
      <ClaimApprovalChainBlock approvalChain={approvalChain} />
    </div>
  );
}
