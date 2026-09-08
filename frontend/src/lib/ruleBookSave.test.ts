import { describe, expect, it } from "vitest";
import {
  mergeDocumentTypePatch,
  shouldApplyRuleBookSaveResponse,
} from "@/lib/ruleBookSave";
import type { DocumentTypeDefinition } from "@/lib/v5DocumentTypes";

function sampleType(code: string, requiredFields: string[]): DocumentTypeDefinition {
  return {
    code,
    title: code,
    shortTitle: code,
    klass: "Transactional",
    posting: "Yes",
    recognitionMode: "signals",
    recognitionSignals: [],
    llmPrompt: "",
    routeTarget: "Purchase Management",
    counterpartyType: "vendor",
    enabled: true,
    classifier: {
      enabled: false,
      priority: 100,
      confidence: 0.85,
      root: { type: "group", operator: "AND", children: [] },
    },
    requiredFields,
    absentFields: [],
    minRouteConfidence: 0.65,
    validationProfile: "",
    playbookProfile: "po_goods",
    matchPolicy: { mode: "three_way_po_grn" },
    approvalPolicy: { mode: "full_doa" },
    validationRules: [],
    customValidationRules: [],
    extractionFields: ["vendor", "total", "invoice_no"],
    extraction: [],
    checks: [],
    match: [],
    approval: [],
    accounting: [],
    special: [],
    bundleMandatory: [],
    bundleConditional: [],
    purchaseBundleRole: "",
    salesBundleRole: "",
    postTo: { ledger: "", subLedger: "" },
    matrixTemplateCode: "",
  };
}

describe("mergeDocumentTypePatch", () => {
  it("merges into the latest catalog without dropping other types", () => {
    const catalog = [sampleType("DT-01", ["vendor", "total"]), sampleType("DT-02", ["vendor"])];
    const once = mergeDocumentTypePatch(catalog, "DT-01", { requiredFields: ["vendor"] });
    const twice = mergeDocumentTypePatch(once, "DT-01", { requiredFields: [] });
    expect(twice.find((dt) => dt.code === "DT-01")?.requiredFields).toEqual([]);
    expect(twice.find((dt) => dt.code === "DT-02")?.requiredFields).toEqual(["vendor"]);
  });

  it("matches document type codes case-insensitively", () => {
    const catalog = [sampleType("dt-01", ["vendor"])];
    const next = mergeDocumentTypePatch(catalog, "DT-01", { requiredFields: ["total"] });
    expect(next[0]?.requiredFields).toEqual(["total"]);
  });
});

describe("shouldApplyRuleBookSaveResponse", () => {
  it("accepts only the latest save generation", () => {
    expect(shouldApplyRuleBookSaveResponse(2, 2)).toBe(true);
    expect(shouldApplyRuleBookSaveResponse(1, 2)).toBe(false);
  });
});
