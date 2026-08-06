import { useMemo, useState } from "react";
import { EmptyState } from "@/components/EmptyState";
import { ListSearchInput } from "@/components/ListSearchInput";
import { Card } from "@/components/ui/card";
import { useTeamExpenseAdvanceSettlement } from "@/hooks/useTeamExpenseReports";
import { money, toNumber } from "@/lib/format";
import { matchesListSearch } from "@/lib/listSearch";

type EmployeeAdvanceFloatPanelProps = {
  currency: string;
};

export function EmployeeAdvanceFloatPanel({ currency }: EmployeeAdvanceFloatPanelProps) {
  const { data: rows = [], isLoading } = useTeamExpenseAdvanceSettlement();
  const [searchQuery, setSearchQuery] = useState("");

  const active = useMemo(
    () =>
      rows.filter(
        (row) =>
          toNumber(row.advance_taken) > 0 ||
          toNumber(row.advance_used) > 0 ||
          toNumber(row.advance_ledger_balance) > 0 ||
          toNumber(row.pending_against_advance) > 0
      ),
    [rows]
  );

  const filtered = useMemo(
    () =>
      active.filter((row) =>
        matchesListSearch(
          searchQuery,
          row.employee_id,
          row.name,
          row.email,
          row.role,
          row.department,
          row.division,
          row.location,
          row.advance_sub_ledger
        )
      ),
    [active, searchQuery]
  );

  const totals = filtered.reduce(
    (acc, row) => ({
      took: acc.took + toNumber(row.advance_taken),
      used: acc.used + toNumber(row.advance_used),
      left: acc.left + toNumber(row.advance_ledger_balance),
    }),
    { took: 0, used: 0, left: 0 }
  );

  const fmt = (value: number | string | null | undefined) => money(toNumber(value), currency);

  return (
    <Card className="p-3 mb-4" data-testid="te-advance-float-panel">
      <div className="flex flex-wrap items-baseline justify-between gap-2 mb-2">
        <div>
          <h3 className="text-sm font-semibold">Employee advances</h3>
          <p className="text-xs text-muted-foreground mt-0.5">
            Took = advances paid out · Used = cleared by expense claims · Outstanding = still
            held by the employee
          </p>
        </div>
        {active.length > 0 ? (
          <p className="text-xs text-muted-foreground tnum shrink-0">
            {fmt(totals.took)} took · {fmt(totals.used)} used · {fmt(totals.left)} left
            {searchQuery.trim() ? ` · ${filtered.length} of ${active.length}` : ""}
          </p>
        ) : null}
      </div>

      {isLoading ? (
        <p className="text-sm text-muted-foreground py-4 text-center">Loading…</p>
      ) : active.length === 0 ? (
        <EmptyState
          title="No advance float yet"
          hint="When advance requisitions post, each employee’s took / used / outstanding appears here."
        />
      ) : (
        <div className="space-y-2">
          <ListSearchInput
            value={searchQuery}
            onChange={setSearchQuery}
            placeholder="Search employees by name, email, ID, division…"
            testId="input-te-advance-employee-search"
          />
          {filtered.length === 0 ? (
            <p className="text-sm text-muted-foreground text-center py-6">
              No employees match your search.
            </p>
          ) : (
            <div className="overflow-x-auto max-h-[min(420px,50dvh)] overflow-y-auto">
              <table className="w-full text-sm">
                <thead className="sticky top-0 bg-card z-10">
                  <tr className="text-left text-xs text-muted-foreground border-b border-border">
                    <th className="py-1.5 font-medium">Employee</th>
                    <th className="py-1.5 font-medium text-right">Took</th>
                    <th className="py-1.5 font-medium text-right">Used</th>
                    <th className="py-1.5 font-medium text-right">Outstanding</th>
                    <th className="py-1.5 font-medium text-right">Pending claims</th>
                    <th className="py-1.5 font-medium text-right">Available</th>
                  </tr>
                </thead>
                <tbody>
                  {filtered.map((row) => (
                    <tr
                      key={row.employee_id}
                      className="row-band border-b border-border/60"
                      data-testid={`te-advance-row-${row.employee_id}`}
                    >
                      <td className="py-1.5">
                        <div className="truncate max-w-[200px] font-medium">{row.name}</div>
                        <div className="text-xs text-muted-foreground truncate max-w-[200px]">
                          {[row.employee_id, row.division, row.location, row.email]
                            .filter(Boolean)
                            .join(" · ") || "—"}
                        </div>
                      </td>
                      <td className="py-1.5 text-right tnum">{fmt(row.advance_taken)}</td>
                      <td className="py-1.5 text-right tnum">{fmt(row.advance_used)}</td>
                      <td className="py-1.5 text-right tnum font-medium">
                        {fmt(row.advance_ledger_balance)}
                      </td>
                      <td className="py-1.5 text-right tnum text-muted-foreground">
                        {fmt(row.pending_against_advance)}
                      </td>
                      <td className="py-1.5 text-right tnum">{fmt(row.available_advance)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </Card>
  );
}
