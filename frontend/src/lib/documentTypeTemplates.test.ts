import { describe, expect, it } from "vitest";
import {
  DOCUMENT_TYPE_TEMPLATES,
  documentTypeFromTemplate,
  documentTypesFromStarterPack,
  resolveBundleCodesFromMatrix,
} from "@/lib/documentTypeTemplates";
import { matchRulesFormFromClassifier } from "@/lib/documentMatchRules";
import { isDtCode } from "@/lib/documentBundleConfig";
import type { DocumentTypeDefinition } from "@/lib/v5DocumentTypes";

describe("documentTypesFromStarterPack", () => {
  it("wires procurement pack with org bundle codes", () => {
    const { types, unclassifiedDocumentTypeCode } = documentTypesFromStarterPack(
      "procurement_3way",
      []
    );
    expect(types).toHaveLength(3);
    const invoice = types.find((row) => row.matrixTemplateCode === "DT-01");
    const po = types.find((row) => row.matrixTemplateCode === "DT-02");
    const grn = types.find((row) => row.matrixTemplateCode === "DT-03");
    expect(invoice?.bundleMandatory).toEqual([po?.code, grn?.code].filter(Boolean));
    expect(unclassifiedDocumentTypeCode).toBeUndefined();
  });

  it("wires sales pack with org bundle codes", () => {
    const { types, unclassifiedDocumentTypeCode } = documentTypesFromStarterPack(
      "sales_3way",
      []
    );
    expect(types).toHaveLength(3);
    const invoice = types.find((row) => row.matrixTemplateCode === "DT-26");
    const so = types.find((row) => row.matrixTemplateCode === "DT-27");
    const dn = types.find((row) => row.matrixTemplateCode === "DT-28");
    expect(invoice?.routeTarget).toBe("Sales Management");
    expect(so?.routeTarget).toBe("Sales Management");
    expect(dn?.routeTarget).toBe("Sales Management");
    expect(invoice?.bundleMandatory).toEqual([so?.code, dn?.code].filter(Boolean));
    expect(so?.salesBundleRole).toBe("so");
    expect(dn?.salesBundleRole).toBe("dn");
    expect(invoice?.playbookProfile).toBe("ar_goods");
    expect(so?.classifier.enabled).toBe(true);
    expect(dn?.classifier.enabled).toBe(true);
    expect(unclassifiedDocumentTypeCode).toBeUndefined();
  });

  it("sets unclassified to direct expense org code for opex pack", () => {
    const { types, unclassifiedDocumentTypeCode } = documentTypesFromStarterPack(
      "direct_opex",
      []
    );
    expect(types).toHaveLength(2);
    const direct = types.find((row) => row.matrixTemplateCode === "DT-08");
    expect(direct?.playbookProfile).toBe("direct_expense");
    expect(direct?.bundleMandatory).toEqual([]);
    expect(unclassifiedDocumentTypeCode).toBe(direct?.code);
  });
});

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
