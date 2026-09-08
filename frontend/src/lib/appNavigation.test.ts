import { describe, expect, it } from "vitest";
import { filterNavItems, flattenNavItems, NAV_GROUPS } from "@/lib/appNavigation";

describe("appNavigation", () => {
  it("flattens nav groups with group labels", () => {
    const flat = flattenNavItems(NAV_GROUPS);
    expect(flat.some((row) => row.label === "Dashboard" && row.group === "Dashboard")).toBe(true);
    expect(flat.some((row) => row.to === "/upload" && row.group === "Upload")).toBe(true);
    expect(flat.some((row) => row.to === "/approvals" && row.group === "Approvals")).toBe(true);
    expect(flat.some((row) => row.to === "/creations" && row.group === "Contacts")).toBe(true);
    expect(flat.some((row) => row.to === "/ledger-link" && row.label === "Ledger Sync")).toBe(true);
    expect(flat.some((row) => row.to === "/rules")).toBe(false);
  });

  it("filters nav items by label or group", () => {
    const flat = flattenNavItems(NAV_GROUPS);
    const matches = filterNavItems(flat, "vault");
    expect(matches).toHaveLength(1);
    expect(matches[0]?.to).toBe("/vault");
  });
});
