import { describe, expect, it } from "vitest";
import {
  DASHBOARD_PERIOD_OPTIONS,
  DASHBOARD_PERIODS,
  DEFAULT_DASHBOARD_PERIOD,
  dashboardPeriodQuery,
  isDashboardPeriod,
} from "@/lib/dashboardPeriod";

describe("dashboardPeriod", () => {
  it("exposes finance-standard reporting windows", () => {
    expect(DASHBOARD_PERIODS).toEqual(["fy_ytd", "mtd", "fq_ytd", "r12"]);
    expect(DASHBOARD_PERIOD_OPTIONS.map((option) => option.label)).toEqual([
      "Financial year YTD",
      "Month to date",
      "Quarter to date",
      "Rolling 12 months",
    ]);
  });

  it("defaults to Australian FY year-to-date", () => {
    expect(DEFAULT_DASHBOARD_PERIOD).toBe("fy_ytd");
  });

  it("validates period keys", () => {
    expect(isDashboardPeriod("fy_ytd")).toBe(true);
    expect(isDashboardPeriod("mtd")).toBe(true);
    expect(isDashboardPeriod("month")).toBe(false);
  });

  it("builds API query strings", () => {
    expect(dashboardPeriodQuery("mtd")).toBe("period=mtd");
    expect(dashboardPeriodQuery("fq_ytd")).toBe("period=fq_ytd");
  });
});
