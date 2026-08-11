import { useEffect, useMemo, useState } from "react";
import { Sparkles } from "lucide-react";

import type { LineItem } from "@/api/types";
import { SubLedgerField } from "@/components/rule-book/SubLedgerField";
import { Select } from "@/components/ui/select";
import { useChartOfAccounts } from "@/hooks/useChartOfAccounts";
import {
  coaAccountsToSelectOptions,
  ledgerHasSubLedgerCatalog,
  mergeCoaOptionsWithSavedValue,
} from "@/lib/coaAccountOptions";
import { cn } from "@/lib/cn";
import {
  effectiveLineLedger,
  lineGlMappingReason,
  lineSubLedgerRequired,
  suggestLineSubLedger,
} from "@/lib/lineGlAccount";

type LineGlAccountCellProps = {
  line: LineItem;
  parentLedger: string;
  postingApplies: boolean;
  onSubLedgerChange?: (subLedger: string) => void;
  editable?: boolean;
};

export function LineGlAccountCell({
  line,
  parentLedger,
  postingApplies,
  onSubLedgerChange,
  editable = false,
}: LineGlAccountCellProps) {
  const { data: accounts = [] } = useChartOfAccounts();
  const hasCatalog = ledgerHasSubLedgerCatalog(parentLedger, accounts);
  const required = lineSubLedgerRequired(line, parentLedger, accounts);
  const suggested = useMemo(
    () => suggestLineSubLedger(line, accounts, parentLedger),
    [accounts, line, parentLedger]
  );
  const [subLedger, setSubLedger] = useState(line.sub_ledger?.trim() ?? suggested);

  useEffect(() => {
    setSubLedger(line.sub_ledger?.trim() ?? suggested);
  }, [line.sub_ledger, line.id, suggested]);

  const parentOptions = useMemo(
    () =>
      mergeCoaOptionsWithSavedValue(
        coaAccountsToSelectOptions(accounts, {
          includeEmpty: true,
          emptyLabel: required ? "— Select GL —" : "— Optional —",
        }),
        subLedger
      ),
    [accounts, required, subLedger]
  );

  if (!postingApplies) {
    return (
      <span className="text-xs text-muted-foreground">Not posted — reference document</span>
    );
  }

  const reason = lineGlMappingReason(line, parentLedger, hasCatalog);
  const displayLedger = effectiveLineLedger(line, parentLedger);

  // Editable: always offer a GL picker (sub-ledger under parent, or any COA account).
  if (editable && onSubLedgerChange) {
    if (!parentLedger.trim()) {
      return (
        <div className="space-y-1">
          <Select
            value={subLedger}
            onValueChange={(value) => {
              setSubLedger(value);
              onSubLedgerChange(value);
            }}
            options={parentOptions}
            className="invoice-drawer-gl-select w-full"
            data-testid="invoice-gl-select"
            size="sm"
          />
          <p className="text-[10px] text-muted-foreground">
            Pick a GL account for this line
          </p>
        </div>
      );
    }

    if (hasCatalog) {
      return (
        <div className={cn(required && "rounded-md ring-1 ring-destructive/40 p-1")}>
          <p className="text-[10px] text-muted-foreground mb-1 truncate" title={parentLedger}>
            {parentLedger}
          </p>
          <SubLedgerField
            ledger={parentLedger}
            value={subLedger}
            onChange={(value) => {
              setSubLedger(value);
              onSubLedgerChange(value);
            }}
            accounts={accounts}
            className="invoice-drawer-gl-select w-full"
            data-testid="invoice-gl-select"
            includeEmpty
            emptyLabel={required ? "— Select sub-ledger —" : "— Optional —"}
            size="sm"
          />
          <div className="mt-1 flex items-center gap-1 text-[10px] text-muted-foreground min-w-0">
            <Sparkles className="h-3 w-3 text-primary shrink-0" />
            <span className="truncate">
              {required ? "Pick a sub-ledger under the document-type ledger to post" : reason}
            </span>
          </div>
        </div>
      );
    }

    // Parent ledger has no Sub-GLs — let the user pick any COA account for this line.
    return (
      <div className="space-y-1">
        <p className="text-[10px] text-muted-foreground truncate" title={parentLedger}>
          {parentLedger}
        </p>
        <Select
          value={subLedger || parentLedger}
          onValueChange={(value) => {
            setSubLedger(value);
            onSubLedgerChange(value);
          }}
          options={parentOptions}
          className="invoice-drawer-gl-select w-full"
          data-testid="invoice-gl-select"
          size="sm"
        />
        <div className="mt-1 flex items-center gap-1 text-[10px] text-muted-foreground min-w-0">
          <Sparkles className="h-3 w-3 text-primary shrink-0" />
          <span className="truncate">GL for this line</span>
        </div>
      </div>
    );
  }

  if (!parentLedger.trim()) {
    return (
      <span className="text-xs text-muted-foreground">Configure document type Post to ledger</span>
    );
  }

  if (!hasCatalog) {
    return (
      <div className="space-y-1">
        <span className="text-xs text-foreground">{displayLedger}</span>
        {line.gl_mapping_reason ? (
          <div className="flex items-center gap-1 text-[10px] text-muted-foreground min-w-0">
            <Sparkles className="h-3 w-3 text-primary shrink-0" />
            <span className="truncate">{reason}</span>
          </div>
        ) : null}
      </div>
    );
  }

  return (
    <div className={cn(required && "rounded-md ring-1 ring-destructive/40 p-1")}>
      <p className="text-[10px] text-muted-foreground mb-1 truncate" title={parentLedger}>
        {parentLedger}
      </p>
      <span
        className={cn(
          "text-xs block",
          required ? "text-destructive font-medium" : "text-foreground"
        )}
      >
        {subLedger || (required ? "— Required —" : "— Optional —")}
      </span>
      <div className="mt-1 flex items-center gap-1 text-[10px] text-muted-foreground min-w-0">
        <Sparkles className="h-3 w-3 text-primary shrink-0" />
        <span className="truncate">
          {required ? "Pick a sub-ledger under the document-type ledger to post" : reason}
        </span>
      </div>
    </div>
  );
}
