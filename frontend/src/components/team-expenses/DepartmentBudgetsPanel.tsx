import { Fragment, useEffect, useMemo, useState } from "react";
import { ChevronDown, ChevronRight, Plus, Trash2, Upload } from "lucide-react";
import { api } from "@/api/client";
import type { DepartmentBudgetRow } from "@/api/types";
import { EmptyState } from "@/components/EmptyState";
import { FieldLabel } from "@/components/rule-book/FieldLabel";
import { BudgetUtilBar } from "@/components/team-expenses/BudgetUtilBar";
import { GlBudgetImportDialog } from "@/components/team-expenses/GlBudgetImportDialog";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { NumericInput } from "@/components/ui/numeric-input";
import { Select, toSelectOptions } from "@/components/ui/select";
import { useToast } from "@/context/ToastContext";
import { useCoaAccountOptions } from "@/hooks/useCoaAccountOptions";
import {
  useDeleteParentGlBudgetTree,
  useDepartmentBudgets,
  useImportDepartmentBudgets,
  useUpsertParentGlBudgetTree,
} from "@/hooks/useDepartmentBudgets";
import { useTeamExpenseDepartmentBudgetUtilization } from "@/hooks/useTeamExpenseReports";
import { cn } from "@/lib/cn";
import {
  mergeCoaOptionsWithSavedValue,
  subLedgersForLedger,
} from "@/lib/coaAccountOptions";
import { money } from "@/lib/format";

const PERIOD_KINDS = ["monthly", "quarterly", "annual"] as const;

function currentPeriodKey(kind: (typeof PERIOD_KINDS)[number]): string {
  const now = new Date();
  const y = now.getFullYear();
  const m = now.getMonth() + 1;
  if (kind === "monthly") return `${y}-${String(m).padStart(2, "0")}`;
  if (kind === "quarterly") return `${y}-Q${Math.floor((m - 1) / 3) + 1}`;
  return `${y}`;
}

function roundMoney(n: number): number {
  return Math.round((n + Number.EPSILON) * 100) / 100;
}

type BudgetTreeGroup = {
  parentGl: string;
  periodKind: string;
  periodKey: string;
  parentRow: DepartmentBudgetRow | null;
  subRows: DepartmentBudgetRow[];
};

