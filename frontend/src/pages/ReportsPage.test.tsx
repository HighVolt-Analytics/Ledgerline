/**
 * @vitest-environment happy-dom
 */
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ReportsPage } from "@/pages/ReportsPage";
import type { ReportCatalogResponse, ReportPreview } from "@/api/types";

const TENANT = "tenant-a";

const {
  getReportCatalog,
  putReportFavourites,
  getReportPreview,
  exportReport,
  listReportLayouts,
} = vi.hoisted(() => ({
  getReportCatalog: vi.fn(),
  putReportFavourites: vi.fn(),
  getReportPreview: vi.fn(),
  exportReport: vi.fn(),
  listReportLayouts: vi.fn(),
}));

vi.mock("@/api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/client")>();
  return {
    ...actual,
    getActiveTenantId: () => TENANT,
    api: {
      ...actual.api,
      getReportCatalog,
      putReportFavourites,
      getReportPreview,
      exportReport,
      listReportLayouts,
    },
  };
});

vi.mock("@/context/AuthContext", () => ({
  useAuth: () => ({
    user: {
      id: 1,
      email: "admin@example.com",
      full_name: "Admin",
      role: "admin",
      tenant_id: TENANT,
      tenant_name: "Tenant A",
      tenant_slug: "tenant-a",
      tenant_timezone: "UTC",
      tenant_locale: "en-AU",
    },
  }),
}));

vi.mock("@/context/ToastContext", () => ({
  useToast: () => ({ toast: vi.fn() }),
}));

const CATALOG: ReportCatalogResponse = {
  favourite_ids: [],
  reports: [
    {
      id: "invoice-register",
      name: "Invoice Register",
      description: "The source of truth for payables as of the period end. Vendor Spend, AP Aging and Payment Schedule read from here. Custom range still filters by invoice date.",
      category: "transactions",
      supports_compare: false,
    },
    {
      id: "cash-forecast",
      name: "Cash Forecast",
      description: "AP amounts due by date. Employee reimbursements are not included yet.",
      category: "transactions",
      supports_compare: false,
    },
    {
      id: "aged-payables",
      name: "Aged Payables",
      description: "Outstanding vendor balances bucketed by due date.",
      category: "payables_receivables",
      supports_compare: false,
    },
  ],
};

const PREVIEW: ReportPreview = {
  report_id: "invoice-register",
  title: "Invoice Register",
  period_label: "2026-08-01 – 2026-08-31",
  currency: "AUD",
  columns: ["Vendor", "Total"],
  rows: [{ cells: ["Acme Co", "500.00"] }],
  empty: false,
  notes: "Employee reimbursements are not included yet.",
};

function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <ReportsPage />
    </QueryClientProvider>
  );
}

