import { describe, expect, it } from "vitest";
import {
  ROUTE_EXPENSES,
  ROUTE_PURCHASE,
  ROUTE_SALES,
  ROUTE_TEAM,
} from "@/lib/invoice";
import {
  isUploadRouteFilter,
  parseUploadRouteFilter,
  routeTargetForUploadFilter,
  uploadRouteFilterLabel,
} from "@/lib/uploadRouteFilter";

describe("uploadRouteFilter", () => {
  it("maps each tab to the exact invoice route_target", () => {
    expect(routeTargetForUploadFilter("team-expenses")).toBe(ROUTE_TEAM);
    expect(routeTargetForUploadFilter("expenses")).toBe(ROUTE_EXPENSES);
    expect(routeTargetForUploadFilter("purchases")).toBe(ROUTE_PURCHASE);
    expect(routeTargetForUploadFilter("sales")).toBe(ROUTE_SALES);
  });

  it("keeps the tab labels used on Upload", () => {
    expect(uploadRouteFilterLabel("team-expenses")).toBe("Team Expenses");
    expect(uploadRouteFilterLabel("expenses")).toBe("Expenses Management");
    expect(uploadRouteFilterLabel("purchases")).toBe("Purchase Management");
    expect(uploadRouteFilterLabel("sales")).toBe("Sales Management");
  });

  it("parses view query values and rejects unknown tokens", () => {
    expect(parseUploadRouteFilter("team-expenses")).toBe("team-expenses");
    expect(parseUploadRouteFilter("purchases")).toBe("purchases");
    expect(parseUploadRouteFilter("summary")).toBeNull();
    expect(parseUploadRouteFilter("setup")).toBeNull();
    expect(parseUploadRouteFilter(null)).toBeNull();
    expect(isUploadRouteFilter("sales")).toBe(true);
    expect(isUploadRouteFilter("all")).toBe(false);
  });
});
