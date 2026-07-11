/**
 * @vitest-environment happy-dom
 */
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { IntegrationsPage } from "@/pages/IntegrationsPage";

const mockReloadAll = vi.fn();
const mockSelectXeroOrg = vi.fn();
const mockSyncXeroSettings = vi.fn();
const mockSyncXeroContacts = vi.fn();

vi.mock("@/context/AuthContext", () => ({
  useAuth: () => ({
    user: {
      id: 1,
      email: "admin@example.com",
      full_name: "Admin",
      role: "admin",
      tenant_id: "tenant-a",
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

vi.mock("@/hooks/useStripe", () => ({
  useStripeAccount: () => ({ data: null, isLoading: false }),
  useStripeReadiness: () => ({ data: null, isLoading: false }),
}));

vi.mock("@/hooks/useAccountingIntegrations", () => ({
  useAccountingIntegrations: () => ({
    status: {
      xero: {
        provider: "xero",
        configured: true,
        status: "organisation_selection_required",
        display_name: null,
        provider_tenant_id: null,
        scopes: null,
        connected_at: null,
        last_error: null,
      },
      quickbooks_online: {
        provider: "quickbooks_online",
        configured: false,
        status: "disconnected",
        display_name: null,
        provider_tenant_id: null,
        scopes: null,
        connected_at: null,
        last_error: null,
      },
    },
    xeroReadiness: {
      configured: true,
      connected: true,
      ready: false,
      status: "organisation_selection_required",
      organisation_selected: false,
      provider_tenant_id: null,
      display_name: null,
      connection_count: 2,
      last_error: null,
    },
    xeroConnections: [
      {
        id: 1,
        xero_connection_id: "conn-1",
        xero_tenant_id: "tenant-1",
        xero_tenant_type: "ORGANISATION",
        xero_tenant_name: "Demo Company AU",
        selected: false,
      },
      {
        id: 2,
        xero_connection_id: "conn-2",
        xero_tenant_id: "tenant-2",
        xero_tenant_type: "ORGANISATION",
        xero_tenant_name: "Demo Company NZ",
        selected: false,
      },
    ],
    loading: false,
    xeroLoading: false,
    error: null,
    xeroError: null,
    reload: mockReloadAll,
    reloadXero: mockReloadAll,
    reloadAll: mockReloadAll,
    selectXeroOrg: mockSelectXeroOrg,
    syncXeroSettings: mockSyncXeroSettings,
    syncXeroContacts: mockSyncXeroContacts,
  }),
}));

vi.mock("@/api/client", () => ({
  getActiveTenantId: () => "tenant-a",
  api: {
    getSettings: vi.fn().mockResolvedValue({
      graph_mailbox: "",
      graph_enabled: false,
      graph_poll_interval_minutes: 15,
      graph_folder_moves_enabled: false,
      graph_processed_folder: "",
      graph_exceptions_folder: "",
      blob_enabled: false,
      azure_storage_container: "",
      azure_di_enabled: false,
      gemini_vision_available: false,
      azure_foundry_vision_available: false,
      default_document_ai_provider: "azure_di",
      azure_postgres_enabled: false,
      azure_redis_enabled: false,
      appinsights_enabled: false,
      azure_location: "",
      azure_webapp_url: "",
      abn_validation_mode: "off",
      rule_book_config_path: "",
      cors_origins: "",
      whatsapp_configured: false,
      app_env: "development",
      payment_environment_label: "Sandbox",
      stripe_mode: "sandbox",
      xero_configured: true,
      quickbooks_configured: false,
      stripe_global_payouts_access_status: "not_requested",
      stripe_payments_execution_enabled: false,
      stripe_live_payments_enabled: false,
      payment_manual_execution_enabled: true,
      payment_manual_execution_limit_usd: 1000,
      payment_execution_disabled: false,
    }),
    listMailboxes: vi.fn().mockResolvedValue([]),
    listMailboxConnectionRequests: vi.fn().mockResolvedValue([]),
    getWhatsappStatus: vi.fn().mockResolvedValue({
      configured: false,
      webhook_callback_url: "",
      oauth_callback_url: "",
      connections: [],
    }),
    getViberStatus: vi.fn().mockResolvedValue({
      configured: false,
      webhook_callback_url: "",
      webhook_reachable: false,
      connections: [],
    }),
    getMailboxAdminConsentUrl: vi.fn().mockResolvedValue({
      admin_consent_url: "https://example.com/consent",
      instructions: "Grant consent",
    }),
    connectXero: vi.fn(),
    disconnectAccountingIntegration: vi.fn(),
  },
}));

describe("IntegrationsPage Xero org picker", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    cleanup();
  });

  it("shows organisation picker when OAuth returns select_org", async () => {
    render(
      <MemoryRouter initialEntries={["/integrations?xero=select_org"]}>
        <IntegrationsPage />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(screen.getByTestId("xero-org-picker")).toBeTruthy();
    });

    expect(screen.getByText("Demo Company AU")).toBeTruthy();
    expect(screen.getByText("Demo Company NZ")).toBeTruthy();
    expect(mockReloadAll).toHaveBeenCalledWith(true);
  });
});
