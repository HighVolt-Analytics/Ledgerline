/** Team expense report CSV builders for the Reports download menu. */

import type {
  EmployeeAdvanceSettlementRow,
  EmployeeBudgetUtilizationRow,
  EmployeeExpenseSummaryRow,
} from "@/api/types";
import { toNumber } from "@/lib/format";
import { downloadCsvFile } from "@/lib/reportExports";

function escapeCsvCell(value: string | number): string {
  const text = String(value);
  if (/[",\n]/.test(text)) {
    return `"${text.replace(/"/g, '""')}"`;
  }
  return text;
}

function rowsToCsv(header: string[], data: (string | number)[][]): string {
  const lines = [
    header.map(escapeCsvCell).join(","),
    ...data.map((row) => row.map(escapeCsvCell).join(",")),
  ];
  return lines.join("\n");
}

function blank(value: string | number | null | undefined): string | number {
  if (value == null) return "";
  return value;
}

const ADVANCE_HEADERS = [
  "Employee ID",
  "Name",
  "Role",
  "Email",
  "Mobile",
  "Mobile 2",
  "Viber",
  "Date of joining",
  "Department",
  "Division",
  "Location",
  "Supervisor 1",
  "Supervisor 2",
  "Bank name",
  "Bank account name",
  "Bank account number",
  "BSB",
  "SWIFT",
  "IBAN",
  "Advance parent ledger",
  "Advance sub ledger",
  "Status",
  "Claim count",
  "Last claim",
  "Claim YTD spent",
  "Advance ledger balance",
  "Pending against advance",
  "Available advance",
];

export function buildAdvanceSettlementCsv(rows: EmployeeAdvanceSettlementRow[]): string {
  return rowsToCsv(
    ADVANCE_HEADERS,
    rows.map((r) => [
      r.employee_id,
      r.name,
      r.role,
      r.email,
      r.whatsapp_number,
      r.whatsapp_number_2,
      r.viber_number ?? "",
      r.date_of_joining,
      r.department,
      r.division,
      r.location,
      r.supervisor_1,
      r.supervisor_2,
      r.bank_name,
      r.bank_account_name,
      r.bank_account_number,
      r.bank_bsb,
      r.bank_swift,
      r.bank_iban,
      r.advance_parent_ledger,
      r.advance_sub_ledger,
      r.status,
      r.claim_count,
      r.last_claim,
      toNumber(r.claim_ytd_spent),
      toNumber(r.advance_ledger_balance),
      toNumber(r.pending_against_advance),
      toNumber(r.available_advance),
    ])
  );
}

const BUDGET_HEADERS = [
  "Employee ID",
  "Name",
  "Role",
  "Email",
  "Mobile",
  "Mobile 2",
  "Viber",
  "Date of joining",
  "Department",
  "Division",
  "Location",
  "Supervisor 1",
  "Supervisor 2",
  "Bank name",
  "Bank account name",
  "Bank account number",
  "BSB",
  "SWIFT",
  "IBAN",
  "Status",
  "Monthly budget",
  "Monthly spent",
  "Monthly remaining",
  "Monthly utilization %",
  "Quarterly budget",
  "Quarterly spent",
  "Quarterly remaining",
  "Quarterly utilization %",
  "Annual budget",
  "Annual spent",
  "Annual remaining",
  "Annual utilization %",
  "Category caps",
  "Claim count",
  "Last claim",
];

export function buildBudgetUtilizationCsv(rows: EmployeeBudgetUtilizationRow[]): string {
  return rowsToCsv(
    BUDGET_HEADERS,
    rows.map((r) => [
      r.employee_id,
      r.name,
      r.role,
      r.email,
      r.whatsapp_number,
      r.whatsapp_number_2,
      r.viber_number ?? "",
      r.date_of_joining,
      r.department,
      r.division,
      r.location,
      r.supervisor_1,
      r.supervisor_2,
      r.bank_name,
      r.bank_account_name,
      r.bank_account_number,
      r.bank_bsb,
      r.bank_swift,
      r.bank_iban,
      r.status,
      r.budget_monthly,
      r.mtd_spent,
      blank(r.monthly_remaining),
      blank(r.monthly_utilization_pct),
      r.budget_quarterly,
      r.qtd_spent,
      blank(r.quarterly_remaining),
      blank(r.quarterly_utilization_pct),
      r.budget_annual,
      r.ytd_spent,
      blank(r.annual_remaining),
      blank(r.annual_utilization_pct),
      r.category_caps,
      r.claim_count,
      r.last_claim,
    ])
  );
}

const SUMMARY_HEADERS = [
  "Employee name",
  "Email",
  "Mobile",
  "Division",
  "Location",
  "Document no.",
  "Invoice date",
  "Expense type",
  "Document type",
  "Line item",
  "Qty",
  "Line amount",
  "Currency",
  "Ledger code",
  "Ledger",
  "Status",
  "Evaluation status",
];

export function buildExpenseSummaryCsv(rows: EmployeeExpenseSummaryRow[]): string {
  return rowsToCsv(
    SUMMARY_HEADERS,
    rows.map((r) => [
      r.employee_name,
      r.employee_email,
      r.mobile,
      r.division,
      r.location,
      r.document_no,
      r.invoice_date ?? "",
      r.team_expense_kind,
      r.document_type_code,
      r.line_description,
      blank(r.line_qty == null ? null : toNumber(r.line_qty)),
      blank(r.line_amount == null ? null : toNumber(r.line_amount)),
      r.currency,
      r.ledger_code,
      r.ledger_name,
      r.status,
      r.evaluation_status,
    ])
  );
}

export function downloadAdvanceSettlementCsv(
  rows: EmployeeAdvanceSettlementRow[],
  periodLabel: string
): void {
  downloadCsvFile(buildAdvanceSettlementCsv(rows), `employee_advance_settlement_${periodLabel}.csv`);
}

export function downloadBudgetUtilizationCsv(
  rows: EmployeeBudgetUtilizationRow[],
  periodLabel: string
): void {
  downloadCsvFile(buildBudgetUtilizationCsv(rows), `employee_budget_utilization_${periodLabel}.csv`);
}

export function downloadExpenseSummaryCsv(
  rows: EmployeeExpenseSummaryRow[],
  periodLabel: string
): void {
  downloadCsvFile(buildExpenseSummaryCsv(rows), `employee_expense_summary_${periodLabel}.csv`);
}
