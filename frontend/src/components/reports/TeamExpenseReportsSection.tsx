import { useMemo } from "react";
import type {
  EmployeeAdvanceSettlementRow,
  EmployeeBudgetUtilizationRow,
  EmployeeExpenseSummaryRow,
} from "@/api/types";
import { EmptyState } from "@/components/EmptyState";
import { KpiCard } from "@/components/KpiCard";
import { Card } from "@/components/ui/card";
import {
  useTeamExpenseAdvanceSettlement,
  useTeamExpenseBudgetUtilization,
  useTeamExpenseExpenseSummary,
} from "@/hooks/useTeamExpenseReports";
import { money, toNumber } from "@/lib/format";
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
    case "expense_against_advance":
      return "Against advance";
    case "expense_claim":
      return "Claim";
    default:
      return kind || "—";
  }
}

function statusLabel(status: string): string {
  if (!status) return "—";
  return status.replace(/_/g, " ");
}

export function TeamExpenseReportsSection({
  month,
  currency,
  locale,
}: TeamExpenseReportsSectionProps) {
  const range = useMemo(() => monthToDateRange(month), [month]);
  const { data: advanceRows, isLoading: advanceLoading } = useTeamExpenseAdvanceSettlement();
  const { data: budgetRows, isLoading: budgetLoading } = useTeamExpenseBudgetUtilization();
  const { data: summaryRows, isLoading: summaryLoading } = useTeamExpenseExpenseSummary(
    range.dateFrom,
    range.dateTo
  );

  const fmt = (value: number | string | null | undefined) =>
    money(toNumber(value), currency, locale);

  const advance = advanceRows ?? [];
  const budgets = budgetRows ?? [];
  const summary = summaryRows ?? [];

  const totals = useMemo(() => {
    const advanceOutstanding = advance.reduce(
      (sum, row) => sum + toNumber(row.advance_ledger_balance),
      0
    );
    const available = advance.reduce((sum, row) => sum + toNumber(row.available_advance), 0);
    const pending = advance.reduce(
      (sum, row) => sum + toNumber(row.pending_against_advance),
      0
    );
    const overBudget = budgets.filter((row) => {
      const monthlyCap = row.budget_monthly ?? 0;
      return monthlyCap > 0 && row.mtd_spent > monthlyCap;
    }).length;
    return {
      advanceOutstanding,
      available,
      pending,
      overBudget,
      employeeCount: advance.length || budgets.length,
      summaryCount: summary.length,
    };
  }, [advance, budgets, summary.length]);

  const loading = advanceLoading || budgetLoading || summaryLoading;

  return (
    <Card className="p-4 mt-6">
      <h2 className="text-base font-semibold mb-1">Team expense reports</h2>
      <p className="text-xs text-muted-foreground mb-4">
        Advance settlement and budget utilization are live snapshots. Expense summary shows Team
        Expenses documents for {month}. Download full CSV from the menu above.
      </p>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4 mb-4">
        <KpiCard
          label="Advance outstanding"
          value={loading ? "…" : fmt(totals.advanceOutstanding)}
          delta={{ dir: "flat", text: `${totals.employeeCount} employees` }}
          testid="kpi-te-advance"
        />
        <KpiCard
          label="Available advance"
          value={loading ? "…" : fmt(totals.available)}
          delta={{
            dir: "flat",
            text: `${fmt(totals.pending)} pending`,
          }}
          testid="kpi-te-available"
        />
        <KpiCard
          label="Over monthly budget"
          value={loading ? "…" : totals.overBudget}
          delta={{ dir: "flat", text: "employees" }}
          testid="kpi-te-over-budget"
        />
        <KpiCard
          label="Expense lines (month)"
          value={loading ? "…" : totals.summaryCount}
          delta={{ dir: "flat", text: month }}
          testid="kpi-te-summary-count"
        />
      </div>

      <div className="grid gap-4 lg:grid-cols-2 mb-4">
        <AdvanceSettlementTable rows={advance} currency={currency} locale={locale} loading={advanceLoading} />
        <BudgetUtilizationTable rows={budgets} currency={currency} locale={locale} loading={budgetLoading} />
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
  const fmt = (value: number | string) => money(toNumber(value), currency, locale);

  return (
    <div>
      <h3 className="text-sm font-semibold mb-3">Employee advance settlement</h3>
      {loading ? (
        <p className="text-sm text-muted-foreground py-6 text-center">Loading…</p>
      ) : rows.length === 0 ? (
        <EmptyState
          title="No employees"
          hint="Add employees in Rule Book to see advance balances."
        />
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-muted-foreground border-b border-border">
                <th className="py-1.5 font-medium">Employee</th>
                <th className="py-1.5 font-medium text-right">Ledger</th>
                <th className="py-1.5 font-medium text-right">Pending</th>
                <th className="py-1.5 font-medium text-right">Available</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.employee_id} className="row-band border-b border-border/60">
                  <td className="py-1.5">
                    <div className="truncate max-w-[180px] font-medium">{row.name}</div>
                    <div className="text-xs text-muted-foreground truncate max-w-[180px]">
                      {row.email || row.division || row.location || "—"}
                    </div>
                  </td>
                  <td className="py-1.5 text-right tnum">{fmt(row.advance_ledger_balance)}</td>
                  <td className="py-1.5 text-right tnum text-muted-foreground">
                    {fmt(row.pending_against_advance)}
                  </td>
                  <td className="py-1.5 text-right tnum font-medium">{fmt(row.available_advance)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function BudgetUtilizationTable({
  rows,
  currency,
  locale,
  loading,
}: {
  rows: EmployeeBudgetUtilizationRow[];
  currency: string;
  locale?: string;
  loading: boolean;
}) {
  const fmt = (value: number | string | null | undefined) =>
    money(toNumber(value), currency, locale);

  return (
    <div>
      <h3 className="text-sm font-semibold mb-3">Employee budget utilization</h3>
      {loading ? (
        <p className="text-sm text-muted-foreground py-6 text-center">Loading…</p>
      ) : rows.length === 0 ? (
        <EmptyState
          title="No employees"
          hint="Budget caps and claim spend appear from the employee master."
        />
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-muted-foreground border-b border-border">
                <th className="py-1.5 font-medium">Employee</th>
                <th className="py-1.5 font-medium text-right">MTD / Cap</th>
                <th className="py-1.5 font-medium text-right">Remaining</th>
                <th className="py-1.5 font-medium text-right">Used</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => {
                const over =
                  (row.budget_monthly ?? 0) > 0 && row.mtd_spent > row.budget_monthly;
                return (
                  <tr key={row.employee_id} className="row-band border-b border-border/60">
                    <td className="py-1.5">
                      <div className="truncate max-w-[180px] font-medium">{row.name}</div>
                      <div className="text-xs text-muted-foreground truncate max-w-[180px]">
                        {row.department || row.division || "—"}
                      </div>
                    </td>
                    <td className="py-1.5 text-right tnum">
                      {fmt(row.mtd_spent)}
                      <span className="text-muted-foreground">
                        {" "}
                        / {row.budget_monthly > 0 ? fmt(row.budget_monthly) : "—"}
                      </span>
                    </td>
                    <td className="py-1.5 text-right tnum text-muted-foreground">
                      {row.monthly_remaining == null ? "—" : fmt(row.monthly_remaining)}
                    </td>
                    <td
                      className={`py-1.5 text-right tnum font-medium ${
                        over ? "text-destructive" : ""
                      }`}
                    >
                      {row.monthly_utilization_pct == null
                        ? "—"
                        : `${row.monthly_utilization_pct}%`}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
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
  const fmt = (value: number | string | null | undefined) =>
    money(toNumber(value), currency, locale);

  return (
    <div>
      <div className="flex items-baseline justify-between gap-2 mb-3">
        <h3 className="text-sm font-semibold">Employee expense summary</h3>
        <p className="text-xs text-muted-foreground">{month}</p>
      </div>
      {loading ? (
        <p className="text-sm text-muted-foreground py-6 text-center">Loading…</p>
      ) : rows.length === 0 ? (
        <EmptyState
          title="No team expenses this month"
          hint="Claims, advances, and against-advance documents appear here after capture."
        />
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-muted-foreground border-b border-border">
                <th className="py-1.5 font-medium">Employee</th>
                <th className="py-1.5 font-medium">Document</th>
                <th className="py-1.5 font-medium">Line / ledger</th>
                <th className="py-1.5 font-medium text-right">Amount</th>
                <th className="py-1.5 font-medium text-right">Status</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row, index) => (
                <tr
                  key={`${row.invoice_id}-${index}`}
                  className="row-band border-b border-border/60"
                >
                  <td className="py-1.5">
                    <div className="truncate max-w-[140px] font-medium">
                      {row.employee_name || "Unmatched"}
                    </div>
                    <div className="text-xs text-muted-foreground truncate max-w-[140px]">
                      {[row.division, row.location].filter(Boolean).join(" · ") ||
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
                      {row.ledger_name || row.ledger_code || "—"}
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
  );
}
