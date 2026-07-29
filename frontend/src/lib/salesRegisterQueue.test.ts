import { describe, expect, it } from "vitest";
import type { Invoice, SalesOrderApi } from "@/api/types";
import {
  buildSalesRegisterCoverage,
  salesActionIssue,
  salesActionRequiredInvoices,
  salesInvoiceNeedsAction,
} from "@/lib/salesRegisterQueue";

const baseInvoice = (overrides: Partial<Invoice>): Invoice =>
  ({
    id: 1,
    vendor: "Acme Pty Ltd",
    abn: null,
    invoice_no: "INV-1",
    po_reference: null,
    so_reference: null,
    sales_document_type: null,
    cost_centre: null,
    invoice_date: "2026-01-01",
    due_date: null,
    currency: "AUD",
    subtotal: "100",
    gst: "10",
    total: "110",
    status: "processed",
    file_hash: null,
    raw_file_path: null,
    email_sender: null,
    capture_source: null,
    connected_mailbox_id: null,
    storage_vendor_slug: null,
    account_code: null,
    account_name: null,
    route_target: "Sales Management",
    matched_rule_ids: null,
    vendor_confidence: null,
    evaluation_status: null,
    validation_results: null,
    created_at: "2026-01-01T00:00:00Z",
    has_stored_file: false,
    ...overrides,
  }) as Invoice;

const baseSalesRow = (overrides: Partial<SalesOrderApi> = {}): SalesOrderApi => ({
  id: 10,
  so_number: "SO-100",
  customer: "Acme Pty Ltd",
  so_date: "2026-01-01",
  item: "Widget",
  requestor: "Sales",
  so_qty: 5,
  so_unit_price: 20,
  dn_qty: 5,
  dn_date: "2026-01-02",
  dn_shipper: "Courier",
  dn_condition: "Good",
  invoice_id: 99,
  invoice_no: "INV-99",
  invoice_qty: 5,
  invoice_unit_price: 20,
  gst_rate: 0.1,
  variance_approved: false,
  status: "open",
  match: {
    status: "3-Way Match",
    qty_variance_value: 0,
    price_variance_value: 0,
    total_deviation: 0,
    po_value: 100,
    invoice_value: 100,
    invoice_gst: 10,
    invoice_total: 110,
  },
  ...overrides,
});

describe("salesRegisterQueue", () => {
  it("builds coverage from sales register rows", () => {
    const coverage = buildSalesRegisterCoverage([
      baseSalesRow({ invoice_id: 99, so_document_id: 50, dn_document_id: 51 }),
    ]);
    expect(coverage.invoiceIds.has(99)).toBe(true);
    expect(coverage.soDocumentIds.has(50)).toBe(true);
    expect(coverage.dnDocumentIds.has(51)).toBe(true);
    expect(coverage.soNumbers.has("SO-100")).toBe(true);
  });

  it("flags commercial invoice missing from register", () => {
    const coverage = buildSalesRegisterCoverage([]);
    const inv = baseInvoice({ id: 42, so_reference: "SO-100" });
    expect(salesInvoiceNeedsAction(inv, coverage)).toBe(true);
    expect(salesActionIssue(inv, coverage)).toContain("SO-100");
  });

  it("flags awaiting SO invoices for action", () => {
    const coverage = buildSalesRegisterCoverage([]);
    const inv = baseInvoice({ id: 7, evaluation_status: "awaiting_so", so_reference: "SO-200" });
    expect(salesInvoiceNeedsAction(inv, coverage)).toBe(true);
    expect(salesActionIssue(inv, coverage)).toContain("SO-200");
  });

  it("returns action required routed invoices", () => {
    const routed = [
      baseInvoice({ id: 1, so_reference: "SO-100" }),
      baseInvoice({ id: 2, sales_document_type: "so" }),
    ];
    const rows = [baseSalesRow({ invoice_id: 1 })];
    const action = salesActionRequiredInvoices(routed, rows);
    expect(action.map((i) => i.id)).toEqual([2]);
  });
});
