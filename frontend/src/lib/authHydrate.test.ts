import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, api } from "@/api/client";
import { hydrateUserAndMemberships } from "@/lib/authHydrate";

vi.mock("@/api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/client")>();
  return {
    ...actual,
    api: {
      ...actual.api,
      me: vi.fn(),
    },
  };
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("hydrateUserAndMemberships", () => {
  it("does not keep a JWT-only user when /me returns 401", async () => {
    vi.mocked(api.me).mockRejectedValue(new ApiError("Invalid or expired token", 401));

    await expect(
      hydrateUserAndMemberships({
        access: "hdr.eyJzdWIiOiIxIn0.sig",
        fallbackToTokenOnMeFailure: true,
      })
    ).rejects.toMatchObject({ status: 401 });
  });
});