export function DepartmentBudgetsPanel({ currency }: { currency: string }) {
  const { toast } = useToast();
  const { data: rows = [], isLoading } = useDepartmentBudgets();
  const { data: utilization = [] } = useTeamExpenseDepartmentBudgetUtilization();
  const upsertMut = useUpsertParentGlBudgetTree();
  const deleteTreeMut = useDeleteParentGlBudgetTree();
  const importMut = useImportDepartmentBudgets();
  const {
    options: coaOptions,
    allAccounts,
    isLoading: coaLoading,
  } = useCoaAccountOptions({
    // Same catalogue as Team Expenses rules Parent GL (not Expense-only).
    // Budgets must be creatable for any wallet rules can post to.
    includeEmpty: true,
    emptyLabel: "— Select parent GL —",
  });

  const [parentGl, setParentGl] = useState("");
  const [periodKind, setPeriodKind] = useState<(typeof PERIOD_KINDS)[number]>("monthly");
  const [periodKey, setPeriodKey] = useState(currentPeriodKey("monthly"));
  const [parentBudget, setParentBudget] = useState<number | null>(0);
  const [subBudgets, setSubBudgets] = useState<Record<string, number | null>>({});
  const [notes, setNotes] = useState("");
  const [enforcement, setEnforcement] = useState<"soft" | "hard">("soft");
  const [error, setError] = useState<string | null>(null);
  const [importOpen, setImportOpen] = useState(false);
  /** When set, Save updates this tree (and migrates if parent/period changed). */
  const [editingTree, setEditingTree] = useState<{
    parentGl: string;
    periodKind: (typeof PERIOD_KINDS)[number];
    periodKey: string;
  } | null>(null);
  /** Keys of parent rows whose Sub-GLs are expanded in the table. */
  const [expandedKeys, setExpandedKeys] = useState<Set<string>>(() => new Set());

  const parentOptions = useMemo(
    () => mergeCoaOptionsWithSavedValue(coaOptions, parentGl),
    [coaOptions, parentGl]
  );

  const catalogSubs = useMemo(
    () => subLedgersForLedger(parentGl, allAccounts),
    [parentGl, allAccounts]
  );

  const catalogSubNames = useMemo(
    () => catalogSubs.map((s) => s.name).join("\0"),
    [catalogSubs]
  );

  useEffect(() => {
    if (!parentGl.trim()) {
      setSubBudgets({});
      return;
    }
    const names = catalogSubNames ? catalogSubNames.split("\0") : [];
    setSubBudgets((prev) => {
      const next: Record<string, number | null> = {};
      for (const name of names) {
        next[name] = prev[name] ?? 0;
      }
      return next;
    });
  }, [parentGl, catalogSubNames]);

  const subSum = useMemo(() => {
    return roundMoney(
      catalogSubs.reduce((acc, sub) => acc + (subBudgets[sub.name] ?? 0), 0)
    );
  }, [catalogSubs, subBudgets]);

  const parentAmt = parentBudget ?? 0;
  const remaining = roundMoney(parentAmt - subSum);
  const sumMatches =
    catalogSubs.length === 0 || Math.abs(remaining) < 0.005;

  const utilById = useMemo(() => {
    const map = new Map<number, (typeof utilization)[number]>();
    for (const row of utilization) map.set(row.budget_id, row);
    return map;
  }, [utilization]);

  const parentOfSub = useMemo(() => {
    const map = new Map<string, string>();
    for (const account of allAccounts) {
      for (const sub of account.subLedgers ?? []) {
        if (sub.name.trim()) map.set(sub.name.trim().toLowerCase(), account.name);
      }
    }
    return map;
  }, [allAccounts]);

  const treeGroups = useMemo(() => {
    const groups = new Map<string, BudgetTreeGroup>();
    const orphanSubs: DepartmentBudgetRow[] = [];

    for (const row of rows) {
      const gl = row.gl_ledger.trim();
      const parentName = parentOfSub.get(gl.toLowerCase());
      const isTopLevel = allAccounts.some(
        (a) => a.name.trim().toLowerCase() === gl.toLowerCase()
      );

      if (isTopLevel) {
        const key = `${gl}::${row.period_kind}::${row.period_key}`;
        const existing = groups.get(key);
        if (existing) existing.parentRow = row;
        else {
          groups.set(key, {
            parentGl: gl,
            periodKind: row.period_kind,
            periodKey: row.period_key,
            parentRow: row,
            subRows: [],
          });
        }
        continue;
      }

      if (parentName) {
        const key = `${parentName}::${row.period_kind}::${row.period_key}`;
        const existing = groups.get(key);
        if (existing) existing.subRows.push(row);
        else {
          groups.set(key, {
            parentGl: parentName,
            periodKind: row.period_kind,
            periodKey: row.period_key,
            parentRow: null,
            subRows: [row],
          });
        }
        continue;
      }

      orphanSubs.push(row);
    }

    for (const orphan of orphanSubs) {
      const key = `${orphan.gl_ledger}::${orphan.period_kind}::${orphan.period_key}`;
      if (!groups.has(key)) {
        groups.set(key, {
          parentGl: orphan.gl_ledger,
          periodKind: orphan.period_kind,
          periodKey: orphan.period_key,
          parentRow: orphan,
          subRows: [],
        });
      }
    }

    return [...groups.values()].sort((a, b) =>
      `${a.parentGl}${a.periodKey}`.localeCompare(`${b.parentGl}${b.periodKey}`)
    );
  }, [rows, allAccounts, parentOfSub]);

  // Default-expand parent rows that have Sub-GL budgets (once per key).
  useEffect(() => {
    setExpandedKeys((prev) => {
      let changed = false;
      const next = new Set(prev);
      for (const group of treeGroups) {
        if (group.subRows.length === 0) continue;
        const key = `${group.parentGl}::${group.periodKind}::${group.periodKey}`;
        if (!next.has(key)) {
          next.add(key);
          changed = true;
        }
      }
      return changed ? next : prev;
    });
  }, [treeGroups]);

  const toggleExpanded = (key: string) => {
    setExpandedKeys((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  const onPeriodKindChange = (kind: string) => {
    const k = (PERIOD_KINDS.includes(kind as (typeof PERIOD_KINDS)[number])
      ? kind
      : "monthly") as (typeof PERIOD_KINDS)[number];
    // Only auto-fill period key when the kind actually changes — re-selecting
    // the same kind (common while editing) must not jump to the current calendar period.
    if (k !== periodKind) {
      setPeriodKind(k);
      setPeriodKey(currentPeriodKey(k));
    }
  };

  const resetForm = () => {
    setNotes("");
    setEnforcement("soft");
    setParentBudget(0);
    setSubBudgets({});
    setParentGl("");
    setEditingTree(null);
    setError(null);
  };

  const loadTreeIntoForm = (group: BudgetTreeGroup) => {
    const kind = (
      PERIOD_KINDS.includes(group.periodKind as (typeof PERIOD_KINDS)[number])
        ? group.periodKind
        : "monthly"
    ) as (typeof PERIOD_KINDS)[number];
    setEditingTree({
      parentGl: group.parentGl,
      periodKind: kind,
      periodKey: group.periodKey,
    });
    setParentGl(group.parentGl);
    setPeriodKind(kind);
    setPeriodKey(group.periodKey);
    setParentBudget(group.parentRow ? Number(group.parentRow.allocated) : 0);
    const next: Record<string, number | null> = {};
    const catalog = subLedgersForLedger(group.parentGl, allAccounts);
    for (const sub of catalog) {
      const saved = group.subRows.find(
        (r) => r.gl_ledger.trim().toLowerCase() === sub.name.toLowerCase()
      );
      next[sub.name] = saved ? Number(saved.allocated) : 0;
    }
    setSubBudgets(next);
    setNotes(group.parentRow?.notes ?? "");
    setEnforcement(group.parentRow?.enforcement === "hard" ? "hard" : "soft");
    setError(null);
  };

  const onSave = async () => {
    setError(null);
    const parent = parentGl.trim();
    if (!parent) {
      setError("Parent GL is required");
      return;
    }
    if (catalogSubs.length > 0 && !sumMatches) {
      setError(
        `Sub-GL budgets must sum to parent budget (${money(parentAmt, currency)}). ` +
          `Current sum ${money(subSum, currency)}; remaining ${money(remaining, currency)}.`
      );
      return;
    }
    const nextKey = {
      parentGl: parent,
      periodKind,
      periodKey: periodKey.trim(),
    };
    const keyChanged =
      editingTree != null &&
      (editingTree.parentGl.trim().toLowerCase() !== nextKey.parentGl.toLowerCase() ||
        editingTree.periodKind !== nextKey.periodKind ||
        editingTree.periodKey !== nextKey.periodKey);

    try {
      // If parent/period identity changed while editing, remove the old tree first
      // so we don't leave a duplicate row behind.
      if (keyChanged && editingTree) {
        await deleteTreeMut.mutateAsync({
          parent_gl: editingTree.parentGl,
          period_kind: editingTree.periodKind,
          period_key: editingTree.periodKey,
        });
      }
      await upsertMut.mutateAsync({
        parent_gl: parent,
        period_kind: periodKind,
        period_key: periodKey.trim(),
        allocated: parentAmt,
        sub_allocations: catalogSubs.map((sub) => ({
          gl_ledger: sub.name,
          allocated: subBudgets[sub.name] ?? 0,
        })),
        enforcement,
        notes: notes.trim() || null,
      });
      resetForm();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save GL budget tree");
    }
  };

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h3 className="text-sm font-semibold">GL budgets</h3>
          <p className="text-xs text-muted-foreground mt-0.5">
            Choose a Parent GL to load all of its Sub-GLs. Set each Sub-GL budget so their sum
            equals the parent budget, then save once — or import many wallets from a spreadsheet.
          </p>
        </div>
        <Button
          type="button"
          size="sm"
          variant="outline"
          onClick={() => setImportOpen(true)}
          data-testid="button-import-gl-budgets"
        >
          <Upload className="h-3.5 w-3.5 mr-1" />
          Import spreadsheet
        </Button>
      </div>

      <GlBudgetImportDialog
        open={importOpen}
        busy={importMut.isPending}
        onClose={() => setImportOpen(false)}
        onDownloadTemplate={(opts) => api.downloadDepartmentBudgetImportTemplate(opts)}
        onPreview={(file) => importMut.mutateAsync({ file, dryRun: true })}
        onImport={async (file) => {
          const result = await importMut.mutateAsync({ file, dryRun: false });
          toast({
            title: "GL budgets imported",
            description: `${result.created} created, ${result.updated} updated`,
          });
          return result;
        }}
      />

      <Card className="p-3 space-y-3">
        <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
          <FieldLabel label="Parent GL">
            <Select
              value={parentGl}
              onValueChange={setParentGl}
              options={parentOptions}
              placeholder={coaLoading ? "Loading accounts…" : "— Select parent GL —"}
              className="h-8 text-xs"
              data-testid="te-gl-budget-account"
            />
          </FieldLabel>
          <FieldLabel label="Period kind">
            <Select
              value={periodKind}
              onValueChange={onPeriodKindChange}
              options={toSelectOptions([...PERIOD_KINDS])}
              className="h-8 text-xs"
            />
          </FieldLabel>
          <FieldLabel label="Period key">
            <Input
              value={periodKey}
              onChange={(e) => setPeriodKey(e.target.value)}
              placeholder="2026-08 / 2026-Q3 / 2026"
              className="h-8 text-xs"
            />
          </FieldLabel>
          <FieldLabel label="Parent budget (total)">
            <NumericInput
              value={parentBudget ?? undefined}
              onValueChange={(v) => setParentBudget(v ?? null)}
              className="h-8 text-xs"
              data-testid="te-gl-budget-parent-amount"
            />
          </FieldLabel>
          <FieldLabel label="Over budget">
            <Select
              value={enforcement}
              onValueChange={(v) => setEnforcement(v === "hard" ? "hard" : "soft")}
              options={[
                { value: "soft", label: "Soft — manager can approve" },
                { value: "hard", label: "Hard — raise budget first" },
              ]}
              className="h-8 text-xs"
              data-testid="te-gl-budget-enforcement"
            />
          </FieldLabel>
          <FieldLabel label="Notes">
            <Input
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              className="h-8 text-xs"
            />
          </FieldLabel>
        </div>

        {parentGl.trim() && catalogSubs.length === 0 ? (
          <p className="text-xs text-muted-foreground">
            This parent has no Sub-GLs in the chart of accounts — only the parent wallet will be
            saved.
          </p>
        ) : null}

        {catalogSubs.length > 0 ? (
          <div className="rounded-md border border-border/70 overflow-hidden">
            <div className="px-3 py-2 bg-muted/30 flex items-center justify-between gap-2">
              <p className="text-xs font-medium">Sub-GL allocations</p>
              <p
                className={cn(
                  "text-xs tnum",
                  sumMatches ? "text-muted-foreground" : "text-destructive font-medium"
                )}
              >
                Sum {money(subSum, currency)} / Parent {money(parentAmt, currency)}
                {!sumMatches ? ` · left ${money(remaining, currency)}` : " · balanced"}
              </p>
            </div>
            <table className="w-full text-xs">
              <thead>
                <tr className="text-muted-foreground text-left border-b border-border/60">
                  <th className="px-3 py-2 font-medium">Sub-GL</th>
                  <th className="px-3 py-2 font-medium text-right w-40">Budget</th>
                </tr>
              </thead>
              <tbody>
                {catalogSubs.map((sub) => (
                  <tr key={sub.name} className="border-b border-border/40 last:border-0">
                    <td className="px-3 py-2">
                      {sub.code ? `${sub.code} — ${sub.name}` : sub.name}
                    </td>
                    <td className="px-3 py-2">
                      <NumericInput
                        value={subBudgets[sub.name] ?? undefined}
                        onValueChange={(v) =>
                          setSubBudgets((prev) => ({ ...prev, [sub.name]: v ?? null }))
                        }
                        className="h-8 text-xs"
                        data-testid={`te-gl-budget-sub-${sub.name}`}
                      />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}

        {error ? <p className="text-xs text-destructive">{error}</p> : null}
        <div className="flex flex-wrap items-center gap-2">
          <Button
            type="button"
            size="sm"
            onClick={() => void onSave()}
            disabled={
              upsertMut.isPending ||
              deleteTreeMut.isPending ||
              (catalogSubs.length > 0 && !sumMatches)
            }
            data-testid="te-gl-budget-save"
          >
            <Plus className="h-3.5 w-3.5 mr-1" />
            {editingTree ? "Update parent + Sub-GL budgets" : "Save parent + Sub-GL budgets"}
          </Button>
          {editingTree ? (
            <Button
              type="button"
              size="sm"
              variant="ghost"
              onClick={resetForm}
              disabled={upsertMut.isPending || deleteTreeMut.isPending}
            >
              Cancel edit
            </Button>
          ) : null}
        </div>
      </Card>

      {isLoading ? (
        <p className="text-sm text-muted-foreground py-4 text-center">Loading…</p>
      ) : treeGroups.length === 0 ? (
        <EmptyState
          title="No GL budgets"
          hint="Select a parent GL, allocate every Sub-GL so the sum equals the parent total, then save."
        />
      ) : (
        <Card className="overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-xs text-muted-foreground border-b border-border text-left">
                  <th className="px-4 py-2.5 font-medium">GL account</th>
                  <th className="px-3 py-2.5 font-medium">Period</th>
                  <th className="px-3 py-2.5 font-medium text-right">Budget</th>
                  <th className="px-3 py-2.5 font-medium text-right">Spent so far</th>
                  <th className="px-3 py-2.5 font-medium text-right">Left</th>
                  <th className="px-3 py-2.5 font-medium w-36">Utilisation</th>
                  <th className="px-4 py-2.5 font-medium w-20" />
                </tr>
              </thead>
              <tbody>
                {treeGroups.map((group) => {
                  const key = `${group.parentGl}::${group.periodKind}::${group.periodKey}`;
                  const parent = group.parentRow;
                  const budgetAmt = parent ? Number(parent.allocated) : group.subRows.reduce(
                    (a, r) => a + Number(r.allocated),
                    0
                  );
                  const util = parent ? utilById.get(parent.id) : undefined;
                  const spent = util?.consumed ?? 0;
                  const left = util?.remaining != null ? util.remaining : budgetAmt - spent;
                  const over = left < 0;
                  const pct =
                    budgetAmt > 0 ? Math.min(999, Math.round((spent / budgetAmt) * 100)) : 0;
                  const hasSubs = group.subRows.length > 0;
                  const showSubs = hasSubs && expandedKeys.has(key);

                  return (
                    <Fragment key={key}>
                      <tr className="row-band border-b border-border/60">
                        <td className="px-4 py-2.5 font-medium">
                          {hasSubs ? (
                            <button
                              type="button"
                              className="inline-flex items-center gap-1 text-left hover:text-foreground"
                              onClick={() => toggleExpanded(key)}
                              aria-expanded={showSubs}
                              aria-label={
                                showSubs
                                  ? `Collapse ${group.parentGl} Sub-GLs`
                                  : `Expand ${group.parentGl} Sub-GLs`
                              }
                            >
                              {showSubs ? (
                                <ChevronDown className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
                              ) : (
                                <ChevronRight className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
                              )}
                              {group.parentGl}
                            </button>
                          ) : (
                            <span className="inline-flex items-center gap-1">
                              <span className="w-3.5" />
                              {group.parentGl}
                            </span>
                          )}
                        </td>
                        <td className="px-3 py-2.5 text-muted-foreground">
                          {group.periodKind} · {group.periodKey}
                        </td>
                        <td className="px-3 py-2.5 text-right tnum">
                          {money(budgetAmt, currency)}
                        </td>
                        <td className="px-3 py-2.5 text-right tnum">{money(spent, currency)}</td>
                        <td
                          className={cn(
                            "px-3 py-2.5 text-right tnum font-medium",
                            over && "text-destructive"
                          )}
                        >
                          {money(left, currency)}
                          {over ? " ❌" : ""}
                        </td>
                        <td className="px-3 py-2.5">
                          <div className="flex items-center gap-2">
                            <BudgetUtilBar used={spent} total={budgetAmt} />
                            <span className="tnum text-xs text-muted-foreground w-9 text-right">
                              {pct}%
                            </span>
                          </div>
                        </td>
                        <td className="px-4 py-2.5">
                          <div className="flex items-center gap-1 justify-end">
                            <Button
                              type="button"
                              variant="ghost"
                              size="sm"
                              className="h-7 px-2 text-xs"
                              onClick={() => loadTreeIntoForm(group)}
                            >
                              Edit
                            </Button>
                            <Button
                              type="button"
                              variant="ghost"
                              size="sm"
                              className="h-7 w-7 p-0 text-muted-foreground hover:text-destructive"
                              disabled={deleteTreeMut.isPending}
                              onClick={() =>
                                void deleteTreeMut.mutateAsync({
                                  parent_gl: group.parentGl,
                                  period_kind: group.periodKind as (typeof PERIOD_KINDS)[number],
                                  period_key: group.periodKey,
                                })
                              }
                              aria-label="Delete parent and Sub-GL budgets"
                            >
                              <Trash2 className="h-3.5 w-3.5" />
                            </Button>
                          </div>
                        </td>
                      </tr>
                      {showSubs
                        ? group.subRows.map((sub) => {
                            const subUtil = utilById.get(sub.id);
                            const subBudget = Number(sub.allocated);
                            const subSpent = subUtil?.consumed ?? 0;
                            const subLeft =
                              subUtil?.remaining != null
                                ? subUtil.remaining
                                : subBudget - subSpent;
                            const subOver = subLeft < 0;
                            return (
                              <tr
                                key={sub.id}
                                className="bg-muted/20 border-b border-border/60 text-xs"
                              >
                                <td className="px-4 py-2 pl-10 text-muted-foreground">
                                  ↳ {sub.gl_ledger}
                                </td>
                                <td className="px-3 py-2 text-muted-foreground">
                                  {sub.period_kind} · {sub.period_key}
                                </td>
                                <td className="px-3 py-2 text-right tnum">
                                  {money(subBudget, currency)}
                                </td>
                                <td className="px-3 py-2 text-right tnum">
                                  {money(subSpent, currency)}
                                </td>
                                <td
                                  className={cn(
                                    "px-3 py-2 text-right tnum font-medium",
                                    subOver && "text-destructive"
                                  )}
                                >
                                  {money(subLeft, currency)}
                                </td>
                                <td className="px-3 py-2">
                                  <div className="flex items-center gap-2">
                                    <BudgetUtilBar used={subSpent} total={subBudget} />
                                    <span className="tnum text-[10px] text-muted-foreground w-9 text-right">
                                      {subBudget > 0
                                        ? `${Math.min(999, Math.round((subSpent / subBudget) * 100))}%`
                                        : "0%"}
                                    </span>
                                  </div>
                                </td>
                                <td />
                              </tr>
                            );
                          })
                        : null}
                    </Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>
        </Card>
      )}
    </div>
  );
}
