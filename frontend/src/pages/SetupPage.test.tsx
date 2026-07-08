/**
 * @vitest-environment happy-dom
 */
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { SetupPage } from "@/pages/SetupPage";

vi.mock("@/api/client", () => ({
  api: {
    getPublicBillingPlans: vi.fn().mockResolvedValue({
      country: "SG",
      region: "SG",
      currency_code: "SGD",
      plans: [],
      platform_billing_enabled: true,
    }),
    createSignupCheckout: vi.fn(),
    getSignupCheckoutStatus: vi.fn(),
  },
}));

describe("SetupPage signup form", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    cleanup();
  });

  it("enables Continue to Stripe Checkout on step 2 after valid account details", async () => {
    const user = userEvent.setup();

    render(
      <MemoryRouter>
        <SetupPage />
      </MemoryRouter>
    );

    await user.type(screen.getByTestId("input-business-name"), "Typed Business");
    await user.type(screen.getByTestId("input-email"), "typed@example.com");
    await user.type(screen.getByTestId("input-phone"), "91234567");
    await user.type(screen.getByLabelText("Password"), "password123");
    await user.type(screen.getByLabelText("Confirm password"), "password123");

    const continueButton = screen.getByTestId("button-continue-details") as HTMLButtonElement;
    await waitFor(() => {
      expect(continueButton.disabled).toBe(false);
    });
    await user.click(continueButton);

    const studioButton = await screen.findByTestId("signup-plan-cta-studio");
    await waitFor(() => {
      expect((studioButton as HTMLButtonElement).disabled).toBe(false);
    });

    expect(studioButton.textContent).toBe("Continue to Stripe Checkout");
  });

  it("keeps placeholders separate from field values", () => {
    render(
      <MemoryRouter>
        <SetupPage />
      </MemoryRouter>
    );

    const businessName = screen.getByTestId("input-business-name") as HTMLInputElement;
    const email = screen.getByTestId("input-email") as HTMLInputElement;

    expect(businessName.value).toBe("");
    expect(email.value).toBe("");
    expect(businessName.placeholder).toBe("Enter your business name");
    expect(email.placeholder).toBe("Enter your work email");
  });
});
