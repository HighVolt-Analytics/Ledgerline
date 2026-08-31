import { Fragment, useMemo, useState } from "react";
import type {
  EmployeeAdvanceSettlementRow,
  DepartmentBudgetUtilizationRow,
  EmployeeExpenseSummaryRow,
} from "@/api/types";
import { EmptyState } from "@/components/EmptyState";
import { KpiCard } from "@/components/KpiCard";
import { ListSearchInput } from "@/components/ListSearchInput";
import { Card } from "@/components/ui/card";
import {
  useTeamExpenseAdvanceSettlement,
  useTeamExpenseDepartmentBudgetUtilization,
  useTeamExpenseExpenseSummary,
} from "@/hooks/useTeamExpenseReports";
import { money, toNumber } from "@/lib/format";
import { matchesListSearch } from "@/lib/listSearch";
import { monthToDateRange } from "@/lib/reportExports";

type TeamExpenseReportsSectionProps = {
  month: string;
  currency: string;
  locale?: string;
};

function kindLabel(kind: string): string {
  switch (kind) {
    case "advance_requisition":
      return "Advance";
    case "expense_claim":
    case "expense_against_advance":
      return "Claim";
    default:
      return kind || "—";
  }
}

function statusLabel(status: string): string {
  if (!status) return "—";
  return status.replace(/_/g, " ");
}

function enforcementLabel(value: string | undefined): string {
  return value === "hard" ? "Hard" : "Soft";
}

export function TeamExpenseReportsSection({
  month,
  currency,
  locale,
}: TeamExpenseReportsSectionProps) {
  const range = useMemo(() => monthToDateRange(month), [month]);
  const { data: advanceRows, isLoading: advanceLoading } = useTeamExpenseAdvanceSettlement();
  const { data: deptBudgetRows, isLoading: deptBudgetLoading } =
    useTeamExpenseDepartmentBudgetUtilization();
  const { data: summaryRows, isLoading: summaryLoading } = useTeamExpenseExpenseSummary(
    range.dateFrom,
    range.dateTo
  );

  const fmt = (value: number | string | null | undefined) =>
    money(toNumber(value), currency, locale);

  const advance = advanceRows ?? [];
  const deptBudgets = deptBudgetRows ?? [];
  const summary = summaryRows ?? [];

  const totals = useMemo(() => {
    const took = advance.reduce((sum, row) => sum + toNumber(row.advance_taken), 0);
    const used = advance.reduce((sum, row) => sum + toNumber(row.advance_used), 0);
    const outstanding = advance.reduce(
      (sum, row) => sum + toNumber(row.advance_ledger_balance),
      0
    );
    const available = advance.reduce((sum, row) => sum + toNumber(row.available_advance), 0);
    const overGl = deptBudgets.filter(
      (row) => row.allocated > 0 && row.consumed > row.allocated
    ).length;
    const claimLines = summary.filter((row) => {
      const kind = (row.team_expense_kind || "").toLowerCase();
      return kind === "expense_claim" || kind === "expense_against_advance" || !kind;
    }).length;
    const advanceLines = summary.filter(
      (row) => (row.team_expense_kind || "").toLowerCase() === "advance_requisition"
    ).length;
    return {
      took,
      used,
      outstanding,
      available,
      overGl,
      claimLines,
      advanceLines,
      employeeCount: advance.filter(
        (row) =>
          toNumber(row.advance_taken) > 0 ||
          toNumber(row.advance_used) > 0 ||
          toNumber(row.advance_ledger_balance) > 0
      ).length,
    };
  }, [advance, deptBudgets, summary]);

  const loading = advanceLoading || deptBudgetLoading || summaryLoading;

  return (
    <Card className="p-4 mt-6">
      <h2 className="text-base font-semibold mb-1">Team expense finance reports</h2>
      <p className="text-xs text-muted-foreground mb-4">
        Advances are employee float (balance sheet) — Took / Used / Outstanding. Expense claims
        hit GL budgets on the full claim amount and net any available advance first. Soft budgets
        route overruns for approval; hard budgets block until raised. Period shown for documents:{" "}
        {month}.
      </p>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-5 mb-4">
        <KpiCard
          label="Advance outstanding"
          value={loading ? "…" : fmt(totals.outstanding)}
          delta={{ dir: "flat", text: `${totals.employeeCount} with float` }}
          testid="kpi-te-advance"
        />
        <KpiCard
          label="Advance taken"
          value={loading ? "…" : fmt(totals.took)}
          delta={{ dir: "flat", text: `${fmt(totals.used)} used` }}
          testid="kpi-te-took"
        />
        <KpiCard
          label="Advance available"
          value={loading ? "…" : fmt(totals.available)}
          delta={{ dir: "flat", text: "after pending claims" }}
          testid="kpi-te-available"
        />
        <KpiCard
          label="GL budgets over"
          value={loading ? "…" : totals.overGl}
          delta={{ dir: "flat", text: "parent wallets" }}
          testid="kpi-te-over-dept"
        />
        <KpiCard
          label="Docs this month"
          value={loading ? "…" : summary.length}
          delta={{
            dir: "flat",
            text: `${totals.claimLines} claims · ${totals.advanceLines} advances`,
          }}
          testid="kpi-te-summary"
        />
      </div>

      <div className="mb-4">
        <AdvanceSettlementTable
          rows={advance}
          currency={currency}
          locale={locale}
          loading={advanceLoading}
        />
      </div>

      <div className="mb-4">
        <DepartmentBudgetUtilizationTable
          rows={deptBudgets}
          currency={currency}
          locale={locale}
          loading={deptBudgetLoading}
        />
      </div>

      <ExpenseSummaryTable
        rows={summary}
        currency={currency}
        locale={locale}
        loading={summaryLoading}
        month={month}
      />
    </Card>
  );
}

