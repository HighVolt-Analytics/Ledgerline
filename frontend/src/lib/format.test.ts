import { describe, expect, it } from "vitest";
import {
  currencySymbol,
  formatMoneyByCurrencyMap,
  money,
  normalizeCurrencyCode,
} from "@/lib/format";

describe("currencySymbol", () => {
  it("returns disambiguating symbols for dollar-family currencies", () => {
    expect(currencySymbol("AUD")).toBe("A$");
    expect(currencySymbol("SGD")).toBe("S$");
    expect(currencySymbol("USD")).toBe("US$");
    expect(currencySymbol("NZD")).toBe("NZ$");
  });

  it("returns non-dollar symbols and uppercases codes", () => {
    expect(currencySymbol("GBP")).toBe("£");
    expect(currencySymbol("EUR")).toBe("€");
    expect(currencySymbol("aud")).toBe("A$");
  });
});

describe("normalizeCurrencyCode", () => {
  it("returns null for blank currency", () => {
    expect(normalizeCurrencyCode("")).toBeNull();
    expect(normalizeCurrencyCode("   ")).toBeNull();
    expect(normalizeCurrencyCode(null)).toBeNull();
    expect(normalizeCurrencyCode(undefined)).toBeNull();
  });

  it("uppercases known codes", () => {
    expect(normalizeCurrencyCode("aud")).toBe("AUD");
  });
});

describe("money", () => {
  const locale = "en-SG";

  it("renders AUD, SGD, and USD with visibly distinct symbols", () => {
    const amount = 1234.56;
    const aud = money(amount, "AUD", locale);
    const sgd = money(amount, "SGD", locale);
    const usd = money(amount, "USD", locale);

    expect(aud).toContain("A$");
    expect(sgd).toContain("S$");
    expect(usd).toContain("US$");
    expect(aud).not.toBe(sgd);
    expect(aud).not.toBe(usd);
    expect(sgd).not.toBe(usd);
  });

  it("preserves numeric grouping and decimals from Intl", () => {
    const formatted = money(1234.5, "SGD", locale);
    expect(formatted).toMatch(/1,?234\.50/);
    expect(formatted.startsWith("S$")).toBe(true);
  });

  it("returns em dash for empty values", () => {
    expect(money(null, "AUD")).toBe("—");
    expect(money("", "AUD")).toBe("—");
  });

  it("does not invent S$ when called without a currency argument", () => {
    const omitted = money(299, undefined, locale);
    expect(omitted).toMatch(/299\.00/);
    expect(omitted).not.toContain("S$");
    expect(money(299)).not.toContain("S$");
  });

  it("does not invent S$ when currency is blank", () => {
    const plain = money(299, "", locale);
    expect(plain).toMatch(/299\.00/);
    expect(plain).not.toContain("S$");
    expect(plain).not.toContain("A$");
    expect(money(299, null, locale)).toBe(plain);
    expect(money(299, "   ", locale)).toBe(plain);
  });

  it("uses raw display symbol when ISO is blank", () => {
    expect(money(156, "", locale, "$")).toBe("$156.00");
    expect(money(45, null, locale, "€")).toBe("€45.00");
  });
});

describe("formatMoneyByCurrencyMap", () => {
  it("formats a single currency total", () => {
    expect(formatMoneyByCurrencyMap({ SGD: 100 }, "en-SG")).toContain("S$");
    expect(formatMoneyByCurrencyMap({ SGD: 100 }, "en-SG")).toMatch(/100\.00/);
  });

  it("joins mixed currencies without inventing FX", () => {
    const out = formatMoneyByCurrencyMap({ USD: 50, AUD: 100 }, "en-SG");
    expect(out).toContain("A$");
    expect(out).toContain("US$");
    expect(out).toContain(" · ");
    // Sorted by currency code: AUD before USD
    expect(out.indexOf("A$")).toBeLessThan(out.indexOf("US$"));
  });

  it("does not label blank-key totals as SGD", () => {
    const out = formatMoneyByCurrencyMap({ "": 50, AUD: 100 }, "en-SG");
    expect(out).toContain("A$");
    expect(out).toMatch(/50\.00/);
    expect(out).not.toContain("S$");
  });

  it("returns em dash for empty map", () => {
    expect(formatMoneyByCurrencyMap({}, "en-SG")).toBe("—");
  });
});
