import { useMemo, useState } from "react";
import { Plus, Trash2 } from "lucide-react";
import { EmptyState } from "@/components/EmptyState";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { NumericInput } from "@/components/ui/numeric-input";
import { Select, toSelectOptions } from "@/components/ui/select";
import {
  useCreateDepartmentBudget,
  useDeleteDepartmentBudget,
  useDepartmentBudgets,
} from "@/hooks/useDepartmentBudgets";
import { money } from "@/lib/format";
import { FieldLabel } from "@/components/rule-book/FieldLabel";

const PERIOD_KINDS = ["monthly", "quarterly", "annual"] as const;

function currentPeriodKey(kind: (typeof PERIOD_KINDS)[number]): string {
  const now = new Date();
  const y = now.getFullYear();
  const m = now.getMonth() + 1;
  if (kind === "monthly") return `${y}-${String(m).padStart(2, "0")}`;
  if (kind === "quarterly") return `${y}-Q${Math.floor((m - 1) / 3) + 1}`;
  return `${y}`;
}

export function DepartmentBudgetsPanel({
  currency,
  departments,
}: {
  currency: string;
  departments: string[];
}) {
  const { data: rows = [], isLoading } = useDepartmentBudgets();
  const createMut = useCreateDepartmentBudget();
  const deleteMut = useDeleteDepartmentBudget();

  const [department, setDepartment] = useState("");
  const [glLedger, setGlLedger] = useState("");
  const [periodKind, setPeriodKind] = useState<(typeof PERIOD_KINDS)[number]>("monthly");
  const [periodKey, setPeriodKey] = useState(currentPeriodKey("monthly"));
  const [allocated, setAllocated] = useState<number | null>(0);
  const [notes, setNotes] = useState("");
  const [error, setError] = useState<string | null>(null);

  const deptOptions = useMemo(() => {
    const set = new Set(departments.filter(Boolean).map((d) => d.trim()).filter(Boolean));
    return toSelectOptions(Array.from(set).sort());
  }, [departments]);

  const onPeriodKindChange = (kind: string) => {
    const k = (PERIOD_KINDS.includes(kind as (typeof PERIOD_KINDS)[number])
      ? kind
      : "monthly") as (typeof PERIOD_KINDS)[number];
    setPeriodKind(k);
    setPeriodKey(currentPeriodKey(k));
  };

  const onAdd = async () => {
    setError(null);
    const dept = department.trim();
    if (!dept) {
      setError("Department is required");
      return;
    }
    try {
      await createMut.mutateAsync({
        department: dept,
        gl_ledger: glLedger.trim(),
        period_kind: periodKind,
        period_key: periodKey.trim(),
        allocated: allocated ?? 0,
        notes: notes.trim() || null,
      });
      setNotes("");
      setAllocated(0);
      setGlLedger("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create department budget");
    }
  };

  return (
    <div className="space-y-3">
      <div>
        <h3 className="text-sm font-semibold">Department budgets</h3>
        <p className="text-xs text-muted-foreground mt-0.5">
          Optional envelopes by department (and optional GL). Enforced as VR-TE08 on claims and
          against-advance. Leave blank to skip department budget checks.
        </p>
      </div>

      <Card className="p-3 space-y-3">
        <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
          <FieldLabel label="Department">
            <Input
              value={department}
              onChange={(e) => setDepartment(e.target.value)}
              list="te-dept-budget-departments"
              placeholder="e.g. Sales"
              className="h-8 text-xs"
            />
            {deptOptions.length > 0 ? (
              <datalist id="te-dept-budget-departments">
                {deptOptions.map((opt) => (
                  <option key={opt.value} value={opt.value} />
                ))}
              </datalist>
            ) : null}
          </FieldLabel>
          <FieldLabel label="GL ledger (optional)">
            <Input
              value={glLedger}
              onChange={(e) => setGlLedger(e.target.value)}
              placeholder="All GLs if empty"
              className="h-8 text-xs"
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
          <FieldLabel label="Allocated">
            <NumericInput
              value={allocated ?? undefined}
              onValueChange={(v) => setAllocated(v ?? null)}
              className="h-8 text-xs"
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
        {error ? <p className="text-xs text-destructive">{error}</p> : null}
        <Button
          type="button"
          size="sm"
          onClick={() => void onAdd()}
          disabled={createMut.isPending}
        >
          <Plus className="h-3.5 w-3.5 mr-1" />
          Add department budget
        </Button>
      </Card>

      {isLoading ? (
        <p className="text-sm text-muted-foreground py-4 text-center">Loading…</p>
      ) : rows.length === 0 ? (
        <EmptyState
          title="No department budgets"
          hint="Add an envelope above to enforce department spend limits (VR-TE08)."
        />
      ) : (
        <Card className="overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-xs text-muted-foreground border-b border-border text-left">
                  <th className="px-4 py-2.5 font-medium">Department</th>
                  <th className="px-3 py-2.5 font-medium">GL</th>
                  <th className="px-3 py-2.5 font-medium">Period</th>
                  <th className="px-3 py-2.5 font-medium text-right">Allocated</th>
                  <th className="px-3 py-2.5 font-medium">Notes</th>
                  <th className="px-4 py-2.5 font-medium w-12" />
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.id} className="row-band border-b border-border/60">
                    <td className="px-4 py-2.5 font-medium">{row.department}</td>
                    <td className="px-3 py-2.5 text-muted-foreground">
                      {row.gl_ledger || "(all)"}
                    </td>
                    <td className="px-3 py-2.5 text-muted-foreground">
                      {row.period_kind} · {row.period_key}
                    </td>
                    <td className="px-3 py-2.5 text-right tnum">
                      {money(Number(row.allocated), currency)}
                    </td>
                    <td className="px-3 py-2.5 text-muted-foreground truncate max-w-[160px]">
                      {row.notes || "—"}
                    </td>
                    <td className="px-4 py-2.5">
                      <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        className="h-7 w-7 p-0 text-muted-foreground hover:text-destructive"
                        disabled={deleteMut.isPending}
                        onClick={() => void deleteMut.mutateAsync(row.id)}
                        aria-label="Delete department budget"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}
    </div>
  );
}
