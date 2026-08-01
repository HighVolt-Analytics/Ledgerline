import { useMemo } from "react";

import { Card } from "@/components/ui/card";
import { Select } from "@/components/ui/select";
import { coaAccountsToSelectOptions } from "@/lib/coaAccountOptions";
import { useChartOfAccounts } from "@/hooks/useChartOfAccounts";
import type { TeamExpensePostingDefaults } from "@/lib/v4RuleBookTypes";

type TeamExpensePostingPanelProps = {
  defaults: TeamExpensePostingDefaults;
  onChange: (defaults: TeamExpensePostingDefaults) => void;
};

export function TeamExpensePostingPanel({ defaults, onChange }: TeamExpensePostingPanelProps) {
  const { data: accounts = [], isLoading, isError, blocked } = useChartOfAccounts();

  const allOptions = useMemo(
    () => coaAccountsToSelectOptions(accounts, { includeEmpty: false }),
    [accounts]
  );

  if (isLoading || blocked) {
    return (
      <Card className="p-4 mb-0 text-sm text-muted-foreground" data-testid="team-expense-posting-panel">
        Loading chart of accounts…
      </Card>
    );
  }

  if (isError || !accounts.length) {
    return (
      <Card className="p-4 mb-0 text-sm text-destructive" data-testid="team-expense-posting-panel">
        Configure at least one account in Settings → Chart of accounts before setting team expense
        posting.
      </Card>
    );
  }

  return (
    <Card className="p-4 mb-0" data-testid="team-expense-posting-panel">
      <h3 className="text-sm font-semibold mb-1">Team expense posting</h3>
      <p className="text-xs text-muted-foreground mb-4">
        Advance requisitions debit the employee sub-ledger under their advance parent and credit
        settlement. Expense claims credit settlement; expenses against an advance credit the
        employee sub-ledger instead. Expense ledgers still come from document type Post to.
      </p>
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="space-y-1.5">
          <label htmlFor="team-advance-parent" className="text-xs text-muted-foreground">
            Default advance parent ledger
          </label>
          <Select
            id="team-advance-parent"
            value={defaults.defaultAdvanceParentLedger}
            onValueChange={(defaultAdvanceParentLedger) =>
              onChange({ ...defaults, defaultAdvanceParentLedger })
            }
            options={allOptions}
            className="w-full"
            data-testid="team-advance-parent"
          />
        </div>
        <div className="space-y-1.5">
          <label htmlFor="team-settlement-account" className="text-xs text-muted-foreground">
            Settlement account
          </label>
          <Select
            id="team-settlement-account"
            value={defaults.settlementAccount}
            onValueChange={(settlementAccount) => onChange({ ...defaults, settlementAccount })}
            options={allOptions}
            className="w-full"
            data-testid="team-settlement-account"
          />
        </div>
      </div>
    </Card>
  );
}
