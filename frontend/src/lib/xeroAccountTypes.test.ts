import { describe, expect, it } from "vitest";

import { defaultXeroSubtype, normalizeXeroSubtype } from "@/lib/xeroAccountTypes";

describe("xeroAccountTypes", () => {
  it("defaults a subtype for each LedgerLink type", () => {
    expect(defaultXeroSubtype("Asset")).toBe("CURRENT");
    expect(defaultXeroSubtype("Expense")).toBe("EXPENSE");
  });

  it("keeps a valid subtype and replaces one that does not belong", () => {
    expect(normalizeXeroSubtype("Revenue", "OTHERINCOME")).toBe("OTHERINCOME");
    expect(normalizeXeroSubtype("Asset", "EXPENSE")).toBe("CURRENT");
  });
});
