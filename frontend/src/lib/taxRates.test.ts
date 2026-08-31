import { describe, expect, it } from "vitest";

import { formatTaxPercent, parseTaxRateInput, TAX_RATE_TYPE_OPTIONS, totalTaxRate } from "@/lib/taxRates";

describe("taxRates", () => {
  it("exposes the Xero AU Activity Statement type labels", () => {
    expect(TAX_RATE_TYPE_OPTIONS.map((o) => o.label)).toEqual([
      "Sales",
      "Purchases",
      "GST Free Sales",
      "Exempt Income",
      "BAS Excluded",
      "GST Free Expenses",
    ]);
  });

  it("sums component rates for the total line", () => {
    expect(totalTaxRate([{ rate: 10 }, { rate: 2.25 }])).toBe(12.25);
    expect(formatTaxPercent(0)).toBe("0.00 %");
    expect(parseTaxRateInput("")).toBeNull();
    expect(parseTaxRateInput("10")).toBe(10);
  });
});
