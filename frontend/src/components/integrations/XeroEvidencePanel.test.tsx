/**
 * @vitest-environment happy-dom
 */
import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
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
    getXeroSyncHistory: vi.fn(async () => ({ total: 0, limit: 50, offset: 0, items: [] })),
    getXeroExportHistory: vi.fn(async () => ({ total: 0, limit: 50, offset: 0, items: [] })),
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
});
