import { Fragment, useEffect, useState } from "react";
import { ChevronDown, ChevronRight, Loader2, Plus, Trash2 } from "lucide-react";

import type { ChartOfAccountRow, SubLedgerRow } from "@/api/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { InlineTableSkeleton } from "@/components/skeleton/PageSkeletons";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { useToast } from "@/context/ToastContext";
import {
  CHART_OF_ACCOUNT_TYPES,
  chartOfAccountRowToPayload,
  coaTypeMisclassificationWarnings,
  inferChartOfAccountTypeFromName,
  newChartOfAccountRow,
  normalizeChartOfAccountType,
  useChartOfAccounts,
  useSaveChartOfAccounts,
} from "@/hooks/useChartOfAccounts";
import { cn } from "@/lib/cn";
import { newClientRowKey } from "@/lib/clientRowKey";

type SubLedgerRowLocal = SubLedgerRow & { _rowKey: string };
type ChartOfAccountRowLocal = Omit<ChartOfAccountRow, "subLedgers"> & {
  _rowKey: string;
  subLedgers: SubLedgerRowLocal[];
};

type ChartOfAccountsPanelProps = {
  canEdit?: boolean;
  onSaved?: () => void;
};

function newSubLedgerRowLocal(): SubLedgerRowLocal {
  return { code: "", name: "", _rowKey: newClientRowKey("sub-coa") };
}

function validateAccounts(accounts: ChartOfAccountRowLocal[]): string | null {
  if (!accounts.length) return "Add at least one account";
  const codes = new Set<string>();
  const names = new Set<string>();
  for (const row of accounts) {
    const code = row.code.trim();
    const name = row.name.trim();
    if (!code) return "Every account needs a code";
    if (!name) return "Every account needs a name";
    const codeKey = code.toUpperCase();
    if (codes.has(codeKey)) return `Duplicate account code: ${code}`;
    codes.add(codeKey);
    const nameKey = name.toLowerCase();
    if (names.has(nameKey)) return `Duplicate account name: ${name}`;
    names.add(nameKey);

    const subCodes = new Set<string>();
    const subNames = new Set<string>();
    for (const sub of row.subLedgers ?? []) {
      const subCode = sub.code.trim();
      const subName = sub.name.trim();
      if (!subCode && !subName) continue;
      if (!subCode) return `Sub-ledger under ${name} needs a code`;
      if (!subName) return `Sub-ledger under ${name} needs a name`;
      const subCodeKey = subCode.toUpperCase();
      if (subCodes.has(subCodeKey)) {
        return `Duplicate sub-ledger code ${subCode} under ${name}`;
      }
      subCodes.add(subCodeKey);
      const subNameKey = subName.toLowerCase();
      if (subNames.has(subNameKey)) {
        return `Duplicate sub-ledger name ${subName} under ${name}`;
      }
      subNames.add(subNameKey);
    }
  }
  return null;
}

function toLocalRow(row: ChartOfAccountRow): ChartOfAccountRowLocal {
  return {
    ...row,
    type: normalizeChartOfAccountType(row.type),
    subLedgers: (row.subLedgers ?? []).map((sub) => ({
      ...sub,
      _rowKey: newClientRowKey("sub-coa"),
    })),
    _rowKey: newClientRowKey("coa"),
  };
}

