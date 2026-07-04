import { describe, expect, it } from "vitest";

import { lineAccountReason, suggestLineAccount } from "@/lib/lineGlAccount";

const baseInv = { account_name: "Office Supplies" };

const baseLine = { description: "General supplies" };

describe("suggestLineAccount", () => {
  it("maps steel descriptions to Raw Materials", () => {
    expect(
      suggestLineAccount(baseInv, { description: "Steel coil 5mm" }, true),
    ).toBe("Raw Materials");
  });

  it("maps freight descriptions to Freight & Logistics", () => {
    expect(
      suggestLineAccount(baseInv, { description: "Freight charges" }, true),
    ).toBe("Freight & Logistics");
  });

  it("falls back to invoice account_name then Suspense Account", () => {
    expect(suggestLineAccount(baseInv, baseLine, true)).toBe("Office Supplies");
    expect(
      suggestLineAccount(
        { account_name: null },
        { description: "Misc item" },
        true,
      ),
    ).toBe("Suspense Account");
  });

  it("returns reference-document label when posting does not apply", () => {
    expect(suggestLineAccount(baseInv, baseLine, false)).toBe(
      "Not posted — reference document",
    );
  });
});

describe("lineAccountReason", () => {
  it("returns awaiting rule book mapping for suspense", () => {
    expect(lineAccountReason("Suspense Account", "Acme Pty Ltd")).toBe(
      "Awaiting rule book mapping",
    );
  });

  it("returns vendor rule text for Raw Materials", () => {
    expect(lineAccountReason("Raw Materials", "Acme Pty Ltd")).toBe(
      "Raw Materials match: Acme Pty Ltd vendor rule",
    );
  });

  it("returns compliance message for non-posting documents", () => {
    expect(lineAccountReason("Not posted — reference document", null)).toBe(
      "Supporting / compliance document — no ledger entry",
    );
  });
});
