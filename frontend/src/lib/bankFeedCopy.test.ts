import { describe, expect, it } from "vitest";
import { formatBankImportFlash } from "@/lib/bankFeedCopy";

describe("formatBankImportFlash", () => {
  it("includes auto-categorized count on a successful import", () => {
    expect(
      formatBankImportFlash({
        accepted_count: 17,
        row_count: 17,
        duplicate_count: 0,
        categorized_count: 9,
      })
    ).toBe("Imported 17 of 17 rows · 9 auto-categorized");
  });

  it("keeps a zero categorized count visible", () => {
    expect(
      formatBankImportFlash({
        accepted_count: 3,
        row_count: 3,
        duplicate_count: 1,
        categorized_count: 0,
      })
    ).toBe("Imported 3 of 3 rows · 1 duplicate(s) skipped · 0 auto-categorized");
  });
});
