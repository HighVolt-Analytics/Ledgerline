/**
 * @vitest-environment happy-dom
 */
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "@/api/client";
import { XeroMappingWorkspace } from "@/components/integrations/XeroMappingWorkspace";

vi.mock("@/api/client", () => ({
  api: {
    listVendors: vi.fn(async () => [
      { id: 1, vendor_slug: "acme", vendor_name: "Acme Supplies", sender_pattern: "", abn: null, approved: true },
    ]),
    getChartOfAccounts: vi.fn(async () => ({
      accounts: [{ code: "400", name: "Purchases", type: "Expense" }],
    })),
    getXeroReferenceContacts: vi.fn(async () => ({
      total: 1,
      limit: 200,
      offset: 0,
      items: [
        {
          id: 1,
          xero_contact_id: "contact-1",
          xero_tenant_id: "org-1",
          name: "Acme Supplies",
          email_address: null,
          is_supplier: true,
          is_customer: false,
          mapping_status: "unmapped",
          sync_status: "active",
          last_synced_at: null,
          created_at: null,
          source_system: "xero",
          source_label: "Source: Xero",
          external_id: "contact-1",
          imported_at: null,
        },
      ],
    })),
    getXeroReferenceAccounts: vi.fn(async () => ({
      total: 1,
      limit: 200,
      offset: 0,
      items: [
        {
          id: 1,
          xero_account_id: "acc-400",
          xero_tenant_id: "org-1",
          code: "400",
          name: "Purchases",
          account_type: "EXPENSE",
          status: "ACTIVE",
          sync_status: "active",
          last_synced_at: null,
          created_at: null,
          source_system: "xero",
          source_label: "Source: Xero",
          external_id: "acc-400",
          imported_at: null,
        },
      ],
    })),
    getXeroReferenceTaxRates: vi.fn(async () => ({
      total: 1,
      limit: 200,
      offset: 0,
      items: [
        {
          id: 1,
          tax_type: "INPUT",
          xero_tenant_id: "org-1",
          name: "GST on Expenses",
          status: "ACTIVE",
          effective_rate: 10,
          sync_status: "active",
          last_synced_at: null,
          created_at: null,
          source_system: "xero",
          source_label: "Source: Xero",
          external_id: "INPUT",
          imported_at: null,
        },
      ],
    })),
    getXeroReferenceTrackingCategories: vi.fn(async () => ({
      total: 0,
      items: [],
    })),
    getXeroMappings: vi.fn(async () => ({ items: [] })),
    putXeroMappings: vi.fn(async (mappings) => ({ items: mappings })),
  },
}));

vi.mock("@/lib/tenantSession", () => ({
  captureTenantFetchScope: () => ({ tenantId: "t1", token: "tok" }),
  isTenantFetchScopeCurrent: () => true,
}));

vi.mock("@/hooks/useResetOnTenantChange", () => ({
  useResetOnTenantChange: () => undefined,
}));

describe("XeroMappingWorkspace", () => {
  afterEach(() => {
    cleanup();
  });

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("highlights unmapped LedgerLink values", async () => {
    render(<XeroMappingWorkspace enabled onMappingsSaved={vi.fn()} />);
    await waitFor(() => {
      expect(screen.getByTestId("xero-mappings-panel")).toBeTruthy();
    });
    fireEvent.click(screen.getByTestId("mapping-tab-gl_accounts"));
    await waitFor(() => {
      expect(screen.getByTestId("mapping-unmapped-400")).toBeTruthy();
      expect(screen.getByTestId("mapping-unmapped-count").textContent).toMatch(/unmapped/);
    });
  });

  it("auto-maps exact GL code to Xero AccountCode", async () => {
    render(<XeroMappingWorkspace enabled onMappingsSaved={vi.fn()} />);
    await waitFor(() => screen.getByTestId("xero-mappings-panel"));
    fireEvent.click(screen.getByTestId("mapping-tab-gl_accounts"));
    await waitFor(() => screen.getByTestId("mapping-select-gl-400"));
    fireEvent.click(screen.getByTestId("mapping-auto-map"));
    await waitFor(() => {
      const select = screen.getByTestId("mapping-select-gl-400") as HTMLSelectElement;
      expect(select.value).toBe("400");
      expect(screen.queryByTestId("mapping-unmapped-400")).toBeNull();
    });
  });

  it("saves mappings via PUT and refreshes via onMappingsSaved", async () => {
    const onMappingsSaved = vi.fn(async () => undefined);
    render(<XeroMappingWorkspace enabled onMappingsSaved={onMappingsSaved} />);
    await waitFor(() => screen.getByTestId("xero-mappings-panel"));
    fireEvent.click(screen.getByTestId("mapping-tab-gl_accounts"));
    await waitFor(() => screen.getByTestId("mapping-select-gl-400"));
    fireEvent.click(screen.getByTestId("mapping-auto-map"));
    fireEvent.click(screen.getByTestId("mapping-save"));
    await waitFor(() => {
      expect(api.putXeroMappings).toHaveBeenCalled();
      expect(onMappingsSaved).toHaveBeenCalled();
    });
    const payload = vi.mocked(api.putXeroMappings).mock.calls[0][0];
    expect(payload).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          mapping_type: "gl_account",
          source_key: "400",
          external_code: "400",
        }),
      ])
    );
  });
});
