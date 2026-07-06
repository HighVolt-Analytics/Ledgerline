import { describe, expect, it } from "vitest";
import {
  applyRoutePlaybookDefaults,
  matchModeAllowedForRoute,
  matchModesForRoute,
  matchTabLabel,
  suggestedPlaybookForRoute,
} from "@/lib/documentPlaybookConfig";
import type { DocumentTypeDefinition } from "@/lib/v5DocumentTypes";

function dt(partial: Partial<DocumentTypeDefinition>): DocumentTypeDefinition {
  return {
    code: "DT-01",
    title: "Test",
    shortTitle: "Test",
    klass: "Transactional",
    posting: "Yes",
    recognitionMode: "signals",
    recognitionSignals: ["heading_invoice"],
    llmPrompt: "",
    routeTarget: "Purchase Management",
    enabled: true,
    playbookProfile: "po_goods",
    matchPolicy: { mode: "three_way_po_grn" },
    approvalPolicy: { mode: "touchless_on_clean_match" },
    purchaseBundleRole: "",
    salesBundleRole: "",
    bundleMandatory: [],
    bundleConditional: [],
    ...partial,
  } as DocumentTypeDefinition;
}

describe("matchTabLabel", () => {
  it("returns 3-way purchase label for po_goods", () => {
    expect(matchTabLabel("Purchase Management", "three_way_po_grn")).toBe(
      "3-way match (PO · GRN · Invoice)"
    );
  });

  it("returns 2-way purchase label for po_services", () => {
    expect(matchTabLabel("Purchase Management", "two_way_po_ses")).toBe(
      "2-way match (PO · service entry)"
    );
  });

  it("returns 3-way sales label for ar_goods", () => {
    expect(matchTabLabel("Sales Management", "three_way_so_dn")).toBe(
      "3-way match (SO · DN · Invoice)"
    );
  });

  it("returns 2-way sales label for ar_goods_2way", () => {
    expect(matchTabLabel("Sales Management", "two_way_dn_invoice")).toBe(
      "2-way match (DN · Invoice)"
    );
  });
});

describe("matchModesForRoute", () => {
  it("restricts purchase workspace to PO match modes", () => {
    expect(matchModesForRoute("Purchase Management")).toEqual([
      "none",
      "three_way_po_grn",
      "two_way_po_ses",
    ]);
  });

  it("restricts sales workspace to AR match modes", () => {
    expect(matchModesForRoute("Sales Management")).toEqual([
      "none",
      "three_way_so_dn",
      "two_way_dn_invoice",
    ]);
  });
});

describe("applyRoutePlaybookDefaults", () => {
  it("keeps compatible match mode when route unchanged", () => {
    const draft = dt({
      routeTarget: "Purchase Management",
      playbookProfile: "po_services",
      matchPolicy: { mode: "two_way_po_ses" },
    });
    const next = applyRoutePlaybookDefaults(draft, "Purchase Management");
    expect(next.playbookProfile).toBe("po_services");
    expect(next.matchPolicy.mode).toBe("two_way_po_ses");
  });

  it("resets playbook when switching to sales with purchase match mode", () => {
    const draft = dt({
      routeTarget: "Purchase Management",
      playbookProfile: "po_goods",
      matchPolicy: { mode: "three_way_po_grn" },
    });
    const next = applyRoutePlaybookDefaults(draft, "Sales Management");
    expect(next.routeTarget).toBe("Sales Management");
    expect(next.playbookProfile).toBe("ar_goods");
    expect(next.matchPolicy.mode).toBe("three_way_so_dn");
  });

  it("resets playbook when switching to purchase with sales match mode", () => {
    const draft = dt({
      routeTarget: "Sales Management",
      playbookProfile: "ar_goods_2way",
      matchPolicy: { mode: "two_way_dn_invoice" },
    });
    const next = applyRoutePlaybookDefaults(draft, "Purchase Management");
    expect(next.playbookProfile).toBe("po_goods");
    expect(next.matchPolicy.mode).toBe("three_way_po_grn");
  });
});

describe("suggestedPlaybookForRoute", () => {
  it("suggests ar_goods for sales route", () => {
    expect(suggestedPlaybookForRoute("Sales Management")).toBe("ar_goods");
  });

  it("suggests po_goods for purchase route", () => {
    expect(suggestedPlaybookForRoute("Purchase Management")).toBe("po_goods");
  });
});

describe("matchModeAllowedForRoute", () => {
  it("rejects sales match mode on purchase route", () => {
    expect(matchModeAllowedForRoute("Purchase Management", "three_way_so_dn")).toBe(false);
  });

  it("allows purchase 2-way on purchase route", () => {
    expect(matchModeAllowedForRoute("Purchase Management", "two_way_po_ses")).toBe(true);
  });
});
