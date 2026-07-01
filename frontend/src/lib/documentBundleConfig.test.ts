import { describe, expect, it } from "vitest";
import {
  bundleEditorMode,
  bundleMemberCandidates,
  suggestedMandatoryBundleMembers,
} from "@/lib/documentBundleConfig";
import type { DocumentTypeDefinition } from "@/lib/v5DocumentTypes";

function dt(partial: Partial<DocumentTypeDefinition>): DocumentTypeDefinition {
  return {
    code: "DT-01",
    title: "Test",
    shortTitle: "Test",
    klass: "Transactional",
    posting: "Yes",
    fraudRisk: "low",
    oneLine: "test",
    routeTarget: "Purchase Management",
    enabled: true,
    playbookProfile: "po_goods",
    purchaseBundleRole: "",
    bundleMandatory: [],
    bundleConditional: [],
    ...partial,
  } as DocumentTypeDefinition;
}

describe("bundleEditorMode", () => {
  it("uses member mode for PO supporting type", () => {
    expect(
      bundleEditorMode(
        dt({
          code: "DT-02",
          klass: "Supporting",
          posting: "No",
          purchaseBundleRole: "po",
        })
      )
    ).toBe("member");
  });

  it("uses consumer mode for po_goods invoice", () => {
    expect(bundleEditorMode(dt({ playbookProfile: "po_goods" }))).toBe("consumer");
  });

  it("uses inactive mode for direct expense", () => {
    expect(
      bundleEditorMode(
        dt({
          playbookProfile: "direct_expense",
          routeTarget: "Approvals",
          posting: "Yes",
        })
      )
    ).toBe("inactive");
  });
});

describe("bundleMemberCandidates", () => {
  it("lists only supporting types with PO/GRN role", () => {
    const catalogue = [
      dt({ code: "DT-01", playbookProfile: "po_goods" }),
      dt({ code: "DT-02", klass: "Supporting", posting: "No", purchaseBundleRole: "po" }),
      dt({ code: "DT-03", klass: "Supporting", posting: "No", purchaseBundleRole: "grn" }),
      dt({ code: "DT-08", playbookProfile: "direct_expense", routeTarget: "Approvals" }),
    ];
    const members = bundleMemberCandidates(catalogue, "DT-01");
    expect(members.map((row) => row.code)).toEqual(["DT-02", "DT-03"]);
  });
});

describe("suggestedMandatoryBundleMembers", () => {
  it("suggests PO and GRN codes from catalogue", () => {
    const catalogue = [
      dt({ code: "DT-01" }),
      dt({ code: "DT-05", klass: "Supporting", posting: "No", purchaseBundleRole: "po" }),
      dt({ code: "DT-06", klass: "Supporting", posting: "No", purchaseBundleRole: "grn" }),
    ];
    expect(suggestedMandatoryBundleMembers(catalogue, "DT-01")).toEqual(["DT-05", "DT-06"]);
  });
});
