import { describe, expect, it } from "vitest";
import type { Invoice } from "@/api/types";
import { invoiceToSalesRow, salesKpisFromRegister } from "@/lib/routePageAdapters";

const baseInvoice = {
  id: 1,
  currency: "AUD",
  created_at: "2026-01-15T10:00:00Z",
  document_ref: "DOC-S-1",
} as Invoice;

describe("invoiceToSalesRow", () => {
  it("maps vendor to customer and flags overdue invoices", () => {
    const row = invoiceToSalesRow({
      ...baseInvoice,
      vendor: "Harbour View Hotel",
      total: "250.00",
      invoice_date: "2026-01-10",
      due_date: "2020-01-01",
      status: "pending",
    });
    expect(row.customer).toBe("Harbour View Hotel");
    expect(row.amount).toBe(250);
    expect(row.overdue).toBe(true);
    expect(row.state).toBe("In Review");
  });

  it("uses em dash when vendor is missing", () => {
    const row = invoiceToSalesRow({
      ...baseInvoice,
      vendor: "   ",
      total: "0",
      status: "processed",
      published_to_ledger: true,
    });
    expect(row.customer).toBe("—");
    expect(row.state).toBe("Posted to Ledger");
  });
});

describe("salesKpisFromRegister", () => {
  it("counts open, posted, and overdue sales invoices", () => {
    const salesRows = [
      {
        id: 1,
        so_number: "SO-1",
        customer: "Customer A",
        so_qty: 10,
        so_unit_price: 10,
        variance_approved: false,
        status: "open",
        match: { status: "No DN", qty_variance_value: 0, price_variance_value: 0, total_deviation: 0, po_value: 100, invoice_value: 100, invoice_gst: 10, invoice_total: 110 },
      },
    ] as const;
    const routed: Invoice[] = [
      {
        ...baseInvoice,
        id: 1,
        vendor: "Customer A",
        total: "100",
        status: "new",
        due_date: "2020-01-01",
      },
      {
        ...baseInvoice,
        id: 2,
        vendor: "Customer B",
        total: "200",
        status: "exception",
        due_date: "2026-12-31",
      },
      {
        ...baseInvoice,
        id: 3,
        vendor: "Customer C",
        total: "300",
        status: "processed",
        published_to_ledger: true,
        due_date: "2026-12-31",
      },
    ];
    const kpis = salesKpisFromRegister([...salesRows], routed);
    expect(kpis.open).toBe(2);
    expect(kpis.pending).toBe(1);
    expect(kpis.postedCount).toBe(1);
    expect(kpis.postedTotal).toBe(300);
    expect(kpis.overdue).toBe(1);
    expect(kpis.missingDn).toBe(1);
  });
});