describe("ReportsPage catalog", () => {
  afterEach(() => {
    cleanup();
  });

  beforeEach(() => {
    vi.clearAllMocks();
    getReportCatalog.mockResolvedValue(CATALOG);
    putReportFavourites.mockResolvedValue(["invoice-register"]);
    getReportPreview.mockResolvedValue(PREVIEW);
    listReportLayouts.mockResolvedValue([]);
    exportReport.mockResolvedValue({ filename: "invoice_register.xlsx" });
  });

  it("filters the catalog by search", async () => {
    const user = userEvent.setup();
    renderPage();

    expect(await screen.findByText("Invoice Register")).toBeTruthy();
    expect(screen.getByText("Cash Forecast")).toBeTruthy();

    await user.type(screen.getByTestId("input-report-search"), "cash");

    expect(screen.queryByText("Invoice Register")).toBeNull();
    expect(screen.getByText("Cash Forecast")).toBeTruthy();
  });

  it("filters by category tab", async () => {
    const user = userEvent.setup();
    renderPage();
    expect(await screen.findByText("Invoice Register")).toBeTruthy();

    await user.click(screen.getByTestId("tab-reports-payables_receivables"));

    expect(screen.queryByText("Invoice Register")).toBeNull();
    expect(screen.getByText("Aged Payables")).toBeTruthy();
  });

  it("stars a report through PUT /favourites", async () => {
    const user = userEvent.setup();
    renderPage();
    expect(await screen.findByText("Invoice Register")).toBeTruthy();

    await user.click(screen.getByTestId("button-favourite-invoice-register"));

    await waitFor(() => {
      expect(putReportFavourites).toHaveBeenCalledWith(["invoice-register"]);
    });
  });

  it("exports the selected report with range params", async () => {
    const user = userEvent.setup();
    renderPage();
    expect(await screen.findByText("Invoice Register")).toBeTruthy();

    await user.click(screen.getByTestId("button-preview-invoice-register"));
    expect(await screen.findByText("Acme Co")).toBeTruthy();
    expect(screen.getByText("Employee reimbursements are not included yet.")).toBeTruthy();

    await user.click(screen.getByTestId("button-export-invoice-register"));

    await waitFor(() => {
      expect(exportReport).toHaveBeenCalledWith("invoice-register", {
        format: "xlsx",
        range: "month",
        compare: false,
        from: undefined,
        to: undefined,
        layout_id: undefined,
      });
    });
  });

  it("renders the empty preview state", async () => {
    getReportPreview.mockResolvedValue({ ...PREVIEW, empty: true, rows: [] });
    const user = userEvent.setup();
    renderPage();
    expect(await screen.findByText("Invoice Register")).toBeTruthy();

    await user.click(screen.getByTestId("button-preview-invoice-register"));

    expect(await screen.findByText("No data for this period")).toBeTruthy();
  });

  it("blocks custom range export when from is after to", async () => {
    const user = userEvent.setup();
    renderPage();
    expect(await screen.findByText("Invoice Register")).toBeTruthy();

    await user.click(screen.getByTestId("button-preview-invoice-register"));
    await user.click(screen.getByTestId("range-invoice-register-custom"));
    await user.type(screen.getByTestId("preview-from-invoice-register"), "2026-08-20");
    await user.type(screen.getByTestId("preview-to-invoice-register"), "2026-08-01");

    expect(await screen.findByTestId("preview-invalid-range-invoice-register")).toBeTruthy();
    expect(
      (screen.getByTestId("button-export-invoice-register") as HTMLButtonElement).disabled
    ).toBe(true);
    expect(
      getReportPreview.mock.calls.some(
        (call) => call[1]?.from === "2026-08-20" && call[1]?.to === "2026-08-01"
      )
    ).toBe(false);
  });

  it("auto-applies the default layout and can switch back to catalog columns", async () => {
    listReportLayouts.mockResolvedValue([
      {
        id: 7,
        report_id: "invoice-register",
        name: "Amount only",
        column_config: { columns: ["Total"] },
        is_default: true,
      },
    ]);
    const user = userEvent.setup();
    renderPage();
    expect(await screen.findByText("Invoice Register")).toBeTruthy();
    await user.click(screen.getByTestId("button-preview-invoice-register"));

    expect(await screen.findByText("500.00")).toBeTruthy();
    expect(screen.queryByRole("columnheader", { name: "Vendor" })).toBeNull();
    expect(screen.queryByText("Acme Co")).toBeNull();

    await user.click(screen.getByTestId("button-columns-invoice-register"));
    await user.click(screen.getByTestId("select-layout-invoice-register"));
    await user.click(await screen.findByText("Catalog default"));

    expect(await screen.findByRole("columnheader", { name: "Vendor" })).toBeTruthy();
    expect(screen.getByText("Acme Co")).toBeTruthy();
  });

  it("keeps the active layout when the date range changes", async () => {
    listReportLayouts.mockResolvedValue([
      {
        id: 7,
        report_id: "invoice-register",
        name: "Amount only",
        column_config: { columns: ["Total", "Removed Column"] },
        is_default: true,
      },
    ]);
    const user = userEvent.setup();
    renderPage();
    expect(await screen.findByText("Invoice Register")).toBeTruthy();
    await user.click(screen.getByTestId("button-preview-invoice-register"));

    expect(await screen.findByText("500.00")).toBeTruthy();
    expect(screen.queryByRole("columnheader", { name: "Vendor" })).toBeNull();

    await user.click(screen.getByTestId("range-invoice-register-quarter"));
    expect(await screen.findByText("500.00")).toBeTruthy();
    expect(screen.queryByRole("columnheader", { name: "Vendor" })).toBeNull();
    expect(screen.queryByText("Removed Column")).toBeNull();

    await user.click(screen.getByTestId("button-export-invoice-register"));
    await waitFor(() => {
      expect(exportReport).toHaveBeenCalledWith("invoice-register", {
        format: "xlsx",
        range: "quarter",
        compare: false,
        from: undefined,
        to: undefined,
        layout_id: 7,
      });
    });
  });
});
