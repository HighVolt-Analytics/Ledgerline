/** Report helpers — maps API rows to chart/CSV shapes. */

import type { GlAccountSpendRow, ReportDocumentRow, VendorSpendRow } from "@/api/types";
import { toNumber } from "@/lib/format";

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

export const REPORT_CHART_COLORS = [
  "hsl(186 64% 34%)",
  "hsl(186 56% 44%)",
  "hsl(186 48% 54%)",
  "hsl(43 74% 49%)",
  "hsl(200 50% 50%)",
  "hsl(160 50% 42%)",
  "hsl(20 60% 55%)",
  "hsl(280 40% 55%)",
] as const;

export function defaultReportPeriod(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

export function buildReportPeriodOptions(): { label: string; value: string }[] {
  const now = new Date();
  return [0, 1, 2].map((offset) => {
    const d = new Date(now.getFullYear(), now.getMonth() - offset, 1);
    const value = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
    const label = d.toLocaleString("en-US", { month: "long", year: "numeric" });
    return { label, value };
  });
}
