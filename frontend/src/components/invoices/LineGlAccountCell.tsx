import type { ReactNode } from "react";
import { Sparkles } from "lucide-react";

import type { LineItem } from "@/api/types";
import { SubLedgerField } from "@/components/rule-book/SubLedgerField";
import { Select } from "@/components/ui/select";
import { useChartOfAccounts } from "@/hooks/useChartOfAccounts";
import {
  coaAccountsToSelectOptions,
  ledgerHasSubLedgerCatalog,
  mergeCoaOptionsWithSavedValue,
  subLedgerExistsInCoa,
} from "@/lib/coaAccountOptions";
import { cn } from "@/lib/cn";
import {
  effectiveLineLedger,
  lineGlMappingReason,
  lineSubLedgerRequired,
  resolveLineGlSelection,
} from "@/lib/lineGlAccount";

export type LineGlChange = {
  parent_ledger: string;
  sub_ledger: string;
};

type LineGlAccountCellProps = {
  line: LineItem;
  parentLedger: string;
  postingApplies: boolean;
  onGlChange?: (next: LineGlChange) => void;
  editable?: boolean;
  asDrawerFields?: boolean;
  /** Two sibling cells for a line-item grid row: Main GL | Sub GL. */
  asRowColumns?: boolean;
};

function GlDrawerField({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="invoice-drawer-field invoice-drawer-field--readonly">
      <div className="invoice-drawer-field__label font-normal">{label}</div>
      <div className="invoice-drawer-field__control min-w-0">{children}</div>
    </div>
  );
}

function GlValue({
  children,
  empty,
  danger,
}: {
  children: ReactNode;
  empty?: boolean;
  danger?: boolean;
}) {
  return (
    <div
      className={cn(
        "invoice-drawer-field__value tnum font-normal",
        empty && "invoice-drawer-field__value--empty",
        danger && "text-destructive"
      )}
    >
      {children}
    </div>
  );
}

