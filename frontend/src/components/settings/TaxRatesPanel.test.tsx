/**
 * @vitest-environment happy-dom
 */
import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { TaxRatesPayload } from "@/api/types";
import { TaxRatesPanel } from "@/components/settings/TaxRatesPanel";

const toast = vi.fn();

vi.mock("@/context/ToastContext", () => ({
  useToast: () => ({ toast }),
}));

const useTaxRates = vi.fn();
const useCreateTaxRate = vi.fn(() => ({ isPending: false, mutateAsync: vi.fn() }));
const useUpdateTaxRate = vi.fn(() => ({ isPending: false, mutateAsync: vi.fn() }));
const useDeleteTaxRate = vi.fn(() => ({ isPending: false, mutateAsync: vi.fn() }));
const useSyncTaxRates = vi.fn(() => ({ isPending: false, mutateAsync: vi.fn() }));

vi.mock("@/hooks/useTaxRates", () => ({
  useTaxRates: (...args: unknown[]) => useTaxRates(...args),
  useCreateTaxRate: () => useCreateTaxRate(),
  useUpdateTaxRate: () => useUpdateTaxRate(),
  useDeleteTaxRate: () => useDeleteTaxRate(),
  useSyncTaxRates: () => useSyncTaxRates(),
}));

function renderPanel() {
  return render(
    <MemoryRouter>
      <TaxRatesPanel canEdit />
    </MemoryRouter>
  );
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("TaxRatesPanel", () => {
  it("asks to connect a bill processing platform when none is linked", () => {
    useTaxRates.mockReturnValue({
      data: { tax_rates: [], source: "none", xero_connected: false } satisfies TaxRatesPayload,
      isLoading: false,
      isError: false,
      blocked: false,
    });
    renderPanel();
    expect(screen.getByText(/Connect a bill processing platform to view tax rates/)).toBeTruthy();
    expect(screen.queryByTestId("button-sync-tax-rates")).toBeNull();
  });

  it("shows the Xero connection chip beside sync when Xero is ready", () => {
    useTaxRates.mockReturnValue({
      data: {
        tax_rates: [],
        source: "xero",
        xero_connected: true,
        provider: {
          id: "xero",
          name: "Xero",
          organisation_name: "Demo Org",
          connected: true,
        },
      } satisfies TaxRatesPayload,
      isLoading: false,
      isError: false,
      blocked: false,
    });
    renderPanel();
    expect(screen.getByTestId("button-sync-tax-rates")).toBeTruthy();
    expect(screen.getByText("Demo Org")).toBeTruthy();
    expect(screen.getByText("Connected")).toBeTruthy();
  });

  it("shows QuickBooks tax codes as a read-only synced table", () => {
    useTaxRates.mockReturnValue({
      data: {
        tax_rates: [
          {
            id: "11",
            display_name: "GST on Purchases",
            tax_type: "PURCHASES",
            components: [{ name: "GST", rate: 10 }],
            total_rate: 10,
            can_delete: false,
            can_edit: false,
            source: "quickbooks_online",
          },
        ],
        source: "quickbooks_online",
        provider: {
          id: "quickbooks_online",
          name: "QuickBooks",
          organisation_name: "Sandbox Co",
          connected: true,
        },
      } satisfies TaxRatesPayload,
      isLoading: false,
      isError: false,
      blocked: false,
    });
    renderPanel();
    expect(screen.getByTestId("button-sync-tax-rates")).toBeTruthy();
    expect(screen.getByText("GST on Purchases")).toBeTruthy();
    expect(screen.getByText("Sandbox Co")).toBeTruthy();
    expect(screen.queryByTestId("button-add-tax-rate")).toBeTruthy();
    expect(screen.queryByTestId("button-edit-tax-rate-11")).toBeNull();
  });
});