function AdvanceSettlementTable({
  rows,
  currency,
  locale,
  loading,
}: {
  rows: EmployeeAdvanceSettlementRow[];
  currency: string;
  locale?: string;
  loading: boolean;
}) {
  const [searchQuery, setSearchQuery] = useState("");
  const fmt = (value: number | string | null | undefined) =>
    money(toNumber(value), currency, locale);

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
          row.department,
          row.division,
          row.location
        )
      ),
    [active, searchQuery]
  );

  return (
    <div>
      <h3 className="text-sm font-semibold mb-1">Employee advance float</h3>
      <p className="text-xs text-muted-foreground mb-3">
        Took = paid out · Used = netted by claims · Outstanding = still held · Available =
        outstanding minus open claims
      </p>
      {loading ? (
        <p className="text-sm text-muted-foreground py-6 text-center">Loading…</p>
      ) : active.length === 0 ? (
        <EmptyState
          title="No advance float"
          hint="Posted advance requisitions and claim netting appear here."
        />
      ) : (
        <div className="space-y-2">
          <ListSearchInput
            value={searchQuery}
            onChange={setSearchQuery}
            placeholder="Search employees…"
            testId="input-report-te-advance-search"
          />
          {filtered.length === 0 ? (
            <p className="text-sm text-muted-foreground text-center py-4">
              No employees match your search.
            </p>
          ) : (
            <div className="overflow-x-auto max-h-[min(360px,45dvh)] overflow-y-auto">
              <table className="w-full text-sm">
                <thead className="sticky top-0 bg-card z-10">
                  <tr className="text-left text-xs text-muted-foreground border-b border-border">
                    <th className="py-1.5 font-medium">Employee</th>
                    <th className="py-1.5 font-medium text-right">Took</th>
                    <th className="py-1.5 font-medium text-right">Used</th>
                    <th className="py-1.5 font-medium text-right">Outstanding</th>
                    <th className="py-1.5 font-medium text-right">Pending</th>
                    <th className="py-1.5 font-medium text-right">Available</th>
                  </tr>
                </thead>
                <tbody>
                  {filtered.map((row) => (
                    <tr key={row.employee_id} className="row-band border-b border-border/60">
                      <td className="py-1.5">
                        <div className="truncate max-w-[180px] font-medium">{row.name}</div>
                        <div className="text-xs text-muted-foreground truncate max-w-[180px]">
                          {row.email || row.division || row.location || "—"}
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
    </div>
  );
}

function DepartmentBudgetUtilizationTable({
  rows,
  currency,
  locale,
  loading,
}: {
  rows: DepartmentBudgetUtilizationRow[];
  currency: string;
  locale?: string;
  loading: boolean;
}) {
  const [searchQuery, setSearchQuery] = useState("");
  const fmt = (value: number | string | null | undefined) =>
    money(toNumber(value), currency, locale);

  const filtered = useMemo(
    () =>
      rows.filter((row) =>
        matchesListSearch(searchQuery, row.gl_ledger, row.period_key, row.notes, row.department)
      ),
    [rows, searchQuery]
  );

  return (
    <div>
      <h3 className="text-sm font-semibold mb-1">GL budget utilization</h3>
      <p className="text-xs text-muted-foreground mb-3">
        Finance control for expense claims. Soft = manager override on overrun; Hard = raise
        budget first. Advances do not consume these wallets.
      </p>
      {loading ? (
        <p className="text-sm text-muted-foreground py-6 text-center">Loading…</p>
      ) : rows.length === 0 ? (
        <EmptyState
          title="No GL budgets for current period"
          hint="Configure budgets on Team Expenses → GL budgets."
        />
      ) : (
        <div className="space-y-2">
          <ListSearchInput
            value={searchQuery}
            onChange={setSearchQuery}
            placeholder="Search GL budgets…"
            testId="input-report-te-gl-budget-search"
          />
          {filtered.length === 0 ? (
            <p className="text-sm text-muted-foreground text-center py-4">
              No budgets match your search.
            </p>
          ) : (
            <div className="overflow-x-auto max-h-[min(360px,45dvh)] overflow-y-auto">
              <table className="w-full text-sm">
                <thead className="sticky top-0 bg-card z-10">
                  <tr className="text-left text-xs text-muted-foreground border-b border-border">
                    <th className="py-1.5 font-medium">GL account</th>
                    <th className="py-1.5 font-medium">Period</th>
                    <th className="py-1.5 font-medium">Rule</th>
                    <th className="py-1.5 font-medium text-right">Budget</th>
                    <th className="py-1.5 font-medium text-right">Spent</th>
                    <th className="py-1.5 font-medium text-right">Left</th>
                    <th className="py-1.5 font-medium text-right">Used %</th>
                  </tr>
                </thead>
                <tbody>
                  {filtered.map((row) => {
                    const left = row.remaining;
                    const over = left != null && left < 0;
                    const pct = row.utilization_pct;
                    const breakdown = row.sub_breakdown ?? [];
                    return (
                      <Fragment key={row.budget_id}>
                        <tr className="row-band border-b border-border/60">
                          <td className="py-1.5 font-medium">{row.gl_ledger}</td>
                          <td className="py-1.5 text-muted-foreground">
                            {row.period_kind} · {row.period_key}
                          </td>
                          <td className="py-1.5 text-xs text-muted-foreground">
                            {enforcementLabel(row.enforcement)}
                          </td>
                          <td className="py-1.5 text-right tnum">{fmt(row.allocated)}</td>
                          <td className="py-1.5 text-right tnum">{fmt(row.consumed)}</td>
                          <td
                            className={`py-1.5 text-right tnum font-medium ${
                              over ? "text-destructive" : ""
                            }`}
                          >
                            {left == null ? "—" : fmt(left)}
                          </td>
                          <td
                            className={`py-1.5 text-right tnum font-medium ${
                              over ? "text-destructive" : ""
                            }`}
                          >
                            {pct == null ? "—" : `${pct}%`}
                          </td>
                        </tr>
                        {breakdown.map((sub) => (
                          <tr
                            key={`${row.budget_id}-${sub.gl_ledger}`}
                            className="border-b border-border/40 text-muted-foreground"
                          >
                            <td className="py-1 pl-4 text-xs">↳ {sub.gl_ledger}</td>
                            <td className="py-1" />
                            <td className="py-1" />
                            <td className="py-1" />
                            <td className="py-1 text-right tnum text-xs">{fmt(sub.consumed)}</td>
                            <td className="py-1" />
                            <td className="py-1 text-right tnum text-xs">
                              {sub.pct_of_budget}%
                            </td>
                          </tr>
                        ))}
                      </Fragment>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function ExpenseSummaryTable({
  rows,
  currency,
  locale,
  loading,
  month,
}: {
  rows: EmployeeExpenseSummaryRow[];
  currency: string;
  locale?: string;
  loading: boolean;
  month: string;
}) {
  const [searchQuery, setSearchQuery] = useState("");
  const fmt = (value: number | string | null | undefined) =>
    money(toNumber(value), currency, locale);

  const filtered = useMemo(
    () =>
      rows.filter((row) =>
        matchesListSearch(
          searchQuery,
          row.employee_id,
          row.employee_name,
          row.employee_email,
          row.document_no,
          row.team_expense_kind,
          row.line_description,
          row.main_gl,
          row.sub_ledger,
          row.ledger_code,
          row.department,
          row.division,
          row.location,
          row.status
        )
      ),
    [rows, searchQuery]
  );

  return (
    <div>
      <div className="flex items-baseline justify-between gap-2 mb-1">
        <h3 className="text-sm font-semibold">Employee expense summary</h3>
        <p className="text-xs text-muted-foreground">{month}</p>
      </div>
      <p className="text-xs text-muted-foreground mb-3">
        Claims = P&amp;L / GL budget spend. Advances = float only (do not hit GL budgets).
      </p>
      {loading ? (
        <p className="text-sm text-muted-foreground py-6 text-center">Loading…</p>
      ) : rows.length === 0 ? (
        <EmptyState
          title="No team expenses this month"
          hint="Claims and advance requisitions appear here after capture."
        />
      ) : (
        <div className="space-y-2">
          <ListSearchInput
            value={searchQuery}
            onChange={setSearchQuery}
            placeholder="Search documents, employees, ledgers…"
            testId="input-report-te-summary-search"
          />
          {filtered.length === 0 ? (
            <p className="text-sm text-muted-foreground text-center py-4">
              No rows match your search.
            </p>
          ) : (
            <div className="overflow-x-auto max-h-[min(420px,50dvh)] overflow-y-auto">
              <table className="w-full text-sm">
                <thead className="sticky top-0 bg-card z-10">
                  <tr className="text-left text-xs text-muted-foreground border-b border-border">
                    <th className="py-1.5 font-medium">Employee</th>
                    <th className="py-1.5 font-medium">Document</th>
                    <th className="py-1.5 font-medium">Line / ledger</th>
                    <th className="py-1.5 font-medium text-right">Amount</th>
                    <th className="py-1.5 font-medium text-right">Status</th>
                  </tr>
                </thead>
                <tbody>
                  {filtered.map((row, index) => (
                    <tr
                      key={`${row.invoice_id}-${index}`}
                      className="row-band border-b border-border/60"
                    >
                      <td className="py-1.5">
                        <div className="truncate max-w-[140px] font-medium">
                          {row.employee_name || "Unmatched"}
                        </div>
                        <div className="text-xs text-muted-foreground truncate max-w-[140px]">
                          {[row.employee_id, row.department, row.division, row.location]
                            .filter(Boolean)
                            .join(" · ") ||
                            row.employee_email ||
                            "—"}
                        </div>
                      </td>
                      <td className="py-1.5">
                        <div className="truncate max-w-[120px]">{row.document_no}</div>
                        <div className="text-xs text-muted-foreground">
                          {kindLabel(row.team_expense_kind)}
                        </div>
                      </td>
                      <td className="py-1.5">
                        <div className="truncate max-w-[180px]">
                          {row.line_description || "—"}
                        </div>
                        <div className="text-xs text-muted-foreground truncate max-w-[180px]">
                          {[row.main_gl, row.sub_ledger].filter(Boolean).join(" · ") ||
                            row.ledger_code ||
                            "—"}
                        </div>
                      </td>
                      <td className="py-1.5 text-right tnum font-medium">
                        {row.line_amount == null ? "—" : fmt(row.line_amount)}
                      </td>
                      <td className="py-1.5 text-right text-xs capitalize text-muted-foreground">
                        {statusLabel(row.status)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

















































}

}

}

}
