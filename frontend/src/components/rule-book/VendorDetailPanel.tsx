import { Loader2, Shield } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Select, toSelectOptions } from "@/components/ui/select";
import { useCoaAccountOptions } from "@/hooks/useCoaAccountOptions";
import { cn } from "@/lib/cn";
import { mergeCoaOptionsWithSavedValue } from "@/lib/coaAccountOptions";
import type { VendorMaster } from "@/lib/v4RuleBookTypes";
import { BUSINESS_REGISTRATION_NUMBER_LABEL } from "@/lib/format";
import { BankDetailsSection } from "./BankDetailsSection";
import { FieldLabel } from "./FieldLabel";
import {
  reconcileSubLedgerOnLedgerChange,
  SubLedgerField,
} from "./SubLedgerField";

const VENDOR_STATUS_OPTIONS = ["Active", "On hold", "Pending registration"] as const;

function formatConfirmationStamp(value?: string | null): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
}

function normalizeLedgerValue(ledger: string): string {
  const trimmed = ledger.trim();
  return trimmed === "—" ? "" : trimmed;
}

export function VendorDetailPanel({
  vendor,
  onChange,
  masked,
  onToggleMask,
  focusBank,
  showConfirmation = true,
  className,
}: {
  vendor: VendorMaster;
  onChange: (patch: Partial<VendorMaster>) => void;
  masked: boolean;
  onToggleMask?: () => void;
  focusBank?: boolean;
  showConfirmation?: boolean;
  className?: string;
}) {
  const {
    allAccounts,
    options,
    hasRealAccounts,
    isLoading,
  } = useCoaAccountOptions({ emptyLabel: "—" });
  const ledgerValue = normalizeLedgerValue(vendor.defaultLedger);
  const ledgerOptions = mergeCoaOptionsWithSavedValue(options, ledgerValue);

  return (
    <div
      className={cn("bg-muted/20 p-4 space-y-4", focusBank && "ring-1 ring-primary/30", className)}
      data-testid={`vendor-detail-${vendor.id}`}
    >
      {showConfirmation ? (
        <p className="text-[11px] text-muted-foreground">
          Confirmation email last sent {formatConfirmationStamp(vendor.confirmationSentAt)} ·
          confirmed {formatConfirmationStamp(vendor.confirmedAt)}
        </p>
      ) : null}
      <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-2.5">
        <FieldLabel label="Name">
          <Input
            value={vendor.name}
            onChange={(e) => onChange({ name: e.target.value })}
            className="h-8 text-sm"
          />
        </FieldLabel>
        <FieldLabel label="Contact email">
          <Input
            value={vendor.contactEmail}
            onChange={(e) => onChange({ contactEmail: e.target.value })}
            placeholder="accounts@vendor.com"
            className="h-8 text-xs font-mono"
          />
        </FieldLabel>
        <FieldLabel label="Phone">
          <Input
            value={vendor.contactPhone}
            onChange={(e) => onChange({ contactPhone: e.target.value })}
            placeholder="+61 2 0000 0000"
            className="h-8 text-xs font-mono"
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
        <FieldLabel label={BUSINESS_REGISTRATION_NUMBER_LABEL}>
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
                      vendor.defaultSubLedger ?? "",
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
              Add accounts in Settings → Chart of accounts.
            </p>
          ) : null}
        </div>
        <FieldLabel label="Sub-ledger">
          <SubLedgerField
            ledger={ledgerValue}
            value={vendor.defaultSubLedger ?? ""}
            onChange={(defaultSubLedger) => onChange({ defaultSubLedger })}
            accounts={allAccounts}
            size="sm"
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
            <span className="font-medium">{ledgerValue || "—"}</span> · Cr{" "}
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
