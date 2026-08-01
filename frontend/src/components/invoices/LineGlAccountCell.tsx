import { useEffect, useMemo, useState } from "react";
import { Sparkles } from "lucide-react";

import type { LineItem } from "@/api/types";
import { SubLedgerField } from "@/components/rule-book/SubLedgerField";
import { useChartOfAccounts } from "@/hooks/useChartOfAccounts";
import { ledgerHasSubLedgerCatalog } from "@/lib/coaAccountOptions";
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

  if (!postingApplies) {
    return (
      <span className="text-xs text-muted-foreground">Not posted — reference document</span>
    );
  }

  if (!parentLedger.trim()) {
    return (
      <span className="text-xs text-muted-foreground">Configure document type Post to ledger</span>
    );
  }

  const reason = lineGlMappingReason(line, parentLedger, hasCatalog);
  const displayLedger = effectiveLineLedger(line, parentLedger);

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
      {editable && onSubLedgerChange ? (
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
        />
      ) : (
        <span
          className={cn(
            "text-xs block",
            required ? "text-destructive font-medium" : "text-foreground"
          )}
        >
          {subLedger || (required ? "— Required —" : "— Optional —")}
        </span>
      )}
      <div className="mt-1 flex items-center gap-1 text-[10px] text-muted-foreground min-w-0">
        <Sparkles className="h-3 w-3 text-primary shrink-0" />
        <span className="truncate">
          {required ? "Pick a sub-ledger under the document-type ledger to post" : reason}
        </span>
      </div>
    </div>
  );
}
