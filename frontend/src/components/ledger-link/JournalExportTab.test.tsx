/**
 * @vitest-environment happy-dom
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { JournalExportTab } from "@/components/ledger-link/JournalExportTab";
import type { LedgerLinkExports } from "@/api/types";

const {
  exportXeroInvoice,
  getXeroExportQueue,
  getXeroReadiness,
} = vi.hoisted(() => ({
  exportXeroInvoice: vi.fn(async () => ({
    evidence: {
      sync_id: 1,
      source_invoice_id: 9,
      qll_transaction_id: "qll-1",
      status: "SUCCESS",
      external_id: "xero-1",
      external_number: "INV-9",
      external_status: "DRAFT",
      external_total: 110,
      attachment_status: "success",
      attempt_count: 1,
      error_bucket: null,
      error_code: null,
      error_message: null,
      created_at: "2026-07-01T00:00:00Z",
      updated_at: "2026-07-01T00:00:00Z",
    },
  })),
  getXeroExportQueue: vi.fn(async () => ({
    items: [
      {
        invoice_id: 9,
        invoice_no: "INV-9",
        vendor: "Acme",
        total: 110,
        currency: "AUD",
        valid: false,
        blocking_errors: [
          {
            field: "supplier",
            code: "contact_not_mapped",
            message: "supplier has no Xero contact",
          },
        ],
      },
      {
        invoice_id: 10,
        invoice_no: "INV-10",
        vendor: "Beta",
        total: 50,
        currency: "AUD",
        valid: true,
        blocking_errors: [],
      },
    ],
  })),
  getXeroReadiness: vi.fn(async () => ({
    configured: true,
    connected: false,
    ready: false,
    status: "disconnected",
    organisation_selected: false,
    provider_tenant_id: null,
    display_name: null,
    connection_count: 0,
    last_error: null,
  })),
}));

vi.mock("@/api/client", () => ({
  api: {
    getXeroExportQueue,
    getXeroReadiness,
    exportXeroInvoice,
  },
}));

vi.mock("@/lib/tenantSession", () => ({
  captureTenantFetchScope: () => ({ tenantId: "t1", token: "tok" }),
  isTenantFetchScopeCurrent: () => true,
}));

vi.mock("@/hooks/useResetOnTenantChange", () => ({
  useResetOnTenantChange: () => undefined,
}));

const sampleExports: LedgerLinkExports = {
  invoices: [
    {
      id: "inv-1",
      doc: "INV-1",
      date: "2026-01-01",
      party: "Acme",
      debit: "Expense",
      credit: "AP",
      amount: 100,
      status: "Pending Export",
    },
  ],
  bills: [],
  expenses: [],
  purchases: [],
  payments: [],
};

function wrap(ui: React.ReactElement) {
  return render(<MemoryRouter>{ui}</MemoryRouter>);
}

describe("JournalExportTab", () => {
  afterEach(() => {
    cleanup();
  });

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("loads Xero queue counts and shows the not-ready error line", async () => {
    wrap(<JournalExportTab exports={sampleExports} currency="AUD" />);

    await waitFor(() => {
      expect(getXeroExportQueue).toHaveBeenCalled();
      expect(screen.getByText(/2 pending invoices/)).toBeTruthy();
      expect(screen.getByText(/1 ready/)).toBeTruthy();
    });

    expect(screen.getByTestId("journal-export-error").textContent).toMatch(
      /Xero integration is not ready/
    );
    expect(screen.queryByTestId("xero-export-queue")).toBeNull();
    expect(screen.queryByTestId("journal-xero-export-ledger")).toBeNull();
    expect(screen.queryByTestId("journal-xero-export-history")).toBeNull();
  });

  it("exports ready invoices via Export ready to Xero", async () => {
    wrap(<JournalExportTab exports={sampleExports} currency="AUD" />);
    await waitFor(() => expect(getXeroExportQueue).toHaveBeenCalled());

    screen.getByTestId("button-export-xero").click();

    await waitFor(() => {
      expect(exportXeroInvoice).toHaveBeenCalledWith(10);
    });
    await waitFor(() => {
      expect(getXeroExportQueue.mock.calls.length).toBeGreaterThanOrEqual(2);
    });
  });

  it("shows the connected Xero target and CSV download with the journal preview", async () => {
    wrap(<JournalExportTab exports={sampleExports} currency="AUD" />);
    await waitFor(() => expect(screen.getByText("INV-1")).toBeTruthy());

    expect(screen.getByTestId("target-Xero")).toBeTruthy();
    expect(screen.queryByTestId("target-MYOB")).toBeNull();
    expect(screen.getByTestId("button-download-csv")).toBeTruthy();
    expect(screen.getByTestId("button-refresh-queue")).toBeTruthy();
    expect(screen.getByTestId("button-export-xero")).toBeTruthy();
    expect(screen.getByText("Journal export preview")).toBeTruthy();
  });
});
