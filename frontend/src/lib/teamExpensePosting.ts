import type { TeamExpenseKind } from "@/lib/v4RuleBookTypes";

export type TeamExpensePostingPreview = {
  debit: string;
  credit: string;
  note: string;
};

function money(n: number): string {
  return n.toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

/**
 * Ledger sides each Team Expenses claim kind posts to, for review before journaling.
 * Expense claims partially net available Staff Advance, then pay the rest from settlement.
 */
export function teamExpensePostingPreview(
  kind: TeamExpenseKind,
  {
    expenseLedger,
    advanceLedger,
    settlementLedger,
    claimAmount = 0,
    advanceAvailable = 0,
  }: {
    expenseLedger: string;
    advanceLedger: string;
    settlementLedger: string;
    claimAmount?: number;
    advanceAvailable?: number;
  }
): TeamExpensePostingPreview {
  const expense = expenseLedger.trim() || "Expense ledger";
  const advance = advanceLedger.trim() || "Staff advance";
  const settlement = settlementLedger.trim() || "Settlement";

  if (kind === "advance_requisition") {
    return {
      debit: advance,
      credit: settlement,
      note: "Money paid out — the employee now holds an advance.",
    };
  }

  if (kind === "direct_payment") {
    return {
      debit: expense,
      credit: settlement,
      note: "Company direct spend — no advance netting.",
    };
  }

  const total = Number.isFinite(claimAmount) ? Math.max(0, claimAmount) : 0;
  const available = Number.isFinite(advanceAvailable) ? Math.max(0, advanceAvailable) : 0;
  const netAdvance = Math.min(total, available);
  const settle = Math.max(0, total - netAdvance);

  if (netAdvance > 0 && settle > 0) {
    return {
      debit: expense,
      credit: `${advance} (${money(netAdvance)}) + ${settlement} (${money(settle)})`,
      note: `Nets ${money(netAdvance)} advance; company pays the ${money(settle)} difference. Budget is checked on the full claim.`,
    };
  }
  if (netAdvance > 0) {
    return {
      debit: expense,
      credit: advance,
      note: "Fully cleared against the employee’s outstanding advance — no new cash paid.",
    };
  }
  return {
    debit: expense,
    credit: settlement,
    note: "No advance float available — reimbursed from settlement.",
  };
}
