import { describe, expect, it } from "vitest";
import { documentTypeDefinitionToApi, ruleBookConfigFromApi } from "@/lib/ruleBookConfigApi";
import {
  DICTIONARY_VERSION,
  DOCUMENT_TYPE_TEMPLATES,
  documentTypeFromTemplate,
  formatPostToSuggestionHint,
  resolvePostToSuggestionForDocumentType,
} from "@/lib/documentTypeTemplates";
import { hydrateRecognitionFromClassifier } from "@/lib/documentTypeRecognition";
import { isPresetExtractionFieldKey } from "@/lib/documentExtractionFields";
import type { DocumentTypeDefinition } from "@/lib/v5DocumentTypes";

describe("documentTypeFromTemplate", () => {
  it("creates a blank custom type with the next org code", () => {
    const existing: DocumentTypeDefinition[] = [
      { code: "DT-01" } as DocumentTypeDefinition,
      { code: "DT-02" } as DocumentTypeDefinition,
    ];
    const created = documentTypeFromTemplate("custom", existing);
    expect(created.code).toBe("DT-03");
    expect(created.enabled).toBe(false);
    expect(created.sourceDictionaryCode).toBeUndefined();
    expect(created.matrixTemplateCode ?? "").toBe("");
  });

  it("clone-on-adopt leaves requiredFields empty and sets dictionary provenance", () => {
    const template = DOCUMENT_TYPE_TEMPLATES.find((row) => row.id !== "custom");
    if (!template) {
      expect(DICTIONARY_VERSION).toBeGreaterThan(0);
      return;
    }

    const created = documentTypeFromTemplate(template.id, []);
    expect(created.requiredFields).toEqual([]);
    expect(created.sourceDictionaryCode).toBe(template.dictionaryCode);
    expect(created.createdFromDictionaryVersion).toBe(DICTIONARY_VERSION);
    expect(created.matrixTemplateCode).toBe("");
    expect(created.recognitionMode).toBe("prompt");
    expect(created.classifier.enabled).toBe(false);
  });

  it("does not copy dictionary postTo text into tenant GL fields on adopt", () => {
    const dictionaryTemplates = DOCUMENT_TYPE_TEMPLATES.filter((row) => row.id !== "custom");
    expect(dictionaryTemplates.length).toBeGreaterThan(0);

    for (const template of dictionaryTemplates) {
      const created = documentTypeFromTemplate(template.id, []);
      expect(created.postTo.ledger, template.dictionaryCode).toBe("");
      expect(created.postTo.subLedger, template.dictionaryCode).toBe("");

      const hint = formatPostToSuggestionHint(
        resolvePostToSuggestionForDocumentType(created)
      );
      const expectedHint = formatPostToSuggestionHint({
        ledger: template.postTo.ledger,
        subLedger: template.postTo.subLedger,
      });
      if (expectedHint) {
        expect(hint, template.dictionaryCode).toBe(expectedHint);
        expect(created.postTo.ledger, template.dictionaryCode).not.toBe(template.postTo.ledger);
      }
    }
  });

  it("keeps only standard catalogue keys from dictionary extractionFields on adopt", () => {
    const dictionaryTemplates = DOCUMENT_TYPE_TEMPLATES.filter((row) => row.id !== "custom");
    expect(dictionaryTemplates).toHaveLength(90);

    for (const template of dictionaryTemplates) {
      const created = documentTypeFromTemplate(template.id, []);
      for (const key of created.extractionFields) {
        expect(isPresetExtractionFieldKey(key), `${template.dictionaryCode}:${key}`).toBe(true);
      }
      const prose = (template.extractionFields ?? []).map((row) => String(row).trim()).filter(Boolean);
      for (const hint of prose) {
        expect(
          created.extractionFieldsSuggestion ?? [],
          `${template.dictionaryCode} missing prose hint`
        ).toContain(hint);
      }
      expect(created.requiredFields).toEqual([]);
    }
  });

  it("merges Tier1/Tier2 mapping keys as catalogue-only and keeps unresolved as hints", () => {
    const lib001 = documentTypeFromTemplate("LIB-001", []);
    expect(lib001.extractionFields).toEqual(
      expect.arrayContaining([
        "currency",
        "invoice_no",
        "line_items",
        "po_reference",
        "subtotal",
        "total",
        "vendor",
        "cost_centre",
        "due_date",
        "invoice_date",
        "remittance_reference",
        "service_period",
        "seller_tax_id",
      ])
    );
    expect(lib001.extractionFields).not.toContain("tax_id");
    expect(lib001.extractionFields).not.toContain("payment_reference");
    expect(lib001.extractionFields.every((key) => isPresetExtractionFieldKey(key))).toBe(true);

    const lib003 = documentTypeFromTemplate("LIB-003", []);
    expect(lib003.counterpartyType).toBe("customer");
    expect(lib003.routeTarget).toBe("Sales Management");
    expect(lib003.extractionFields).toContain("buyer_name");
    expect(lib003.extractionFields).toContain("buyer_tax_id");
    expect(lib003.extractionFields).not.toContain("seller_tax_id");
    expect(lib003.extractionFields).toContain("contract_reference");
    expect(lib003.extractionFields.every((key) => isPresetExtractionFieldKey(key))).toBe(true);

    const lib069 = documentTypeFromTemplate("LIB-069", []);
    expect(lib069.extractionFields).toEqual([]);
    expect(lib069.extractionFieldsSuggestion?.length ?? 0).toBeGreaterThan(0);
  });

  it("persists postToSuggestion through API roundtrip without touching postTo", () => {
    const template = DOCUMENT_TYPE_TEMPLATES.find((row) => row.dictionaryCode === "LIB-001");
    if (!template) return;

    const created = documentTypeFromTemplate(template.id, []);
    expect(created.postTo.ledger).toBe("");
    expect(created.postTo.subLedger).toBe("");
    expect(created.postToSuggestion?.ledger).toBe(template.postTo.ledger);

    const apiRow = documentTypeDefinitionToApi(created);
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

    expect(reloaded.postTo.ledger).toBe("");
    expect(reloaded.postTo.subLedger).toBe("");
    expect(reloaded.postToSuggestion?.ledger).toBe(template.postTo.ledger);
    expect(formatPostToSuggestionHint(resolvePostToSuggestionForDocumentType(reloaded))).toContain(
      template.postTo.ledger.slice(0, 24)
    );
  });

  it("preserves explicit prompt mode when classifier tree is stale", () => {
    const fromTemplate = documentTypeFromTemplate("custom", []);
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

  it("preserves user edits after API roundtrip with dictionary provenance", () => {
    const existing: DocumentTypeDefinition[] = [
      { code: "DT-01" } as DocumentTypeDefinition,
      { code: "DT-02" } as DocumentTypeDefinition,
    ];
    const created = documentTypeFromTemplate("custom", existing);
    expect(created.code).toBe("DT-03");

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
      sourceDictionaryCode: "LIB-001",
      createdFromDictionaryVersion: DICTIONARY_VERSION,
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
    expect(reloaded.sourceDictionaryCode).toBe("LIB-001");
    expect(reloaded.createdFromDictionaryVersion).toBe(DICTIONARY_VERSION);
    expect(reloaded.extractionFields).toEqual(
      expect.arrayContaining(["vendor", "invoice_no", "po_reference"])
    );
  });
});
