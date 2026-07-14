import { describe, expect, it } from "vitest";
import shippedCatalog from "@/lib/v5DocumentTypes.json";
import {
  DOCUMENT_TYPE_TEMPLATES,
  documentTypeFromTemplate,
  resolveBundleCodesFromMatrix,
} from "@/lib/documentTypeTemplates";
import {
  DOCUMENT_TYPE_DEFAULT_PROMPTS,
  defaultLlmPromptForCode,
} from "@/lib/documentTypeDefaultPrompts";
import { hydrateRecognitionFromClassifier } from "@/lib/documentTypeRecognition";
import { isDtCode } from "@/lib/documentBundleConfig";
import type { DocumentTypeDefinition } from "@/lib/v5DocumentTypes";

const SHIPPED_CODES = (shippedCatalog as Array<{ code: string }>).map((row) =>
  row.code.trim().toUpperCase()
);

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
  it("covers every shipped v5 code with a default prompt", () => {
    expect(Object.keys(DOCUMENT_TYPE_DEFAULT_PROMPTS).sort()).toEqual([...SHIPPED_CODES].sort());
    for (const code of SHIPPED_CODES) {
      expect(defaultLlmPromptForCode(code).length, code).toBeGreaterThanOrEqual(80);
    }
  });

  it("defaults shipped templates to prompt recognition mode", () => {
    for (const template of DOCUMENT_TYPE_TEMPLATES) {
      if (template.id === "custom") continue;
      const def = documentTypeFromTemplate(template.id, []);
      expect(def.recognitionMode, template.id).toBe("prompt");
      expect(def.llmPrompt.trim().length, template.id).toBeGreaterThanOrEqual(80);
      expect(def.recognitionSignals, template.id).toEqual([]);
      expect(def.classifier.enabled, template.id).toBe(false);
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

  it("preserves explicit prompt mode when classifier tree is stale", () => {
    const fromTemplate = documentTypeFromTemplate("DT-01", []);
    const hydrated = hydrateRecognitionFromClassifier({
      ...fromTemplate,
      llmPrompt: "Custom vendor invoice rules for our AP team.",
      recognitionMode: "prompt",
      classifier: {
        ...fromTemplate.classifier,
        enabled: true,
        root: {
          type: "group",
          operator: "AND",
          children: [
            {
              type: "condition",
              field: "has_po_reference",
              operator: "equals",
              value: "true",
            },
          ],
        },
      },
    });
    expect(hydrated.recognitionMode).toBe("prompt");
    expect(hydrated.llmPrompt).toContain("Custom vendor invoice rules");
    expect(hydrated.classifier.enabled).toBe(false);
  });
});
