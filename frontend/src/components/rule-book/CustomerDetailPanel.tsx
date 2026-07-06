import { Shield } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Select, toSelectOptions } from "@/components/ui/select";
import { useChartOfAccounts } from "@/hooks/useChartOfAccounts";
import type { CustomerMaster } from "@/lib/v4RuleBookTypes";
import { LEDGER_ACCOUNTS } from "@/lib/v4RuleBookTypes";
import { FieldLabel } from "./FieldLabel";
import {
  reconcileSubLedgerOnLedgerChange,
  SubLedgerField,
} from "./SubLedgerField";

const CUSTOMER_LEDGER_OPTIONS = [
  "—",
  ...LEDGER_ACCOUNTS.filter(
    (a) =>
      ![
        "GST Paid",
        "Sales Tax Paid",
        "GST Input Credit",
        "VAT Paid",
        "Accounts Payable",
        "Suspense Account",
      ].includes(a)
  ),
];

const CUSTOMER_STATUS_OPTIONS = ["Active", "On hold", "Pending registration"] as const;

export function CustomerDetailPanel({
  customer,
  onChange,
}: {
  customer: CustomerMaster;
  onChange: (patch: Partial<CustomerMaster>) => void;
}) {
  const { data: coaAccounts = [] } = useChartOfAccounts();
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
        <FieldLabel label="ABN / Tax ID">
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
        <FieldLabel label="Default ledger">
          <Select
            value={customer.defaultLedger || "—"}
            onValueChange={(defaultLedger) =>
              onChange({
                defaultLedger: defaultLedger === "—" ? "" : defaultLedger,
                defaultSubLedger: reconcileSubLedgerOnLedgerChange(
                  defaultLedger === "—" ? "" : defaultLedger,
                  customer.defaultSubLedger,
                  coaAccounts
                ),
              })
            }
            options={toSelectOptions(CUSTOMER_LEDGER_OPTIONS)}
            size="sm"
            className="w-full text-xs"
          />
        </FieldLabel>
        <FieldLabel label="Sub-ledger">
          <SubLedgerField
            ledger={customer.defaultLedger}
            value={customer.defaultSubLedger}
            onChange={(defaultSubLedger) => onChange({ defaultSubLedger })}
            accounts={coaAccounts}
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
