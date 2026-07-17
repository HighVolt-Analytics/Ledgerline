/**
 * @vitest-environment happy-dom
 */
import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import {
  PayPalProviderCard,
  PayProviderSelector,
} from "@/components/payments/PayPalProviderCard";
import type { PaypalReadinessResponse } from "@/api/types";

const readinessState = vi.hoisted(() => ({
  data: null as PaypalReadinessResponse | null,
}));

const balanceState = vi.hoisted(() => ({
  data: {
    available: false,
    reason: "paypal_reporting_access_required",
    balances: [],
  },
}));

const connectMutate = vi.hoisted(() => vi.fn());

vi.mock("@/hooks/usePayPal", () => ({
  usePayPalReadiness: () => ({
    data: readinessState.data,
    isLoading: false,
  }),
  usePayPalBalance: () => ({
    data: balanceState.data,
    isLoading: false,
  }),
  usePayPalTransactions: () => ({
    data: {
      available: false,
      reason: "paypal_reporting_access_required",
      transactions: [],
    },
    isLoading: false,
  }),
  useConnectPayPal: () => ({
    mutateAsync: connectMutate,
    isPending: false,
  }),
  useDisconnectPayPal: () => ({
    mutateAsync: vi.fn(),
    isPending: false,
  }),
  useRefreshPayPalReadiness: () => ({
    mutateAsync: vi.fn(),
    isPending: false,
  }),
}));

describe("PayPalProviderCard", () => {
  afterEach(() => {
    cleanup();
  });

  beforeEach(() => {
    vi.clearAllMocks();
    readinessState.data = {
      configured: true,
      connected: false,
      merchant_id: null,
      display_name: null,
      onboarding_complete: false,
      payments_enabled: false,
      payouts_enabled: false,
      balance_available: false,
      transactions_available: false,
      needs_reauthorization: false,
      last_verified_at: null,
      last_error: null,
    };
    balanceState.data = {
      available: false,
      reason: "paypal_reporting_access_required",
      balances: [],
    };
  });

  it("shows connect button when not connected", () => {
    render(<PayPalProviderCard />);
    expect(screen.getByTestId("button-connect-paypal")).toBeTruthy();
    expect(screen.getByTestId("paypal-not-connected-message")).toBeTruthy();
  });

  it("shows capability message when balance is unavailable", () => {
    readinessState.data = {
      configured: true,
      connected: true,
      merchant_id: "MERCHANT123",
      display_name: "Acme PayPal",
      onboarding_complete: true,
      payments_enabled: true,
      payouts_enabled: true,
      balance_available: false,
      transactions_available: false,
      needs_reauthorization: false,
      last_verified_at: "2026-07-01T00:00:00Z",
      last_error: null,
    };

    render(<PayPalProviderCard />);
    expect(screen.getByTestId("paypal-balance-unavailable").textContent).toMatch(
      /reporting access/i
    );
  });

  it("disables pay when payouts are not enabled", () => {
    readinessState.data = {
      configured: true,
      connected: true,
      merchant_id: "MERCHANT123",
      display_name: "Acme PayPal",
      onboarding_complete: true,
      payments_enabled: true,
      payouts_enabled: false,
      balance_available: false,
      transactions_available: false,
      needs_reauthorization: false,
      last_verified_at: null,
      last_error: null,
    };

    render(<PayPalProviderCard />);
    const capability = screen.getByTestId("button-paypal-pay-capability");
    expect(capability.hasAttribute("disabled")).toBe(true);
    expect(capability.textContent).toMatch(/not enabled/i);

    render(
      <PayProviderSelector
        value="stripe"
        onChange={() => undefined}
        paypalEnabled={false}
        paymentId="42"
      />
    );
    expect(
      screen.getByTestId("button-pay-provider-paypal-42").hasAttribute("disabled")
    ).toBe(true);
  });
});
