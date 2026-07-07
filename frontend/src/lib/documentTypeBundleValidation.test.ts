import { describe, expect, it } from "vitest";
import { bundleConfigWarnings } from "@/lib/documentTypeBundleValidation";
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
    purchaseBundleRole: "",
    bundleMandatory: [],
    bundleConditional: [],
    ...partial,
  } as DocumentTypeDefinition;
}

describe("bundleConfigWarnings", () => {
  it("warns when enforce playbook has empty mandatory list", () => {
    const warnings = bundleConfigWarnings(dt({ playbookProfile: "po_goods" }), []);
    expect(warnings.some((row) => row.id === "enforce-bundle-empty")).toBe(true);
  });

  it("does not warn when mandatory members are configured", () => {
    const catalogue = [
      dt({ code: "DT-01" }),
      dt({ code: "DT-05", klass: "Non-transactional", posting: "No", purchaseBundleRole: "po" }),
    ];
    const warnings = bundleConfigWarnings(
      dt({ playbookProfile: "po_goods", bundleMandatory: ["DT-05"] }),
      catalogue
    );
    expect(warnings.some((row) => row.id === "enforce-bundle-empty")).toBe(false);
  });
});
