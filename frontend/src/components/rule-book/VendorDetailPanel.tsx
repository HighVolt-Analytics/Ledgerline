import { Shield } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Select, toSelectOptions } from "@/components/ui/select";
import { cn } from "@/lib/cn";
import type { VendorMaster } from "@/lib/v4RuleBookTypes";
import { LEDGER_ACCOUNTS } from "@/lib/v4RuleBookTypes";
import { BankDetailsSection } from "./BankDetailsSection";
import { FieldLabel } from "./FieldLabel";

const VENDOR_LEDGER_OPTIONS = [
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

const VENDOR_STATUS_OPTIONS = ["Active", "On hold", "Pending registration"] as const;

export function VendorDetailPanel({
  vendor,
  onChange,
  masked,
  onToggleMask,
  focusBank,
}: {
  vendor: VendorMaster;
  onChange: (patch: Partial<VendorMaster>) => void;
  masked: boolean;
  onToggleMask?: () => void;
  focusBank?: boolean;
}) {
  return (
    <div
      className={cn("bg-muted/20 p-4 space-y-4", focusBank && "ring-1 ring-primary/30")}
      data-testid={`vendor-detail-${vendor.id}`}
    >
      <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-2.5">
        <FieldLabel label="Name">
          <Input
            value={vendor.name}
            onChange={(e) => onChange({ name: e.target.value })}
            className="h-8 text-sm"
          />
        </FieldLabel>
        <FieldLabel label="Aliases (comma-separated)">
          <Input
            value={vendor.aliases.join(", ")}
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
            value={vendor.abn}
            onChange={(e) => onChange({ abn: e.target.value })}
            className="h-8 text-xs font-mono"
          />
        </FieldLabel>
        <FieldLabel label="Street">
          <Input
            value={vendor.billingAddress.street}
            onChange={(e) =>
              onChange({
                billingAddress: { ...vendor.billingAddress, street: e.target.value },
              })
            }
            className="h-8 text-xs"
          />
        </FieldLabel>
        <FieldLabel label="Suburb">
          <Input
            value={vendor.billingAddress.suburb}
            onChange={(e) =>
              onChange({
                billingAddress: { ...vendor.billingAddress, suburb: e.target.value },
              })
            }
            className="h-8 text-xs"
          />
        </FieldLabel>
        <FieldLabel label="Postcode">
          <Input
            value={vendor.billingAddress.postcode}
            onChange={(e) =>
              onChange({
                billingAddress: { ...vendor.billingAddress, postcode: e.target.value },
              })
            }
            className="h-8 text-xs font-mono"
          />
        </FieldLabel>
      </div>

      <BankDetailsSection
        bank={vendor.bank}
        onChange={(bank) => onChange({ bank })}
        masked={focusBank ? false : masked}
        onToggleMask={onToggleMask}
      />

      <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-2.5">
        <FieldLabel label="Default ledger">
          <Select
            value={vendor.defaultLedger}
            onValueChange={(defaultLedger) => onChange({ defaultLedger })}
            options={toSelectOptions(VENDOR_LEDGER_OPTIONS)}
            size="sm"
            className="w-full text-xs"
          />
        </FieldLabel>
        <FieldLabel label="Sub-ledger">
          <Input
            value={vendor.defaultSubLedger ?? ""}
            onChange={(e) => onChange({ defaultSubLedger: e.target.value })}
            className="h-8 text-xs"
          />
        </FieldLabel>
        <FieldLabel label="Payment terms">
          <Input
            value={vendor.paymentTerms}
            onChange={(e) => onChange({ paymentTerms: e.target.value })}
            className="h-8 text-xs"
          />
        </FieldLabel>
        <FieldLabel label="Status">
          <Select
            value={vendor.status}
            onValueChange={(status) => onChange({ status })}
            options={toSelectOptions(VENDOR_STATUS_OPTIONS)}
            size="sm"
            className="w-full text-xs"
          />
        </FieldLabel>
      </div>

      <div className="rounded-lg border border-border bg-background p-3">
        <div className="flex items-center gap-2 mb-2 text-xs font-semibold text-muted-foreground">
          <Shield className="h-3.5 w-3.5 text-primary" />
          Posting preview
        </div>
        <ul className="space-y-1 text-xs">
          <li>
            <span className="text-muted-foreground">Invoice received:</span> Dr{" "}
            <span className="font-medium">{vendor.defaultLedger}</span> · Cr{" "}
            <span className="font-medium">Accounts Payable</span>
          </li>
          <li>
            <span className="text-muted-foreground">Payment executed:</span> Dr{" "}
            <span className="font-medium">Accounts Payable</span> · Cr{" "}
            <span className="font-medium">Stripe Wallet</span>
          </li>
          <li>
            <span className="text-muted-foreground">Reconciliation:</span> posted to Ledger Link
            export
          </li>
        </ul>
      </div>
    </div>
  );
}
