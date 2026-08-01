import type { ChartOfAccountRow } from "@/api/types";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import {
  ledgerHasSubLedgerCatalog,
  subLedgersForLedger,
  subLedgersToSelectOptions,
} from "@/lib/coaAccountOptions";

type SubLedgerFieldProps = {
  ledger: string;
  value: string;
  onChange: (subLedger: string) => void;
  accounts: ChartOfAccountRow[];
  disabled?: boolean;
  placeholder?: string;
  className?: string;
  size?: "sm" | "md";
  includeEmpty?: boolean;
  emptyLabel?: string;
  "data-testid"?: string;
};

export function SubLedgerField({
  ledger,
  value,
  onChange,
  accounts,
  disabled,
  placeholder = "Optional",
  className,
  size = "md",
  includeEmpty = true,
  emptyLabel = "— Optional —",
  "data-testid": dataTestId,
}: SubLedgerFieldProps) {
  const ledgerTrimmed = ledger.trim();
  const hasCatalog = ledgerHasSubLedgerCatalog(ledgerTrimmed, accounts);
  const catalog = hasCatalog ? subLedgersForLedger(ledgerTrimmed, accounts) : [];

  if (!ledgerTrimmed) {
    return (
      <Input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className={className ?? (size === "sm" ? "h-8 text-xs" : "h-9 text-sm")}
        disabled
        placeholder="Select ledger first"
        data-testid={dataTestId}
      />
    );
  }

  if (hasCatalog) {
    return (
      <Select
        value={value}
        onValueChange={onChange}
        options={subLedgersToSelectOptions(catalog, { includeEmpty, emptyLabel })}
        disabled={disabled}
        className={className ?? "w-full"}
        size={size}
        data-testid={dataTestId}
      />
    );
  }

  return (
    <Input
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className={className ?? (size === "sm" ? "h-8 text-xs" : "h-9 text-sm")}
      disabled={disabled}
      placeholder={placeholder}
      data-testid={dataTestId}
    />
  );
}

/** Clear sub-ledger when ledger changes and current value is not valid for the new parent. */
export function reconcileSubLedgerOnLedgerChange(
  nextLedger: string,
  currentSubLedger: string,
  accounts: ChartOfAccountRow[]
): string {
  const sub = currentSubLedger.trim();
  if (!sub) return "";
  if (!ledgerHasSubLedgerCatalog(nextLedger, accounts)) return sub;
  const catalog = subLedgersForLedger(nextLedger, accounts);
  const match = catalog.some((row) => row.name.toLowerCase() === sub.toLowerCase());
  return match ? sub : "";
}
