import { Loader2, Shield } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Select, toSelectOptions } from "@/components/ui/select";
import { useCoaAccountOptions } from "@/hooks/useCoaAccountOptions";
import { mergeCoaOptionsWithSavedValue } from "@/lib/coaAccountOptions";
import type { CustomerMaster } from "@/lib/v4RuleBookTypes";
import { BUSINESS_REGISTRATION_NUMBER_LABEL } from "@/lib/format";
import { FieldLabel } from "./FieldLabel";
import {
  reconcileSubLedgerOnLedgerChange,
  SubLedgerField,
} from "./SubLedgerField";

const CUSTOMER_STATUS_OPTIONS = ["Active", "On hold", "Pending registration"] as const;

function normalizeLedgerValue(ledger: string): string {
  const trimmed = ledger.trim();
  return trimmed === "—" ? "" : trimmed;
}

export function CustomerDetailPanel({
  customer,
  onChange,
}: {
  customer: CustomerMaster;
  onChange: (patch: Partial<CustomerMaster>) => void;
}) {
  const {
    allAccounts,
    options,
    hasRealAccounts,
    isLoading,
  } = useCoaAccountOptions({ emptyLabel: "—" });
  const ledgerValue = normalizeLedgerValue(customer.defaultLedger);
  const ledgerOptions = mergeCoaOptionsWithSavedValue(options, ledgerValue);

  return (
    <div className="bg-muted/20 p-4 space-y-4" data-testid={`customer-detail-${customer.id}`}>
      <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-2.5">
        <FieldLabel label="Name">
          <Input
            value={customer.name}
            onChange={(e) => onChange({ name: e.target.value })}
            className="h-8 text-sm"
          />
        </FieldLabel>
        <FieldLabel label="Aliases (comma-separated)">
          <Input
            value={customer.aliases.join(", ")}
            onChange={(e) =>
              onChange({
                aliases: e.target.value
                  .split(",")
                  .map((s) => s.trim())
                  .filter(Boolean),
              })
            }
            className="h-8 text-xs"
          />
        </FieldLabel>
        <FieldLabel label={BUSINESS_REGISTRATION_NUMBER_LABEL}>
          <Input
            value={customer.abn}
            onChange={(e) => onChange({ abn: e.target.value })}
            className="h-8 text-xs font-mono"
          />
        </FieldLabel>
        <FieldLabel label="Street">
          <Input
            value={customer.billingAddress.street}
            onChange={(e) =>
              onChange({
                billingAddress: { ...customer.billingAddress, street: e.target.value },
              })
            }
            className="h-8 text-xs"
          />
        </FieldLabel>
        <FieldLabel label="Suburb">
          <Input
            value={customer.billingAddress.suburb}
            onChange={(e) =>
              onChange({
                billingAddress: { ...customer.billingAddress, suburb: e.target.value },
              })
            }
            className="h-8 text-xs"
          />
        </FieldLabel>
        <FieldLabel label="Postcode">
          <Input
            value={customer.billingAddress.postcode}
            onChange={(e) =>
              onChange({
                billingAddress: { ...customer.billingAddress, postcode: e.target.value },
              })
            }
            className="h-8 text-xs"
          />
        </FieldLabel>
        <div className="space-y-1">
          <FieldLabel label="Default ledger">
            {isLoading ? (
              <div className="flex h-8 items-center gap-2 text-xs text-muted-foreground">
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                Loading…
              </div>
            ) : (
              <Select
                value={ledgerValue}
                onValueChange={(defaultLedger) =>
                  onChange({
                    defaultLedger,
                    defaultSubLedger: reconcileSubLedgerOnLedgerChange(
                      defaultLedger,
                      customer.defaultSubLedger,
                      allAccounts
                    ),
                  })
                }
                options={ledgerOptions}
                disabled={isLoading}
                size="sm"
                className="w-full text-xs"
              />
            )}
          </FieldLabel>
          {!isLoading && !hasRealAccounts ? (
            <p className="text-[10px] text-muted-foreground">
              No accounts in your chart — add them in Settings → Chart of accounts.
            </p>
          ) : null}
        </div>
        <FieldLabel label="Sub-ledger">
          <SubLedgerField
            ledger={ledgerValue}
            value={customer.defaultSubLedger}
            onChange={(defaultSubLedger) => onChange({ defaultSubLedger })}
            accounts={allAccounts}
            size="sm"
          />
        </FieldLabel>
        <FieldLabel label="Payment terms">
          <Input
            value={customer.paymentTerms}
            onChange={(e) => onChange({ paymentTerms: e.target.value })}
            className="h-8 text-xs"
            placeholder="Net 30"
          />
        </FieldLabel>
        <FieldLabel label="Status">
          <Select
            value={customer.status}
            onValueChange={(status) => onChange({ status })}
            options={toSelectOptions([...CUSTOMER_STATUS_OPTIONS])}
            size="sm"
            className="w-full text-xs"
          />
        </FieldLabel>
      </div>
      <div className="flex items-center gap-2 text-xs text-muted-foreground">
        <Shield className="h-3.5 w-3.5" />
        Revenue YTD and invoice counts are updated from posted sales documents.
      </div>
    </div>
  );
}
