/** Report helpers — maps API rows to chart/CSV shapes. */

import type { GlAccountSpendRow, ReportDocumentRow, VendorSpendRow } from "@/api/types";
import { toNumber } from "@/lib/format";
import { KPI_MODULE_CHART_COLORS } from "@/lib/kpiModuleColors";
import { tenantMonthKey } from "@/lib/tenantTime";

export type ReportInvoice = {
  id: string;
  vendor: string;
  account: string;
  period: string;
  invoiceDate: string;
  subtotal: number;
  gst: number;
  total: number;
};

export type GlAccountRow = {
  account: string;
  amount: number;
  count: number;
};

export type VendorSpendRowLocal = {
  vendor: string;
  amount: number;
  count: number;
};

export function mapReportDocument(row: ReportDocumentRow): ReportInvoice {
  return {
    id: row.document_ref,
    vendor: row.vendor,
    account: row.account,
    period: row.period_key,
    invoiceDate: row.invoice_date ?? "",
    subtotal: toNumber(row.subtotal),
    gst: toNumber(row.gst),
    total: toNumber(row.total),
  };
}

export function mapGlAccountRow(row: GlAccountSpendRow): GlAccountRow {
  return {
    account: row.account,
    amount: toNumber(row.amount),
    count: row.count,
  };
}

export function mapVendorSpendRow(row: VendorSpendRow): VendorSpendRowLocal {
  return {
    vendor: row.vendor,
    amount: toNumber(row.amount),
    count: row.count,
  };
}

export function buildReportsCsv(invoices: ReportInvoice[]): string {
  const header = ["Document", "Vendor", "GL Account", "Invoice date", "Net", "Tax", "Gross"];
  const rows = invoices.map((inv) =>
    [
      inv.id,
      inv.vendor,
      inv.account,
      inv.invoiceDate,
      inv.subtotal,
      inv.gst,
      inv.total,
    ].join(",")
  );
  return [header.join(","), ...rows].join("\n");
}

/** Same accent palette as dashboard KPI module icons (see kpi.css). */
export const REPORT_CHART_COLORS = KPI_MODULE_CHART_COLORS;

export function defaultReportPeriod(timeZone: string): string {
  return tenantMonthKey(timeZone);
}

export function buildReportPeriodOptions(timeZone: string, locale = "en-US"): { label: string; value: string }[] {
  return [0, 1, 2].map((offset) => {
    const value = tenantMonthKey(timeZone, offset);
    const [y, m] = value.split("-").map(Number);
    const label = new Date(y, m - 1, 1).toLocaleString(locale, { month: "long", year: "numeric" });
    return { label, value };
  });
}
