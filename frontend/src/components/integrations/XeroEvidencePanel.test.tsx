/**
 * @vitest-environment happy-dom
 */
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { XeroEvidencePanel } from "@/components/integrations/XeroEvidencePanel";

vi.mock("@/api/client", () => ({
  api: {
    getXeroMasterTotals: vi.fn(async () => ({
      accounts: 2,
      tax_rates: 1,
      contacts: 3,
      currencies: 1,
    })),
    getXeroAccounts: vi.fn(async () => ({
      total: 1,
      limit: 50,
      offset: 0,
      items: [
        {
          id: 1,
          xero_account_id: "acc-1",
          xero_tenant_id: "org-1",
          code: "200",
          name: "Sales",
          account_type: "REVENUE",
          status: "ACTIVE",
          sync_status: "active",
          last_synced_at: "2026-07-01T00:00:00Z",
          created_at: "2026-07-01T00:00:00Z",
          source_system: "xero",
          source_label: "Source: Xero",
          external_id: "acc-1",
          imported_at: "2026-07-01T00:00:00Z",
        },
      ],
    })),
    getXeroTaxRates: vi.fn(async () => ({ total: 0, limit: 50, offset: 0, items: [] })),
    getXeroContactsList: vi.fn(async () => ({ total: 0, limit: 50, offset: 0, items: [] })),
    listVendors: vi.fn(async () => []),
    getChartOfAccounts: vi.fn(async () => ({ accounts: [] })),
    getXeroReferenceContacts: vi.fn(async () => ({ total: 0, limit: 200, offset: 0, items: [] })),
    getXeroReferenceAccounts: vi.fn(async () => ({ total: 0, limit: 200, offset: 0, items: [] })),
    getXeroReferenceTaxRates: vi.fn(async () => ({ total: 0, limit: 200, offset: 0, items: [] })),
    getXeroReferenceTrackingCategories: vi.fn(async () => ({ total: 0, items: [] })),
    getXeroMappings: vi.fn(async () => ({
      items: [{ mapping_type: "gl_account", source_key: "400", external_code: "400" }],
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
            { field: "supplier", code: "contact_not_mapped", message: "supplier has no Xero contact" },
          ],
        },
      ],
    })),
    getXeroExportLedger: vi.fn(async () => ({
      total: 1,
      items: [
        {
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
      ],
    })),
    getXeroSyncHistory: vi.fn(async () => ({ total: 0, limit: 50, offset: 0, items: [] })),
    getXeroExportHistory: vi.fn(async () => ({ total: 0, limit: 50, offset: 0, items: [] })),
    putXeroMappings: vi.fn(async () => ({ items: [] })),
    exportXeroInvoice: vi.fn(async () => ({ evidence: {} })),
    refreshXeroExport: vi.fn(async () => ({ evidence: {}, divergence_flags: [] })),
    retryXeroAttachment: vi.fn(async () => ({ evidence: {} })),
    runXeroReconciliation: vi.fn(async () => ({ checked: 0, divergences: [] })),
    reconcileXero: vi.fn(async () => ({ job_id: 1, reconciled: 0, failed: 0, committed: true })),
  },
}));

vi.mock("@/lib/tenantSession", () => ({
  captureTenantFetchScope: () => ({ tenantId: "t1", token: "tok" }),
  isTenantFetchScopeCurrent: () => true,
}));

vi.mock("@/hooks/useResetOnTenantChange", () => ({
  useResetOnTenantChange: () => undefined,
}));

function wrap(ui: React.ReactElement) {
  return render(<MemoryRouter>{ui}</MemoryRouter>);
}

describe("XeroEvidencePanel", () => {
  afterEach(() => {
    cleanup();
  });

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("shows stored account totals and provenance badges", async () => {
    wrap(<XeroEvidencePanel enabled />);
    await waitFor(() => {
      expect(screen.getByText("Accounts stored")).toBeTruthy();
    });
    expect(screen.getByText("2")).toBeTruthy();
    screen.getByRole("button", { name: "Accounts" }).click();
    await waitFor(() => {
      expect(screen.getByText("200")).toBeTruthy();
      expect(screen.getByText("Source: Xero")).toBeTruthy();
    });
  });

  it("renders mappings workspace and blocks export with structured errors", async () => {
    wrap(<XeroEvidencePanel enabled />);
    await waitFor(() => screen.getByText("Accounts stored"));
    const panel = screen.getByTestId("xero-evidence-panel");
    within(panel).getByRole("button", { name: "Mappings" }).click();
    await waitFor(() => {
      expect(screen.getByTestId("xero-mappings-panel")).toBeTruthy();
      expect(screen.getByTestId("mapping-tab-suppliers")).toBeTruthy();
      expect(screen.getByTestId("mapping-save")).toBeTruthy();
    });
    within(panel).getByRole("button", { name: "Export queue" }).click();
    await waitFor(() => {
      expect(screen.getByTestId("xero-blocking-errors")).toBeTruthy();
      expect(screen.getByText("supplier has no Xero contact")).toBeTruthy();
      expect(
        (screen.getByTestId("xero-export-action") as HTMLButtonElement).disabled
      ).toBe(true);
    });
    within(panel).getByRole("button", { name: "Export evidence" }).click();
    await waitFor(() => {
      expect(screen.getByTestId("xero-attachment-status").textContent).toMatch(/PDF: success/);
    });
  });
});