export function ChartOfAccountsPanel({ canEdit = false, onSaved }: ChartOfAccountsPanelProps) {
  const { toast } = useToast();
  const { data, isLoading, isError, blocked } = useChartOfAccounts();
  const saveMutation = useSaveChartOfAccounts();
  const [rows, setRows] = useState<ChartOfAccountRowLocal[]>([]);
  const [dirty, setDirty] = useState(false);
  const [expandedKeys, setExpandedKeys] = useState<Set<string>>(new Set());

  useEffect(() => {
    if (data) {
      setRows(data.map(toLocalRow));
      setDirty(false);
    }
  }, [data]);

  const toggleExpanded = (rowKey: string) => {
    setExpandedKeys((prev) => {
      const next = new Set(prev);
      if (next.has(rowKey)) next.delete(rowKey);
      else next.add(rowKey);
      return next;
    });
  };

  const updateRow = (index: number, patch: Partial<ChartOfAccountRowLocal>) => {
    setRows((prev) => prev.map((row, i) => (i === index ? { ...row, ...patch } : row)));
    setDirty(true);
  };

  const updateSubLedger = (
    accountIndex: number,
    subIndex: number,
    patch: Partial<SubLedgerRowLocal>
  ) => {
    setRows((prev) =>
      prev.map((row, i): ChartOfAccountRowLocal => {
        if (i !== accountIndex) return row;
        const subLedgers: SubLedgerRowLocal[] = row.subLedgers.map((sub, j) =>
          j === subIndex ? { ...sub, ...patch } : sub
        );
        return { ...row, subLedgers };
      })
    );
    setDirty(true);
  };

  const addSubLedger = (accountIndex: number) => {
    setRows((prev) =>
      prev.map((row, i): ChartOfAccountRowLocal =>
        i === accountIndex
          ? { ...row, subLedgers: [...row.subLedgers, newSubLedgerRowLocal()] }
          : row
      )
    );
    setDirty(true);
    const rowKey = rows[accountIndex]?._rowKey;
    if (rowKey) {
      setExpandedKeys((prev) => new Set(prev).add(rowKey));
    }
  };

  const removeSubLedger = (accountIndex: number, subIndex: number) => {
    setRows((prev) =>
      prev.map((row, i): ChartOfAccountRowLocal =>
        i === accountIndex
          ? { ...row, subLedgers: row.subLedgers.filter((_, j) => j !== subIndex) }
          : row
      )
    );
    setDirty(true);
  };

  const addRow = () => {
    setRows((prev) => [...prev, toLocalRow(newChartOfAccountRow())]);
    setDirty(true);
  };

  const removeRow = (index: number) => {
    setRows((prev) => prev.filter((_, i) => i !== index));
    setDirty(true);
  };

  const save = async () => {
    const error = validateAccounts(rows);
    if (error) {
      toast({ title: error, variant: "destructive" });
      return;
    }
    const typeWarnings = coaTypeMisclassificationWarnings(rows);
    if (typeWarnings.length) {
      toast({
        title: "Chart of accounts type hints",
        description: typeWarnings.slice(0, 2).join(" "),
      });
    }
    try {
      await saveMutation.mutateAsync(
        rows.map((row) => {
          const payload = chartOfAccountRowToPayload(row);
          const subLedgers = (row.subLedgers ?? [])
            .map((sub) => ({ code: sub.code.trim(), name: sub.name.trim() }))
            .filter((sub) => sub.code && sub.name);
          return {
            code: payload.code,
            name: payload.name,
            type: payload.type,
            subLedgers,
            sub_ledgers: subLedgers,
          };
        })
      );
      setDirty(false);
      onSaved?.();
      toast({ title: "Chart of accounts saved" });
    } catch (err) {
      const message = err instanceof Error ? err.message : "Could not save chart of accounts";
      toast({ title: message, variant: "destructive" });
    }
  };

  if (isLoading || blocked) {
    return (
      <Card className="w-full overflow-hidden" data-testid="chart-of-accounts-panel">
        <InlineTableSkeleton rows={8} columns={4} />
      </Card>
    );
  }

  if (isError) {
    return (
      <Card className="w-full p-6 text-sm text-destructive">
        Could not load chart of accounts for this organisation.
      </Card>
    );
  }

  return (
    <div className="w-full space-y-4" data-testid="chart-of-accounts-panel">
      <p className="text-sm text-muted-foreground">
        GL accounts for this organisation. Optionally define sub-ledgers under each account for
        cost centres or analytical segments. Classification rules reference account names from
        this list.
      </p>

      <Card className="overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border text-left text-xs text-muted-foreground">
              <th className="px-2 py-2 w-8" />
              <th className="px-2 py-2 font-medium">Code</th>
              <th className="px-3 py-2 font-medium">GL Account</th>
              <th className="px-3 py-2 font-medium">Type</th>
              {canEdit ? <th className="px-3 py-2 w-10" /> : null}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, index) => {
              const subCount = row.subLedgers.filter(
                (sub) => sub.code.trim() || sub.name.trim()
              ).length;
              const expanded = expandedKeys.has(row._rowKey);
              return (
                <Fragment key={row._rowKey}>
                  <tr className="row-band border-b border-border/60">
                    <td className="px-2 py-2">
                      <Button
                        type="button"
                        variant="ghost"
                        size="icon"
                        className="h-7 w-7 text-muted-foreground"
                        onClick={() => toggleExpanded(row._rowKey)}
                        aria-label={expanded ? "Collapse sub-ledgers" : "Expand sub-ledgers"}
                        data-testid={`coa-expand-${index}`}
                      >
                        {expanded ? (
                          <ChevronDown className="h-4 w-4" />
                        ) : (
                          <ChevronRight className="h-4 w-4" />
                        )}
                      </Button>
                    </td>
                    <td className="px-2 py-2">
                      {canEdit ? (
                        <Input
                          value={row.code}
                          onChange={(e) => updateRow(index, { code: e.target.value })}
                          className="h-8 font-mono text-xs"
                          data-testid={`coa-code-${index}`}
                        />
                      ) : (
                        <span className="tnum text-muted-foreground">{row.code}</span>
                      )}
                    </td>
                    <td className="px-3 py-2">
                      <div className="flex items-center gap-2">
                        {canEdit ? (
                          <Input
                            value={row.name}
                            onChange={(e) => updateRow(index, { name: e.target.value })}
                            onBlur={(e) => {
                              const name = e.target.value.trim();
                              if (!name) return;
                              updateRow(index, { type: inferChartOfAccountTypeFromName(name) });
                            }}
                            className="h-8 text-xs flex-1"
                            data-testid={`coa-name-${index}`}
                          />
                        ) : (
                          <span>{row.name}</span>
                        )}
                        {subCount > 0 ? (
                          <Badge variant="secondary" className="text-[10px] shrink-0">
                            {subCount} sub-ledger{subCount === 1 ? "" : "s"}
                          </Badge>
                        ) : null}
                      </div>
                    </td>
                    <td className="px-3 py-2">
                      {canEdit ? (
                        <Select
                          value={row.type}
                          onValueChange={(type) =>
                            updateRow(index, {
                              type: normalizeChartOfAccountType(type),
                            })
                          }
                          options={CHART_OF_ACCOUNT_TYPES.map((type) => ({
                            value: type,
                            label: type,
                          }))}
                          className="w-full min-w-[7rem]"
                          data-testid={`coa-type-${index}`}
                        />
                      ) : (
                        <Badge variant="outline" className="text-[10px]">
                          {row.type}
                        </Badge>
                      )}
                    </td>
                    {canEdit ? (
                      <td className="px-3 py-2 text-right">
                        <Button
                          type="button"
                          variant="ghost"
                          size="icon"
                          className="h-8 w-8 text-muted-foreground hover:text-destructive"
                          onClick={() => removeRow(index)}
                          disabled={rows.length <= 1}
                          aria-label="Remove account"
                        >
                          <Trash2 className="h-4 w-4" />
                        </Button>
                      </td>
                    ) : null}
                  </tr>
                  {expanded ? (
                    <tr key={`${row._rowKey}-subs`} className="border-b border-border/60 bg-muted/20">
                      <td colSpan={canEdit ? 5 : 4} className="px-4 py-3">
                        <div className="space-y-2 pl-6">
                          <p className="text-[11px] font-medium text-muted-foreground">
                            Sub-ledgers for {row.name.trim() || "this account"}
                          </p>
                          {row.subLedgers.length === 0 ? (
                            <p className="text-[11px] text-muted-foreground">
                              No sub-ledgers defined.
                            </p>
                          ) : (
                            <div className="space-y-1">
                              {row.subLedgers.map((sub: SubLedgerRowLocal, subIndex) => (
                                <div
                                  key={sub._rowKey}
                                  className="flex flex-wrap items-center gap-2"
                                >
                                  {canEdit ? (
                                    <>
                                      <Input
                                        value={sub.code}
                                        onChange={(e) =>
                                          updateSubLedger(index, subIndex, { code: e.target.value })
                                        }
                                        className="h-7 w-24 font-mono text-xs"
                                        placeholder="Code"
                                        data-testid={`coa-sub-code-${index}-${subIndex}`}
                                      />
                                      <Input
                                        value={sub.name}
                                        onChange={(e) =>
                                          updateSubLedger(index, subIndex, { name: e.target.value })
                                        }
                                        className="h-7 flex-1 min-w-[10rem] text-xs"
                                        placeholder="Sub-ledger name"
                                        data-testid={`coa-sub-name-${index}-${subIndex}`}
                                      />
                                      <Button
                                        type="button"
                                        variant="ghost"
                                        size="icon"
                                        className="h-7 w-7 text-muted-foreground hover:text-destructive"
                                        onClick={() => removeSubLedger(index, subIndex)}
                                        aria-label="Remove sub-ledger"
                                      >
                                        <Trash2 className="h-3.5 w-3.5" />
                                      </Button>
                                    </>
                                  ) : (
                                    <span className="text-xs text-muted-foreground">
                                      <span className="tnum font-mono">{sub.code}</span>
                                      {" · "}
                                      {sub.name}
                                    </span>
                                  )}
                                </div>
                              ))}
                            </div>
                          )}
                          {canEdit ? (
                            <Button
                              type="button"
                              variant="outline"
                              size="sm"
                              className="h-7 text-xs"
                              onClick={() => addSubLedger(index)}
                              data-testid={`coa-add-sub-${index}`}
                            >
                              <Plus className="mr-1 h-3 w-3" />
                              Add sub-ledger
                            </Button>
                          ) : null}
                        </div>
                      </td>
                    </tr>
                  ) : null}
                </Fragment>
              );
            })}
          </tbody>
        </table>
      </Card>

      {canEdit ? (
        <div className="flex flex-wrap items-center gap-2">
          <Button type="button" variant="outline" size="sm" onClick={addRow}>
            <Plus className="mr-1 h-4 w-4" />
            Add account
          </Button>
          <Button
            type="button"
            size="sm"
            onClick={() => void save()}
            disabled={!dirty || saveMutation.isPending}
            className={cn(saveMutation.isPending && "opacity-70")}
            data-testid="coa-save"
          >
            {saveMutation.isPending ? (
              <>
                <Loader2 className="mr-1 h-4 w-4 animate-spin" />
                Saving…
              </>
            ) : (
              "Save chart of accounts"
            )}
          </Button>
        </div>
      ) : (
        <p className="text-sm text-muted-foreground">Only admins can edit the chart of accounts.</p>
      )}
    </div>
  );
}
