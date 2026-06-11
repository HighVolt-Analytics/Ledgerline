/** Reports page — period helpers and client-side CSV builders. */

import type { GlAccountSpendRow, ReportDocumentRow, ReportsAnalytics, VendorSpendRow } from "@/api/types";
import { saveBlobAsFile } from "@/api/client";
import { toNumber } from "@/lib/format";
import { buildReportsCsv, mapReportDocument } from "@/lib/reportsData";

export type ReportDateFilter = {
  dateFrom: string;
  dateTo: string;
};

export function monthToDateRange(month: string): ReportDateFilter {
  const [yearS, monthS] = month.split("-");
  const year = Number(yearS);
  const monthNum = Number(monthS);
  const lastDay = new Date(year, monthNum, 0).getDate();
  return {
    dateFrom: `${month}-01`,
    dateTo: `${month}-${String(lastDay).padStart(2, "0")}`,
  };
}

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

export function buildGlAccountCsv(rows: GlAccountSpendRow[]): string {
  return rowsToCsv(
    ["GL account", "Line count", "Net spend"],
    rows.map((row) => [row.account, row.count, toNumber(row.amount)])
  );
}

export function buildVendorSpendCsv(rows: VendorSpendRow[]): string {
  return rowsToCsv(
    ["Vendor", "Document count", "Spend"],
    rows.map((row) => [row.vendor, row.count, toNumber(row.amount)])
  );
}

export function downloadCsvFile(csv: string, filename: string): void {
  saveBlobAsFile(new Blob([csv], { type: "text/csv;charset=utf-8;" }), filename);
}

export function downloadDocumentRegisterCsv(
  rows: ReportDocumentRow[],
  month: string
): void {
  const csv = buildReportsCsv(rows.map(mapReportDocument));
  downloadCsvFile(csv, `document_register_${month}.csv`);
}

export function downloadGlSummaryCsv(analytics: ReportsAnalytics, month: string): void {
  const csv = buildGlAccountCsv(analytics.by_gl_account ?? []);
  downloadCsvFile(csv, `gl_summary_${month}.csv`);
}

export function downloadVendorSummaryCsv(analytics: ReportsAnalytics, month: string): void {
  const csv = buildVendorSpendCsv(analytics.top_vendors ?? []);
  downloadCsvFile(csv, `vendor_summary_${month}.csv`);
}
