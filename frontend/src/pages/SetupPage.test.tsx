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

  it("enables Continue to Stripe Checkout after valid fields and Studio selection", async () => {
    const user = userEvent.setup();

    render(
      <MemoryRouter>
        <SetupPage />
      </MemoryRouter>
    );

    const submitButton = screen.getByTestId("button-create-org") as HTMLButtonElement;
    expect(submitButton.disabled).toBe(true);

    await user.type(screen.getByTestId("input-business-name"), "Typed Business");
    await user.type(screen.getByTestId("input-email"), "typed@example.com");
    await user.type(screen.getByTestId("input-phone"), "91234567");
    await user.type(screen.getByLabelText("Password"), "password123");
    await user.type(screen.getByLabelText("Confirm password"), "password123");
    await user.click(screen.getByTestId("signup-plan-studio"));

    await waitFor(() => {
      expect((screen.getByTestId("button-create-org") as HTMLButtonElement).disabled).toBe(
        false
      );
    });

    expect(submitButton.textContent).toBe("Continue to Stripe Checkout");
    expect(screen.queryByTestId("signup-disabled-reason")).toBeNull();
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
