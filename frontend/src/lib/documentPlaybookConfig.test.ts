import { describe, expect, it } from "vitest";
import {
  applyPlaybookChange,
  applyRoutePlaybookDefaults,
  matchModeAllowedForRoute,
  matchModeOptionsForEditor,
  matchModesForRoute,
  matchTabLabel,
  playbookProfileOptionsForEditor,
  playbookProfilesForRoute,
  reconcilePlaybookDraft,
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
      "2-way match (PO · Invoice)"
    );
  });

  it("returns 2-way SO invoice label", () => {
    expect(matchTabLabel("Sales Management", "two_way_so_invoice")).toBe(
      "2-way match (SO · Invoice)"
    );
  });

  it("returns 2-way GRN invoice label", () => {
    expect(matchTabLabel("Purchase Management", "two_way_grn_invoice")).toBe(
      "2-way match (GRN · Invoice)"
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
  it("allows PO and route-agnostic match modes on purchase workspace", () => {
    expect(matchModesForRoute("Purchase Management")).toEqual([
      "none",
      "reference_invoice",
      "shipment",
      "subledger_reconcile",
      "receipt_line",
      "three_way_po_grn",
      "two_way_po_ses",
      "two_way_grn_invoice",
    ]);
  });

  it("allows SO and route-agnostic match modes on sales workspace", () => {
    expect(matchModesForRoute("Sales Management")).toEqual([
      "none",
      "reference_invoice",
      "shipment",
      "subledger_reconcile",
      "receipt_line",
      "three_way_so_dn",
      "two_way_so_invoice",
      "two_way_dn_invoice",
    ]);
  });
});

describe("playbookProfilesForRoute", () => {
  it("includes import_dossier and credit_adjustment on purchase route", () => {
    const profiles = playbookProfilesForRoute("Purchase Management");
    expect(profiles).toContain("import_dossier");
    expect(profiles).toContain("credit_adjustment");
    expect(profiles).not.toContain("ar_goods");
  });
});

describe("playbookProfileOptionsForEditor", () => {
  it("includes current profile when route filter would exclude it", () => {
    const draft = dt({
      routeTarget: "Purchase Management",
      playbookProfile: "ar_goods",
      matchPolicy: { mode: "three_way_so_dn" },
    });
    const options = playbookProfileOptionsForEditor(draft);
    expect(options.some((row) => row.value === "ar_goods")).toBe(true);
    expect(options.find((row) => row.value === "ar_goods")?.label).toContain("(current)");
  });
});

describe("matchModeOptionsForEditor", () => {
  it("includes current match mode when route filter would exclude it", () => {
    const draft = dt({
      routeTarget: "Purchase Management",
      matchPolicy: { mode: "three_way_so_dn" },
    });
    const options = matchModeOptionsForEditor(draft);
    expect(options.some((row) => row.value === "three_way_so_dn")).toBe(true);
  });
});

describe("applyPlaybookChange", () => {
  it("auto-fills mandatory members when switching to po_goods", () => {
    const catalogue = [
      dt({ code: "DT-01", playbookProfile: "direct_expense" }),
      dt({ code: "DT-05", klass: "Non-transactional", posting: "No", purchaseBundleRole: "po" }),
      dt({ code: "DT-06", klass: "Non-transactional", posting: "No", purchaseBundleRole: "grn" }),
    ];
    const next = applyPlaybookChange(
      dt({ code: "DT-01", playbookProfile: "direct_expense" }),
      "po_goods",
      catalogue
    );
    expect(next.playbookProfile).toBe("po_goods");
    expect(next.bundleMandatory).toEqual(["DT-05", "DT-06"]);
  });

  it("clears default mandatory pair when downgrading from enforce playbook", () => {
    const catalogue = [
      dt({ code: "DT-01", playbookProfile: "po_goods", bundleMandatory: ["DT-05", "DT-06"] }),
      dt({ code: "DT-05", klass: "Non-transactional", posting: "No", purchaseBundleRole: "po" }),
      dt({ code: "DT-06", klass: "Non-transactional", posting: "No", purchaseBundleRole: "grn" }),
    ];
    const next = applyPlaybookChange(
      catalogue[0],
      "direct_expense",
      catalogue
    );
    expect(next.playbookProfile).toBe("direct_expense");
    expect(next.bundleMandatory).toEqual([]);
  });

  it("preserves custom mandatory list when downgrading from enforce playbook", () => {
    const catalogue = [
      dt({
        code: "DT-01",
        playbookProfile: "po_goods",
        bundleMandatory: ["DT-05", "DT-06", "DT-07"],
      }),
      dt({ code: "DT-05", klass: "Non-transactional", posting: "No", purchaseBundleRole: "po" }),
      dt({ code: "DT-06", klass: "Non-transactional", posting: "No", purchaseBundleRole: "grn" }),
    ];
    const next = applyPlaybookChange(catalogue[0], "direct_expense", catalogue);
    expect(next.bundleMandatory).toEqual(["DT-05", "DT-06", "DT-07"]);
  });
});

describe("mergeApprovalPolicyMode", () => {
  it("preserves risk fields when playbook mode changes", () => {
    const next = reconcilePlaybookDraft(
      dt({
        playbookProfile: "po_goods",
        approvalPolicy: {
          mode: "touchless_on_clean_match",
          autoApproveBelow: 500,
          requireApprovalForUnmatched: true,
          requireApprovalForUnverifiedCounterparty: true,
        },
      })
    );
    expect(next.approvalPolicy.mode).toBe("touchless_on_clean_match");
    expect(next.approvalPolicy.autoApproveBelow).toBe(500);
    expect(next.approvalPolicy.requireApprovalForUnmatched).toBe(true);
    expect(next.approvalPolicy.requireApprovalForUnverifiedCounterparty).toBe(true);
  });
});

describe("reconcilePlaybookDraft", () => {
  it("sets supporting playbook when purchase bundle role is po", () => {
    const next = reconcilePlaybookDraft(
      dt({
        playbookProfile: "po_goods",
        matchPolicy: { mode: "three_way_po_grn" },
        approvalPolicy: { mode: "touchless_on_clean_match" },
        purchaseBundleRole: "po",
      })
    );
    expect(next.playbookProfile).toBe("supporting");
    expect(next.matchPolicy.mode).toBe("none");
    expect(next.approvalPolicy.mode).toBe("no_posting");
  });

  it("clamps invalid match mode to none for route", () => {
    const next = reconcilePlaybookDraft(
      dt({
        playbookProfile: "po_goods",
        matchPolicy: { mode: "three_way_so_dn" },
      })
    );
    expect(next.matchPolicy.mode).toBe("none");
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

  it("preserves credit_adjustment when switching vault to purchase", () => {
    const draft = dt({
      routeTarget: "Vault",
      playbookProfile: "credit_adjustment",
      matchPolicy: { mode: "reference_invoice" },
      approvalPolicy: { mode: "supervisor_on_exception" },
    });
    const next = applyRoutePlaybookDefaults(draft, "Purchase Management");
    expect(next.playbookProfile).toBe("credit_adjustment");
    expect(next.matchPolicy.mode).toBe("reference_invoice");
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

  it("allows reference_invoice on purchase route", () => {
    expect(matchModeAllowedForRoute("Purchase Management", "reference_invoice")).toBe(true);
  });
});
