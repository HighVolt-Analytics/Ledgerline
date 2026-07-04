import { useEffect, useState } from "react";
import { Loader2, Plus, Trash2 } from "lucide-react";

import type { ChartOfAccountRow } from "@/api/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { useToast } from "@/context/ToastContext";
import {
  CHART_OF_ACCOUNT_TYPES,
  coaTypeMisclassificationWarnings,
  inferChartOfAccountTypeFromName,
  newChartOfAccountRow,
  normalizeChartOfAccountType,
  useChartOfAccounts,
  useSaveChartOfAccounts,
} from "@/hooks/useChartOfAccounts";
import { cn } from "@/lib/cn";

type ChartOfAccountsPanelProps = {
  canEdit?: boolean;
  onSaved?: () => void;
};

function validateAccounts(accounts: ChartOfAccountRow[]): string | null {
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
  }
  return null;
}

export function ChartOfAccountsPanel({ canEdit = false, onSaved }: ChartOfAccountsPanelProps) {
  const { toast } = useToast();
  const { data, isLoading, isError } = useChartOfAccounts();
  const saveMutation = useSaveChartOfAccounts();
  const [rows, setRows] = useState<ChartOfAccountRow[]>([]);
  const [dirty, setDirty] = useState(false);

  useEffect(() => {
    if (data) {
      setRows(
        data.map((row) => ({
          ...row,
          type: normalizeChartOfAccountType(row.type),
        }))
      );
      setDirty(false);
    }
  }, [data]);

  const updateRow = (index: number, patch: Partial<ChartOfAccountRow>) => {
    setRows((prev) => prev.map((row, i) => (i === index ? { ...row, ...patch } : row)));
    setDirty(true);
  };

  const addRow = () => {
    setRows((prev) => [...prev, newChartOfAccountRow()]);
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
        rows.map((row) => ({
          code: row.code.trim(),
          name: row.name.trim(),
          type: row.type,
        }))
      );
      setDirty(false);
      onSaved?.();
      toast({ title: "Chart of accounts saved" });
    } catch (err) {
      const message = err instanceof Error ? err.message : "Could not save chart of accounts";
      toast({ title: message, variant: "destructive" });
    }
  };

  if (isLoading) {
    return (
      <Card className="flex max-w-3xl items-center gap-2 p-6 text-sm text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" />
        Loading chart of accounts…
      </Card>
    );
  }

  if (isError) {
    return (
      <Card className="max-w-3xl p-6 text-sm text-destructive">
        Could not load chart of accounts for this organisation.
      </Card>
    );
  }

  return (
    <div className="max-w-3xl space-y-4" data-testid="chart-of-accounts-panel">
      <p className="text-sm text-muted-foreground">
        GL accounts for this organisation. Classification rules and posting defaults reference
        account names from this list.
      </p>

      <Card className="overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border text-left text-xs text-muted-foreground">
              <th className="px-4 py-2 font-medium">Code</th>
              <th className="px-3 py-2 font-medium">Account</th>
              <th className="px-3 py-2 font-medium">Type</th>
              {canEdit ? <th className="px-3 py-2 w-10" /> : null}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, index) => (
              <tr
                key={`${row.code}-${index}`}
                className="row-band border-b border-border/60 last:border-0"
              >
                <td className="px-4 py-2">
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
                  {canEdit ? (
                    <Input
                      value={row.name}
                      onChange={(e) => updateRow(index, { name: e.target.value })}
                      onBlur={(e) => {
                        const name = e.target.value.trim();
                        if (!name) return;
                        updateRow(index, { type: inferChartOfAccountTypeFromName(name) });
                      }}
                      className="h-8 text-xs"
                      data-testid={`coa-name-${index}`}
                    />
                  ) : (
                    row.name
                  )}
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
            ))}
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
