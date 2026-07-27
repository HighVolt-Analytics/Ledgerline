/**
 * @vitest-environment happy-dom
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { JournalExportTab } from "@/components/ledger-link/JournalExportTab";
import type { LedgerLinkExports } from "@/api/types";

const {
  exportXeroInvoice,
  getXeroExportQueue,
  getXeroExportLedger,
  getXeroExportHistory,
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
  getXeroExportLedger: vi.fn(async () => ({
    total: 1,
    items: [
      {
        sync_id: 1,
        source_invoice_id: 10,
        qll_transaction_id: "qll-10",
        status: "SUCCESS",
        external_id: "xero-10",
        external_number: "INV-10",
        external_status: "DRAFT",
        external_total: 50,
        attachment_status: "success",
        attempt_count: 1,
        error_bucket: null,
        error_code: null,
        error_message: null,
        created_at: "2026-07-01T00:00:00Z",
        updated_at: "2026-07-01T00:00:00Z",
      },
    ],
  })),
  getXeroExportHistory: vi.fn(async () => ({
    total: 1,
    items: [
      {
        id: 1,
        invoice_id: 10,
        external_entity_id: "xero-10",
        external_number: "INV-10",
        external_status: "DRAFT",
        sync_direction: "outbound",
        sync_status: "synced",
        reconciliation_status: null,
        last_pushed_at: "2026-07-01T00:00:00Z",
        last_reconciled_at: null,
        amount_due: null,
        amount_paid: null,
        is_fully_paid: null,
        sync_error_message: null,
      },
    ],
  })),
}));

vi.mock("@/api/client", () => ({
  api: {
    getXeroExportQueue,
    getXeroExportLedger,
    getXeroExportHistory,
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

  it("loads Xero export queue and shows Ready/Blocked with blocking errors", async () => {
    wrap(<JournalExportTab exports={sampleExports} currency="AUD" />);

    await waitFor(() => {
      expect(getXeroExportQueue).toHaveBeenCalled();
      expect(screen.getByText(/2 pending invoices/)).toBeTruthy();
      expect(screen.getByText(/1 ready/)).toBeTruthy();
    });

    const queue = screen.getByTestId("xero-export-queue");
    expect(within(queue).getByText("Blocked")).toBeTruthy();
    expect(within(queue).getByText("Ready")).toBeTruthy();
    expect(within(queue).getByText("supplier has no Xero contact")).toBeTruthy();

    const actions = within(queue).getAllByTestId("xero-export-action");
    expect((actions[0] as HTMLButtonElement).disabled).toBe(true);
    expect((actions[1] as HTMLButtonElement).disabled).toBe(false);
  });

  it("exports via exportXeroInvoice and refreshes queue, ledger, and history", async () => {
    wrap(<JournalExportTab exports={sampleExports} currency="AUD" />);
    await waitFor(() => expect(getXeroExportQueue).toHaveBeenCalled());

    const queue = screen.getByTestId("xero-export-queue");
    const actions = within(queue).getAllByTestId("xero-export-action");
    actions[1].click();

    await waitFor(() => {
      expect(exportXeroInvoice).toHaveBeenCalledWith(10);
    });
    await waitFor(() => {
      expect(getXeroExportQueue.mock.calls.length).toBeGreaterThanOrEqual(2);
      expect(getXeroExportLedger.mock.calls.length).toBeGreaterThanOrEqual(2);
      expect(getXeroExportHistory.mock.calls.length).toBeGreaterThanOrEqual(2);
    });
  });

  it("keeps journal preview and CSV download for non-Xero targets", async () => {
    wrap(<JournalExportTab exports={sampleExports} currency="AUD" />);
    await waitFor(() => expect(screen.getByText("INV-1")).toBeTruthy());

    screen.getByTestId("target-MYOB").click();
    await waitFor(() => {
      expect(screen.queryByTestId("journal-xero-export-queue")).toBeNull();
      expect(screen.getByTestId("button-download-csv")).toBeTruthy();
      expect(screen.getByText("INV-1")).toBeTruthy();
    });
  });
});
