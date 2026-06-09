import { Card } from "@/components/ui/card";
import {
  LEDGER_ACCOUNTS,
  PAYABLE_ACCOUNTS,
  TAX_ACCOUNTS,
  type PostingDefaults,
} from "@/lib/v4RuleBookTypes";

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
}: {
  id: string;
  label: string;
  value: string;
  options: readonly string[];
  onChange: (value: string) => void;
}) {
  return (
    <div className="space-y-1.5">
      <label htmlFor={id} className="text-xs text-muted-foreground">
        {label}
      </label>
      <select
        id={id}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-full h-9 rounded-md border border-input bg-background px-3 text-sm"
        data-testid={id}
      >
        {options.map((option) => (
          <option key={option} value={option}>
            {option}
          </option>
        ))}
      </select>
    </div>
  );
}

export function PostingDefaultsPanel({ defaults, onChange }: PostingDefaultsPanelProps) {
  return (
    <Card className="p-4 mb-0" data-testid="posting-defaults-panel">
      <h3 className="text-sm font-semibold mb-1">Posting defaults</h3>
      <p className="text-xs text-muted-foreground mb-4">
        Tax and payable accounts apply to every journal entry. Unmatched documents post to the
        fallback account.
      </p>
      <div className="grid gap-4 sm:grid-cols-3">
        <AccountSelect
          id="posting-tax-account"
          label="Tax account"
          value={defaults.taxAccount}
          options={TAX_ACCOUNTS}
          onChange={(taxAccount) => onChange({ ...defaults, taxAccount })}
        />
        <AccountSelect
          id="posting-payable-account"
          label="Payable account"
          value={defaults.payableAccount}
          options={PAYABLE_ACCOUNTS}
          onChange={(payableAccount) => onChange({ ...defaults, payableAccount })}
        />
        <AccountSelect
          id="posting-fallback-account"
          label="Fallback account"
          value={defaults.fallbackAccount}
          options={LEDGER_ACCOUNTS}
          onChange={(fallbackAccount) => onChange({ ...defaults, fallbackAccount })}
        />
      </div>
    </Card>
  );
}
