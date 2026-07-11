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
      country: "AU",
      region: "AU",
      currency_code: "AUD",
      plans: [],
      platform_billing_enabled: true,
    }),
  },
}));

vi.mock("@/lib/oauthApi", () => ({
  fetchOAuthProviders: vi.fn().mockResolvedValue({ google: true, microsoft: true }),
  startGoogleOAuth: vi.fn(),
  startMicrosoftOAuth: vi.fn(),
}));

vi.mock("@/lib/signupApi", () => ({
  getSignupToken: vi.fn(() => null),
  persistSignupToken: vi.fn(),
  clearSignupToken: vi.fn(),
  fetchSignupSession: vi.fn().mockResolvedValue({
    email: "typed@example.com",
    full_name: "",
    provider: "email",
    status: "organization",
    identity_via_oauth: false,
  }),
  signupRegister: vi.fn(),
  signupVerifyOtp: vi.fn(),
  signupSetOrganization: vi.fn(),
  signupSelectPlan: vi.fn(),
  signupCheckout: vi.fn(),
  signupCompleteFree: vi.fn(),
  signupCompleteStudio: vi.fn(),
}));

describe("SetupPage signup wizard", () => {
  afterEach(() => {
    cleanup();
  });

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("shows identity step with OAuth and email fields first", async () => {
    render(
      <MemoryRouter>
        <SetupPage />
      </MemoryRouter>
    );

    expect(await screen.findByText("Continue with Microsoft")).toBeTruthy();
    expect(screen.getByText("Continue with Google")).toBeTruthy();
    expect(screen.getByTestId("input-email")).toBeTruthy();
    expect(screen.queryByTestId("input-business-name")).toBeNull();
  });

  it("advances to organisation step after email identity", async () => {
    const user = userEvent.setup();
    const { signupRegister, signupVerifyOtp } = await import("@/lib/signupApi");

    vi.mocked(signupRegister).mockResolvedValue({ challenge_token: "challenge" });
    vi.mocked(signupVerifyOtp).mockResolvedValue({ signup_token: "signup-jwt" });

    render(
      <MemoryRouter>
        <SetupPage />
      </MemoryRouter>
    );

    await user.type(screen.getByTestId("input-email"), "typed@example.com");
    await user.type(screen.getByLabelText("Password"), "password123");
    await user.type(screen.getByLabelText("Confirm password"), "password123");
    await user.click(screen.getByTestId("button-continue-identity"));

    await user.type(screen.getByPlaceholderText("6-digit code"), "123456");
    await user.click(screen.getByRole("button", { name: "Verify email" }));

    expect(await screen.findByTestId("input-business-name")).toBeTruthy();
    expect(signupVerifyOtp).toHaveBeenCalled();
  });

  it("enables plan selection after valid organisation details", async () => {
    const user = userEvent.setup();
    const { signupRegister, signupVerifyOtp, signupSetOrganization } = await import(
      "@/lib/signupApi"
    );

    vi.mocked(signupRegister).mockResolvedValue({ challenge_token: "challenge" });
    vi.mocked(signupVerifyOtp).mockResolvedValue({ signup_token: "signup-jwt" });
    vi.mocked(signupSetOrganization).mockResolvedValue({
      email: "typed@example.com",
      full_name: "",
      provider: "email",
      status: "plan",
      identity_via_oauth: false,
    });

    render(
      <MemoryRouter>
        <SetupPage />
      </MemoryRouter>
    );

    await user.type(screen.getByTestId("input-email"), "typed@example.com");
    await user.type(screen.getByLabelText("Password"), "password123");
    await user.type(screen.getByLabelText("Confirm password"), "password123");
    await user.click(screen.getByTestId("button-continue-identity"));
    await user.type(screen.getByPlaceholderText("6-digit code"), "123456");
    await user.click(screen.getByRole("button", { name: "Verify email" }));

    await user.type(await screen.findByTestId("input-business-name"), "Typed Business");
    await user.type(screen.getByTestId("input-phone"), "91234567");
    const continueOrg = screen.getByTestId("button-continue-details") as HTMLButtonElement;
    await waitFor(() => expect(continueOrg.disabled).toBe(false));
    await user.click(continueOrg);

    const studioButton = await screen.findByTestId("signup-plan-cta-studio");
    await waitFor(() => expect((studioButton as HTMLButtonElement).disabled).toBe(false));
    expect(studioButton.textContent).toBe("Continue to Stripe Checkout");
  });
});
