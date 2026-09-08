/**
 * @vitest-environment happy-dom
 */
import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { PulledContactsPanel } from "@/components/contacts/PulledContactsPanel";

const toast = vi.fn();

vi.mock("@/context/ToastContext", () => ({
  useToast: () => ({ toast }),
}));

const usePulledXeroContacts = vi.fn();
const useSyncPulledXeroContacts = vi.fn(() => ({ isPending: false, mutateAsync: vi.fn() }));
const useCreatePulledXeroContact = vi.fn(() => ({ isPending: false, mutateAsync: vi.fn() }));

vi.mock("@/hooks/usePulledXeroContacts", () => ({
  usePulledXeroContacts: (...args: unknown[]) => usePulledXeroContacts(...args),
  useSyncPulledXeroContacts: () => useSyncPulledXeroContacts(),
  useCreatePulledXeroContact: () => useCreatePulledXeroContact(),
}));

function renderPanel() {
  return render(
    <MemoryRouter>
      <PulledContactsPanel canEdit />
    </MemoryRouter>
  );
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("PulledContactsPanel", () => {
  it("asks to connect Xero when not connected", () => {
    usePulledXeroContacts.mockReturnValue({
      xeroConnected: false,
      qboConnected: false,
      connectedProvider: null,
      loading: false,
      status: { xero: { status: "disconnected", display_name: null } },
      contacts: [],
      contactsLoading: false,
      contactsError: false,
    });
    renderPanel();
    expect(screen.getByTestId("pulled-contacts-connect-note")).toBeTruthy();
    expect(screen.queryByTestId("button-sync-pulled-contacts")).toBeNull();
  });

  it("shows sync and pulled names when Xero is connected", () => {
    usePulledXeroContacts.mockReturnValue({
      xeroConnected: true,
      qboConnected: false,
      connectedProvider: "xero",
      loading: false,
      status: { xero: { status: "connected", display_name: "Demo Org" } },
      contacts: [
        {
          xero_contact_id: "c-1",
          name: "Acme Supplies",
          is_supplier: true,
          is_customer: false,
        },
      ],
      contactsLoading: false,
      contactsError: false,
    });
    renderPanel();
    expect(screen.getByTestId("button-sync-pulled-contacts")).toBeTruthy();
    expect(screen.getByText("Acme Supplies")).toBeTruthy();
    expect(screen.getByTestId("button-add-pulled-contact")).toBeTruthy();
  });

  it("shows QuickBooks pulled names when QuickBooks is connected", () => {
    usePulledXeroContacts.mockReturnValue({
      xeroConnected: false,
      qboConnected: true,
      connectedProvider: "quickbooks",
      loading: false,
      status: {
        xero: { status: "disconnected", display_name: null },
        quickbooks_online: { status: "connected", display_name: "Sandbox Co" },
      },
      contacts: [
        {
          xero_contact_id: "vendor:56",
          qbo_entity_id: "56",
          name: "QBO Vendor",
          is_supplier: true,
          is_customer: false,
        },
      ],
      contactsLoading: false,
      contactsError: false,
    });
    renderPanel();
    expect(screen.getByText("QBO Vendor")).toBeTruthy();
    expect(screen.getByText("Vendor")).toBeTruthy();
    expect(screen.getByTestId("button-sync-pulled-contacts")).toBeTruthy();
  });
});
