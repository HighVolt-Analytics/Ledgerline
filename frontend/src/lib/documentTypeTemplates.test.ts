import { describe, expect, it } from "vitest";
import shippedCatalog from "@/lib/v5DocumentTypes.json";
import { documentTypeDefinitionToApi, ruleBookConfigFromApi } from "@/lib/ruleBookConfigApi";
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

  it("preserves user edits after API roundtrip when org code differs from matrix template", () => {
    const existing: DocumentTypeDefinition[] = [
      { code: "DT-01" } as DocumentTypeDefinition,
      { code: "DT-02" } as DocumentTypeDefinition,
      { code: "DT-03" } as DocumentTypeDefinition,
      { code: "DT-04" } as DocumentTypeDefinition,
    ];
    const created = documentTypeFromTemplate("DT-01", existing);
    expect(created.code).toBe("DT-05");
    expect(created.matrixTemplateCode).toBe("DT-01");

    const customPrompt =
      "Custom PO invoice recognition for our warehouse vendors — handwritten totals allowed.";
    const edited: DocumentTypeDefinition = {
      ...created,
      title: "Our PO goods invoice",
      shortTitle: "Our PO invoice",
      llmPrompt: customPrompt,
      playbookProfile: "standard_transactional",
      matchPolicy: { mode: "none" },
      approvalPolicy: { mode: "full_doa" },
      extractionFields: ["vendor", "invoice_no", "po_reference"],
      requiredFields: ["vendor"],
      postTo: { ledger: "Operating Expenses", subLedger: "" },
    };

    const apiRow = documentTypeDefinitionToApi(edited);
    const reloaded = ruleBookConfigFromApi({
      schema_version: 1,
      document_classification: {
        unclassified_document_type_code: "",
        unclassified_min_confidence: 0.45,
      },
      ai_classification: {
        document_ai_provider: "azure_di",
        auto_route_min_confidence: 0.85,
      },
      org_context: { company_name: "", industry: "", fiscal_year_end: "" },
      document_types: [apiRow],
      email_capture_rules: [],
      purchase_rules: [],
      sales_rules: [],
      expense_rules: [],
      team_expense_rules: [],
      vendor_detection_config: { weights: {}, threshold: 70 },
      posting_defaults: {
        tax_account: "GST Paid",
        payable_account: "Accounts Payable",
        receivable_account: "Accounts Receivable",
        fallback_account: "Suspense Account",
      },
      document_sets: [],
      vendor_masters: [],
      employee_masters: [],
      chart_of_accounts: [],
    }).documentTypes[0]!;

    expect(reloaded.title).toBe("Our PO goods invoice");
    expect(reloaded.shortTitle).toBe("Our PO invoice");
    expect(reloaded.llmPrompt).toBe(customPrompt);
    expect(reloaded.playbookProfile).toBe("standard_transactional");
    expect(reloaded.matchPolicy.mode).toBe("none");
    expect(reloaded.matrixTemplateCode).toBe("DT-01");
    expect(reloaded.extractionFields).toEqual(
      expect.arrayContaining(["vendor", "invoice_no", "po_reference"])
    );
  });
});
