import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

/** Regression: aggregate pages keep explicit currency wiring. */
describe("aggregate money call sites", () => {
  it("Dashboard formats with baseCurrency from stats", () => {
    const src = readFileSync(
      join(__dirname, "../pages/DashboardPage.tsx"),
      "utf8"
    );
    expect(src).toContain("money(v, baseCurrency, locale)");
    expect(src).toContain("stats.base_currency");
  });

  it("Reports formats with analytics base_currency", () => {
    const src = readFileSync(join(__dirname, "../pages/ReportsPage.tsx"), "utf8");
    expect(src).toContain("money(v, currency, locale)");
    expect(src).toContain("base_currency");
  });

  it("Reconciliation formats base totals and per-row currency", () => {
    const src = readFileSync(
      join(__dirname, "../pages/ReconciliationPage.tsx"),
      "utf8"
    );
    expect(src).toContain("money(v, baseCurrency, locale)");
    expect(src).toContain("base_currency");
    expect(src).toContain("formatMoneyByCurrencyMap");
    expect(src).toContain("fmtRow");
  });
});
