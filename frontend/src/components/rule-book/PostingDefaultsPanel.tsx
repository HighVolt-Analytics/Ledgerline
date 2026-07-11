import { useMemo } from "react";

import { Card } from "@/components/ui/card";
import { Select } from "@/components/ui/select";
import { coaAccountsToSelectOptions } from "@/lib/coaAccountOptions";
import { useChartOfAccounts } from "@/hooks/useChartOfAccounts";
import type { PostingDefaults } from "@/lib/v4RuleBookTypes";

type PostingDefaultsPanelProps = {
  defaults: PostingDefaults;
  onChange: (defaults: PostingDefaults) => void;
};

function AccountSelect({
  id,
  label,
  value,
  options,
  onChange,
  disabled,
}: {
  id: string;
  label: string;
  value: string;
  options: { value: string; label: string }[];
  onChange: (value: string) => void;
  disabled?: boolean;
}) {
  return (
    <div className="space-y-1.5">
      <label htmlFor={id} className="text-xs text-muted-foreground">
        {label}
      </label>
      <Select
        id={id}
        value={value}
        onValueChange={onChange}
        options={options}
        disabled={disabled}
        className="w-full"
        data-testid={id}
      />
    </div>
  );
}

export function PostingDefaultsPanel({ defaults, onChange }: PostingDefaultsPanelProps) {
  const { data: accounts = [], isLoading, isError, blocked } = useChartOfAccounts();

  const allOptions = useMemo(
    () => coaAccountsToSelectOptions(accounts, { includeEmpty: false }),
    [accounts]
  );

  if (isLoading || blocked) {
    return (
      <Card className="p-4 mb-0 text-sm text-muted-foreground" data-testid="posting-defaults-panel">
        Loading chart of accounts…
      </Card>
    );
  }

  if (isError || !accounts.length) {
    return (
      <Card className="p-4 mb-0 text-sm text-destructive" data-testid="posting-defaults-panel">
        Configure at least one account in Settings → Chart of accounts before setting posting defaults.
      </Card>
    );
  }

  return (
    <Card className="p-4 mb-0" data-testid="posting-defaults-panel">
      <h3 className="text-sm font-semibold mb-1">Posting defaults</h3>
      <p className="text-xs text-muted-foreground mb-4">
        Tax, payable, and receivable accounts apply to journal control lines. Vendor and customer
        party sub-ledgers are created under the payable / receivable ledgers you select here.
        Unmatched non-transactional documents post to the fallback account.
      </p>
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <AccountSelect
          id="posting-tax-account"
          label="Tax account"
          value={defaults.taxAccount}
          options={allOptions}
          onChange={(taxAccount) => onChange({ ...defaults, taxAccount })}
        />
        <AccountSelect
          id="posting-payable-account"
          label="Payable account"
          value={defaults.payableAccount}
          options={allOptions}
          onChange={(payableAccount) => onChange({ ...defaults, payableAccount })}
        />
        <AccountSelect
          id="posting-receivable-account"
          label="Receivable account"
          value={defaults.receivableAccount}
          options={allOptions}
          onChange={(receivableAccount) => onChange({ ...defaults, receivableAccount })}
        />
        <AccountSelect
          id="posting-fallback-account"
          label="Fallback account"
          value={defaults.fallbackAccount}
          options={allOptions}
          onChange={(fallbackAccount) => onChange({ ...defaults, fallbackAccount })}
        />
      </div>
    </Card>
  );
}
