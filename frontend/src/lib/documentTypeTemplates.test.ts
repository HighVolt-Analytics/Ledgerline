import { describe, expect, it } from "vitest";
import {
  DOCUMENT_TYPE_TEMPLATES,
  documentTypeFromTemplate,
  resolveBundleCodesFromMatrix,
} from "@/lib/documentTypeTemplates";
import { matchRulesFormFromClassifier } from "@/lib/documentMatchRules";
import { isDtCode } from "@/lib/documentBundleConfig";
import type { DocumentTypeDefinition } from "@/lib/v5DocumentTypes";

describe("resolveBundleCodesFromMatrix", () => {
  it("maps matrix template ids to org catalogue codes", () => {
    const existing: DocumentTypeDefinition[] = [
      {
        code: "DT-05",
        matrixTemplateCode: "DT-02",
      } as DocumentTypeDefinition,
      {
        code: "DT-06",
        matrixTemplateCode: "DT-03",
      } as DocumentTypeDefinition,
    ];
    expect(resolveBundleCodesFromMatrix(existing, ["DT-02", "DT-03"])).toEqual([
      "DT-05",
      "DT-06",
    ]);
  });
});

describe("documentTypeFromTemplate format", () => {
  it("produces parseable classifiers for every shipped template", () => {
    for (const template of DOCUMENT_TYPE_TEMPLATES) {
      if (template.id === "custom") continue;
      const def = documentTypeFromTemplate(template.id, []);
      const form = matchRulesFormFromClassifier(def.classifier.root);
      expect(form.matchRules.length, template.id).toBeGreaterThan(0);
    }
  });

  it("uses DT codes only in bundleConditional", () => {
    const arInvoice = documentTypeFromTemplate("DT-26", []);
    expect(arInvoice.bundleConditional).toEqual(["DT-27"]);
    for (const code of arInvoice.bundleConditional ?? []) {
      expect(isDtCode(code)).toBe(true);
    }
  });

  it("derives absentFields from supporting-doc exclude rules", () => {
    const po = documentTypeFromTemplate("DT-02", []);
    expect(po.absentFields).toContain("invoice_no");
  });
});
