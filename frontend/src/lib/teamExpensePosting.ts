import type { TeamExpenseKind } from "@/lib/v4RuleBookTypes";

export type TeamExpensePostingPreview = {
  debit: string;
  credit: string;
  note: string;
};

/**
 * Ledger sides each Team Expenses claim kind posts to, for review before journaling.
 * The expense ledger comes from the document type Post to; the employee advance child
 * comes from the employee master.
 */
export function teamExpensePostingPreview(
  kind: TeamExpenseKind,
  {
    expenseLedger,
    advanceLedger,
    settlementLedger,
  }: {
    expenseLedger: string;
    advanceLedger: string;
    settlementLedger: string;
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
  if (kind === "expense_against_advance") {
    return {
      debit: expense,
      credit: advance,
      note: "Spend clears the advance already given — no new cash paid.",
    };
  }
  return {
    debit: expense,
    credit: settlement,
    note: "Employee paid from their own pocket — reimbursed from settlement.",
  };
}
