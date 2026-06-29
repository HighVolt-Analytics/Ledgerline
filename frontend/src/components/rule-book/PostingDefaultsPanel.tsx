import { Card } from "@/components/ui/card";
import {
  BANK_ACCOUNTS,
  CURRENCY_CODES,
  FX_GAIN_LOSS_ACCOUNTS,
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
    <div className="space-y-4">
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

      <Card className="p-4 mb-0" data-testid="posting-fx-defaults-panel">
        <h3 className="text-sm font-semibold mb-1">Foreign exchange (org default)</h3>
        <p className="text-xs text-muted-foreground mb-4">
          Book foreign invoices at invoice-date rate into functional currency. Payment variance
          posts to the FX gain/loss account. Document types can override these rules.
        </p>
        <div className="grid gap-4 sm:grid-cols-3">
          <div className="space-y-1.5">
            <label htmlFor="posting-functional-currency" className="text-xs text-muted-foreground">
              Functional currency
            </label>
            <select
              id="posting-functional-currency"
              value={defaults.functionalCurrency ?? "AUD"}
              onChange={(e) => onChange({ ...defaults, functionalCurrency: e.target.value })}
              className="w-full h-9 rounded-md border border-input bg-background px-3 text-sm font-mono"
            >
              {CURRENCY_CODES.map((code) => (
                <option key={code} value={code}>
                  {code}
                </option>
              ))}
            </select>
          </div>
          <AccountSelect
            id="posting-fx-gain-loss"
            label="FX gain / loss account"
            value={defaults.fxGainLossAccount ?? "FX Gain/Loss"}
            options={FX_GAIN_LOSS_ACCOUNTS}
            onChange={(fxGainLossAccount) => onChange({ ...defaults, fxGainLossAccount })}
          />
          <AccountSelect
            id="posting-bank-account"
            label="Bank account"
            value={defaults.bankAccount ?? "Bank"}
            options={BANK_ACCOUNTS}
            onChange={(bankAccount) => onChange({ ...defaults, bankAccount })}
          />
        </div>
      </Card>
    </div>
  );
}
