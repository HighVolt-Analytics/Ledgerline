import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import {
  BANK_ACCOUNTS,
  FX_GAIN_LOSS_ACCOUNTS,
  type FxPostingPolicy,
} from "@/lib/v4RuleBookTypes";

const RATE_SOURCES = [
  { value: "invoice_date", label: "Invoice date" },
  { value: "payment_date", label: "Payment date" },
  { value: "po_date", label: "PO date" },
  { value: "static_table", label: "Static rate table" },
  { value: "manual", label: "Manual override" },
] as const;

export function defaultFxPostingPolicy(): FxPostingPolicy {
  return {
    functionalCurrency: "AUD",
    fxGainLossAccount: "FX Gain/Loss",
    bankAccount: "Bank",
    bookingRateSource: "invoice_date",
    paymentRateSource: "payment_date",
    requirePoInvoiceCurrencyMatch: true,
    grnCurrencyOperationalOnly: true,
  };
}

type FxPostingPolicyEditorProps = {
  value: FxPostingPolicy | undefined;
  onChange: (next: FxPostingPolicy | undefined) => void;
  disabled?: boolean;
};

export function FxPostingPolicyEditor({
  value,
  onChange,
  disabled,
}: FxPostingPolicyEditorProps) {
  const enabled = value != null;
  const policy = value ?? defaultFxPostingPolicy();

  const patch = (partial: Partial<FxPostingPolicy>) => {
    onChange({ ...policy, ...partial });
  };

  return (
    <div className="space-y-4" data-testid="fx-posting-policy-editor">
      <div className="flex items-center justify-between gap-3">
        <div>
          <p className="text-sm font-medium">Foreign exchange posting</p>
          <p className="text-xs text-muted-foreground">
            Book AP at invoice-date rate; post FX gain/loss when paying in functional currency.
          </p>
        </div>
        <Switch
          checked={enabled}
          disabled={disabled}
          onCheckedChange={(checked) => onChange(checked ? defaultFxPostingPolicy() : undefined)}
          aria-label="Enable FX policy override"
        />
      </div>

      {enabled ? (
        <div className="grid gap-4 sm:grid-cols-2">
          <div className="space-y-1.5">
            <label htmlFor="fx-functional-currency" className="text-xs text-muted-foreground">
              Functional currency
            </label>
            <Input
              id="fx-functional-currency"
              value={policy.functionalCurrency ?? "AUD"}
              disabled={disabled}
              onChange={(e) => patch({ functionalCurrency: e.target.value.toUpperCase() })}
              className="h-9 font-mono text-sm uppercase"
              maxLength={3}
            />
          </div>
          <div className="space-y-1.5">
            <label htmlFor="fx-gain-loss-account" className="text-xs text-muted-foreground">
              FX gain / loss account
            </label>
            <select
              id="fx-gain-loss-account"
              value={policy.fxGainLossAccount ?? "FX Gain/Loss"}
              disabled={disabled}
              onChange={(e) => patch({ fxGainLossAccount: e.target.value })}
              className="h-9 w-full rounded-md border border-input bg-background px-3 text-sm"
            >
              {FX_GAIN_LOSS_ACCOUNTS.map((option) => (
                <option key={option} value={option}>
                  {option}
                </option>
              ))}
            </select>
          </div>
          <div className="space-y-1.5">
            <label htmlFor="fx-bank-account" className="text-xs text-muted-foreground">
              Bank account (payment)
            </label>
            <select
              id="fx-bank-account"
              value={policy.bankAccount ?? "Bank"}
              disabled={disabled}
              onChange={(e) => patch({ bankAccount: e.target.value })}
              className="h-9 w-full rounded-md border border-input bg-background px-3 text-sm"
            >
              {BANK_ACCOUNTS.map((option) => (
                <option key={option} value={option}>
                  {option}
                </option>
              ))}
            </select>
          </div>
          <div className="space-y-1.5">
            <label htmlFor="fx-booking-rate" className="text-xs text-muted-foreground">
              Booking rate source
            </label>
            <select
              id="fx-booking-rate"
              value={policy.bookingRateSource ?? "invoice_date"}
              disabled={disabled}
              onChange={(e) =>
                patch({
                  bookingRateSource: e.target.value as FxPostingPolicy["bookingRateSource"],
                })
              }
              className="h-9 w-full rounded-md border border-input bg-background px-3 text-sm"
            >
              {RATE_SOURCES.map((row) => (
                <option key={row.value} value={row.value}>
                  {row.label}
                </option>
              ))}
            </select>
          </div>
          <div className="space-y-1.5">
            <label htmlFor="fx-payment-rate" className="text-xs text-muted-foreground">
              Payment rate source
            </label>
            <select
              id="fx-payment-rate"
              value={policy.paymentRateSource ?? "payment_date"}
              disabled={disabled}
              onChange={(e) =>
                patch({
                  paymentRateSource: e.target.value as FxPostingPolicy["paymentRateSource"],
                })
              }
              className="h-9 w-full rounded-md border border-input bg-background px-3 text-sm"
            >
              {RATE_SOURCES.map((row) => (
                <option key={row.value} value={row.value}>
                  {row.label}
                </option>
              ))}
            </select>
          </div>
          <div className="sm:col-span-2 space-y-3 rounded-md border border-border p-3">
            <label className="flex items-center justify-between gap-3 text-sm">
              <span>Require PO and invoice currency match</span>
              <Switch
                checked={policy.requirePoInvoiceCurrencyMatch !== false}
                disabled={disabled}
                onCheckedChange={(checked) => patch({ requirePoInvoiceCurrencyMatch: checked })}
              />
            </label>
            <label className="flex items-center justify-between gap-3 text-sm">
              <span>GRN currency operational only (qty match, not FX amounts)</span>
              <Switch
                checked={policy.grnCurrencyOperationalOnly !== false}
                disabled={disabled}
                onCheckedChange={(checked) => patch({ grnCurrencyOperationalOnly: checked })}
              />
            </label>
          </div>
        </div>
      ) : (
        <p className="text-xs text-muted-foreground">
          Uses org-wide posting defaults on the Posting tab.
        </p>
      )}
    </div>
  );
}

export function FxPostingPolicySummary({ policy }: { policy?: FxPostingPolicy }) {
  if (!policy) {
    return <p className="text-sm text-muted-foreground">Org posting defaults</p>;
  }
  return (
    <dl className="space-y-1 text-sm">
      <div className="flex justify-between gap-2">
        <dt className="text-muted-foreground">Functional</dt>
        <dd className="font-medium">{policy.functionalCurrency ?? "AUD"}</dd>
      </div>
      <div className="flex justify-between gap-2">
        <dt className="text-muted-foreground">FX G/L</dt>
        <dd className="font-medium">{policy.fxGainLossAccount ?? "FX Gain/Loss"}</dd>
      </div>
    </dl>
  );
}