export function LineGlAccountCell({
  line,
  parentLedger,
  postingApplies,
  onGlChange,
  editable = false,
  asDrawerFields = false,
  asRowColumns = false,
}: LineGlAccountCellProps) {
  const { data: accounts = [] } = useChartOfAccounts();
  const { mainLedger, subLedger } = resolveLineGlSelection(line, parentLedger, accounts);
  const hasCatalog = ledgerHasSubLedgerCatalog(mainLedger || parentLedger, accounts);
  const required = lineSubLedgerRequired(
    { sub_ledger: subLedger },
    mainLedger || parentLedger,
    accounts
  );

  const mainOptions = mergeCoaOptionsWithSavedValue(
    coaAccountsToSelectOptions(accounts, {
      includeEmpty: true,
      emptyLabel: "— Select main GL —",
    }),
    mainLedger
  );

  const reason = lineGlMappingReason(line, parentLedger, hasCatalog);
  const displayLedger = effectiveLineLedger(line, parentLedger);
  const hasSubForCurrentMain = ledgerHasSubLedgerCatalog(mainLedger, accounts);
  const subInMainCatalog = subLedgerExistsInCoa(mainLedger, subLedger, accounts);
  const renderedSubLedger = hasSubForCurrentMain ? (subInMainCatalog ? subLedger : "") : "";

  const mainSelect =
    editable && onGlChange ? (
      <Select
        value={mainLedger}
        onValueChange={(value) => {
          onGlChange({
            parent_ledger: value,
            sub_ledger: "",
          });
        }}
        options={mainOptions}
        className="invoice-drawer-gl-select w-full"
        data-testid="invoice-main-gl-select"
        size="sm"
      />
    ) : null;

  const subSelect =
    editable && onGlChange ? (
      hasSubForCurrentMain ? (
        <SubLedgerField
          ledger={mainLedger}
          value={renderedSubLedger}
          onChange={(value) => {
            onGlChange({
              parent_ledger: mainLedger,
              sub_ledger: value,
            });
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
          value=""
          onValueChange={() => undefined}
          options={[{ value: "", label: mainLedger ? "No sub-GL catalogue" : "Select main GL first" }]}
          className="invoice-drawer-gl-select w-full"
          data-testid="invoice-sub-gl-select"
          size="sm"
          disabled
        />
      )
    ) : null;

  if (asRowColumns) {
    const mainText = (mainLedger || parentLedger || displayLedger || "").trim();
    const subText = subLedger.trim();
    const mainBody =
      !postingApplies ? (
        <span className="text-xs text-muted-foreground">—</span>
      ) : editable && onGlChange ? (
        mainSelect
      ) : (
        <span
          className={cn("text-xs block truncate text-left", !mainText && "text-muted-foreground")}
          title={mainText || undefined}
        >
          {mainText || "—"}
        </span>
      );
    const subBody =
      !postingApplies ? (
        <span className="text-xs text-muted-foreground">Not posted</span>
      ) : editable && onGlChange ? (
        subSelect
      ) : (
        <span
          className={cn(
            "text-xs block truncate text-left",
            !subText && "text-muted-foreground",
            required && !subText && "text-destructive"
          )}
          title={(subText || (required ? "— Required —" : "—")) || undefined}
        >
          {subText || (required ? "— Required —" : "—")}
        </span>
      );
    return (
      <>
        <div className="px-2 py-2 min-w-0 text-left" title={mainText || undefined}>{mainBody}</div>
        <div className="px-2 py-2 min-w-0 text-left" title={subText || undefined}>{subBody}</div>
      </>
    );
  }

  if (asDrawerFields) {
    if (!postingApplies) {
      return (
        <>
          <GlDrawerField label="Main GL">
            <GlValue empty>—</GlValue>
          </GlDrawerField>
          <GlDrawerField label="Sub GL">
            <GlValue empty>Not posted</GlValue>
          </GlDrawerField>
        </>
      );
    }
    if (editable && onGlChange) {
      return (
        <>
          <GlDrawerField label="Main GL">{mainSelect}</GlDrawerField>
          <GlDrawerField label="Sub GL">{subSelect}</GlDrawerField>
        </>
      );
    }
    const mainText = (mainLedger || parentLedger || displayLedger || "").trim();
    const subText = subLedger.trim();
    return (
      <>
        <GlDrawerField label="Main GL">
          <GlValue empty={!mainText}>{mainText || "—"}</GlValue>
        </GlDrawerField>
        <GlDrawerField label="Sub GL">
          <GlValue empty={!subText} danger={required && !subText}>
            {subText || (required ? "— Required —" : "—")}
          </GlValue>
        </GlDrawerField>
      </>
    );
  }

  if (!postingApplies) {
    return (
      <span className="text-xs text-muted-foreground">Not posted — reference document</span>
    );
  }

  if (editable && onGlChange) {
    return (
      <div className={cn(required && hasSubForCurrentMain && "rounded-md ring-1 ring-destructive/40 p-1")}>
        <p className="text-[10px] text-muted-foreground mb-1">Main GL</p>
        {mainSelect}
        <p className="mt-2 text-[10px] text-muted-foreground mb-1">Sub GL</p>
        {subSelect}
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

  if (!parentLedger.trim() && !mainLedger.trim()) {
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
      <p className="text-[10px] text-muted-foreground mb-1 truncate" title={mainLedger || parentLedger}>
        {mainLedger || parentLedger}
      </p>
      <span className={cn("text-xs block font-normal", required ? "text-destructive" : "text-foreground")}>
        {subLedger || (required ? "— Required —" : "— Optional —")}
      </span>
      <div className="mt-1 flex items-center gap-1 text-[10px] text-muted-foreground min-w-0">
        <Sparkles className="h-3 w-3 text-primary shrink-0" />
        <span className="truncate">
          {required ? "Pick a sub-ledger under the selected main GL to post" : reason}
        </span>
      </div>
    </div>
  );
}
