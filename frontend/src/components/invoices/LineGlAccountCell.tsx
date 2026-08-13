import { useEffect, useMemo, useState } from "react";
import { Sparkles } from "lucide-react";

import type { LineItem } from "@/api/types";
import { SubLedgerField } from "@/components/rule-book/SubLedgerField";
import { Select } from "@/components/ui/select";
import { useChartOfAccounts } from "@/hooks/useChartOfAccounts";
import {
  coaAccountsToSelectOptions,
  ledgerExistsInCoa,
  ledgerHasSubLedgerCatalog,
  mergeCoaOptionsWithSavedValue,
  subLedgerExistsInCoa,
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
  const fallbackMainLedger = line.parent_ledger?.trim() || parentLedger.trim();
  const initialSubLedger = line.sub_ledger?.trim() ?? "";
  const inferredMainFromSaved =
    initialSubLedger && ledgerExistsInCoa(initialSubLedger, accounts) ? initialSubLedger : "";
  const [mainLedger, setMainLedger] = useState(fallbackMainLedger || inferredMainFromSaved);
  const hasCatalog = ledgerHasSubLedgerCatalog(mainLedger, accounts);
  const required = lineSubLedgerRequired(line, mainLedger || parentLedger, accounts);
  const suggested = useMemo(
    () => suggestLineSubLedger(line, accounts, mainLedger || parentLedger),
    [accounts, line, mainLedger, parentLedger]
  );
  const [subLedger, setSubLedger] = useState(initialSubLedger || suggested);

  useEffect(() => {
    const parent = line.parent_ledger?.trim() || parentLedger.trim();
    const saved = line.sub_ledger?.trim() ?? "";
    const savedIsMainLedger = saved ? ledgerExistsInCoa(saved, accounts) : false;
    const nextMain = parent || (savedIsMainLedger ? saved : "");
    const nextHasCatalog = ledgerHasSubLedgerCatalog(nextMain, accounts);
    const nextSub = nextHasCatalog && savedIsMainLedger ? "" : saved || suggested;
    setMainLedger(nextMain);
    setSubLedger(nextSub);
  }, [accounts, line.parent_ledger, line.sub_ledger, line.id, parentLedger, suggested]);

  const mainOptions = useMemo(
    () =>
      coaAccountsToSelectOptions(accounts, {
        includeEmpty: true,
        emptyLabel: "— Select main GL —",
      }),
    [accounts]
  );

  const subLedgerOptions = useMemo(
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

  // Editable: first pick main GL, then optional/required sub-GL under that main.
  if (editable && onSubLedgerChange) {
    const hasSubForCurrentMain = ledgerHasSubLedgerCatalog(mainLedger, accounts);
    const subInMainCatalog = subLedgerExistsInCoa(mainLedger, subLedger, accounts);
    const renderedSubLedger = hasSubForCurrentMain ? (subInMainCatalog ? subLedger : "") : subLedger;
    const mainOrSubValue = hasSubForCurrentMain ? renderedSubLedger : mainLedger;
    return (
      <div className={cn(required && hasSubForCurrentMain && "rounded-md ring-1 ring-destructive/40 p-1")}>
        <p className="text-[10px] text-muted-foreground mb-1">Main GL</p>
        <Select
          value={mainLedger}
          onValueChange={(value) => {
            setMainLedger(value);
            if (!value) {
              setSubLedger("");
              onSubLedgerChange("");
              return;
            }
            if (ledgerHasSubLedgerCatalog(value, accounts)) {
              setSubLedger("");
              onSubLedgerChange("");
              return;
            }
            setSubLedger(value);
            onSubLedgerChange(value);
          }}
          options={mainOptions}
          className="invoice-drawer-gl-select w-full"
          data-testid="invoice-main-gl-select"
          size="sm"
        />
        <p className="mt-2 text-[10px] text-muted-foreground mb-1">Sub GL</p>
        {hasSubForCurrentMain ? (
          <SubLedgerField
            ledger={mainLedger}
            value={renderedSubLedger}
            onChange={(value) => {
              setSubLedger(value);
              onSubLedgerChange(value);
            }}
            accounts={accounts}
            className="invoice-drawer-gl-select w-full"
            data-testid="invoice-sub-gl-select"
            includeEmpty
            emptyLabel={required ? "— Select sub-GL —" : "— Optional —"}
            size="sm"
          />
        ) : (
          <Select
            value={mainOrSubValue}
            onValueChange={(value) => {
              setSubLedger(value);
              onSubLedgerChange(value);
            }}
            options={subLedgerOptions}
            className="invoice-drawer-gl-select w-full"
            data-testid="invoice-sub-gl-select"
            size="sm"
          />
        )}
        <div className="mt-1 flex items-center gap-1 text-[10px] text-muted-foreground min-w-0">
          <Sparkles className="h-3 w-3 text-primary shrink-0" />
          <span className="truncate">
            {hasSubForCurrentMain
              ? "Pick a sub-GL under the selected main GL"
              : "Selected main GL has no sub-GL catalogue"}
          </span>
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
