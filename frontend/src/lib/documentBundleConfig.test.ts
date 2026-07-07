import { describe, expect, it } from "vitest";
import {
  bundleEditorMode,
  bundleMandatoryMatchesSuggested,
  bundleMemberCandidates,
  normalizeBundleConditional,
  reconcileBundleDraft,
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

describe("bundleEditorMode", () => {
  it("uses member mode for PO supporting type", () => {
    expect(
      bundleEditorMode(
        dt({
          code: "DT-02",
          klass: "Non-transactional",
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

  it("uses inactive for payable purchase type without enforce playbook", () => {
    expect(
      bundleEditorMode(
        dt({
          playbookProfile: "standard_transactional",
          posting: "Yes",
          routeTarget: "Purchase Management",
          bundleMandatory: ["DT-05"],
        })
      )
    ).toBe("inactive");
  });
});

describe("reconcileBundleDraft", () => {
  it("auto-fills PO and GRN when consumer playbook has empty mandatory", () => {
    const catalogue = [
      dt({ code: "DT-01", playbookProfile: "po_goods" }),
      dt({ code: "DT-05", klass: "Non-transactional", posting: "No", purchaseBundleRole: "po" }),
      dt({ code: "DT-06", klass: "Non-transactional", posting: "No", purchaseBundleRole: "grn" }),
    ];
    const next = reconcileBundleDraft(dt({ playbookProfile: "po_goods" }), catalogue);
    expect(next.bundleMandatory).toEqual(["DT-05", "DT-06"]);
  });

  it("clears mandatory when playbook does not enforce bundle", () => {
    const next = reconcileBundleDraft(
      dt({
        playbookProfile: "direct_expense",
        bundleMandatory: ["DT-05", "DT-06"],
      })
    );
    expect(next.bundleMandatory).toEqual([]);
  });

  it("clears mandatory for bundle member types", () => {
    const next = reconcileBundleDraft(
      dt({
        code: "DT-05",
        purchaseBundleRole: "po",
        playbookProfile: "supporting",
        bundleMandatory: ["DT-06"],
      })
    );
    expect(next.bundleMandatory).toEqual([]);
  });
});

describe("bundleMandatoryMatchesSuggested", () => {
  it("returns true when mandatory equals suggested pair", () => {
    const catalogue = [
      dt({ code: "DT-01" }),
      dt({ code: "DT-05", klass: "Non-transactional", posting: "No", purchaseBundleRole: "po" }),
      dt({ code: "DT-06", klass: "Non-transactional", posting: "No", purchaseBundleRole: "grn" }),
    ];
    expect(
      bundleMandatoryMatchesSuggested(
        dt({ bundleMandatory: ["DT-05", "DT-06"] }),
        catalogue
      )
    ).toBe(true);
  });
});

describe("bundleMemberCandidates", () => {
  it("lists only supporting types with PO/GRN role", () => {
    const catalogue = [
      dt({ code: "DT-01", playbookProfile: "po_goods" }),
      dt({ code: "DT-02", klass: "Non-transactional", posting: "No", purchaseBundleRole: "po" }),
      dt({ code: "DT-03", klass: "Non-transactional", posting: "No", purchaseBundleRole: "grn" }),
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
      dt({ code: "DT-05", klass: "Non-transactional", posting: "No", purchaseBundleRole: "po" }),
      dt({ code: "DT-06", klass: "Non-transactional", posting: "No", purchaseBundleRole: "grn" }),
    ];
    expect(suggestedMandatoryBundleMembers(catalogue, "DT-01")).toEqual(["DT-05", "DT-06"]);
  });
});

describe("normalizeBundleConditional", () => {
  it("keeps document type codes only", () => {
    expect(normalizeBundleConditional(["DT-02", "DT-03"])).toEqual(["DT-02", "DT-03"]);
  });

  it("strips legacy free-text advisories", () => {
    expect(
      normalizeBundleConditional([
        "DT-02",
        "Quality certificate",
        "Packing list (if PO flags inspection)",
      ])
    ).toEqual(["DT-02"]);
  });
});
