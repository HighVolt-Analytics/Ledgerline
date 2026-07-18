import { describe, expect, it } from "vitest";
import {
  effectiveDocumentTypeCode,
  invoiceDocumentTypeDisplayLabel,
  isVisionAwaitingClassification,
  storedDocumentTypeCode,
} from "@/lib/documentTypeResolve";
import type { DocumentTypeDefinition } from "@/lib/v5DocumentTypes";

const nonPoInvoice: DocumentTypeDefinition = {
  code: "DT-02",
  title: "Non-PO vendor invoice",
  shortTitle: "Non-PO invoice",
  enabled: true,
  routeTarget: "Purchase Management",
  klass: "Transactional",
  posting: "Yes",
  classifier: {
    priority: 10,
    enabled: true,
    confidence: 0.8,
    root: { type: "group", operator: "AND", children: [] },
  },
} as DocumentTypeDefinition;

const grnDt: DocumentTypeDefinition = {
  code: "DT-28",
  title: "Goods receipt note (GRN) / delivery docket",
  shortTitle: "GRN",
  enabled: true,
  routeTarget: "Purchase Management",
  klass: "Transactional",
  posting: "Yes",
  purchaseBundleRole: "grn",
  classifier: {
    priority: 20,
    enabled: true,
    confidence: 0.8,
    root: { type: "group", operator: "AND", children: [] },
  },
} as DocumentTypeDefinition;

describe("documentTypeResolve pipeline-aware labels", () => {
  it("detects vision awaiting classification", () => {
    expect(isVisionAwaitingClassification({ evaluation_status: "awaiting_classification" })).toBe(
      true
    );
    expect(isVisionAwaitingClassification({ evaluation_status: "vision_vaulted" })).toBe(true);
    expect(isVisionAwaitingClassification({ evaluation_status: "vision_header_review" })).toBe(
      true
    );
    expect(isVisionAwaitingClassification({ evaluation_status: "needs_review" })).toBe(false);
  });

  it("does not invent catalogue DT while awaiting classification", () => {
    const code = effectiveDocumentTypeCode(
      {
        purchase_document_type: "invoice",
        evaluation_status: "awaiting_classification",
        document_heading: "TAX INVOICE",
      },
      [nonPoInvoice]
    );
    expect(code).toBe("");
  });

  it("does not invent catalogue DT on early Received rows (no evaluation yet)", () => {
    const code = effectiveDocumentTypeCode(
      {
        purchase_document_type: "invoice",
        evaluation_status: null,
      },
      [nonPoInvoice]
    );
    expect(code).toBe("");
    expect(
      invoiceDocumentTypeDisplayLabel(
        {
          purchase_document_type: "invoice",
          evaluation_status: null,
        },
        [nonPoInvoice]
      )
    ).toBe("Invoice");
  });

  it("shows vision Tax Invoice chip while awaiting classification", () => {
    const label = invoiceDocumentTypeDisplayLabel(
      {
        purchase_document_type: "invoice",
        evaluation_status: "awaiting_classification",
        document_heading: "TAX INVOICE",
        extracted_fields: { canonical_document_type: "Tax Invoice" },
      },
      [nonPoInvoice]
    );
    expect(label).toBe("Tax Invoice");
  });

  it("prefers vision Goods Receipt Note over catalogue GRN title", () => {
    const label = invoiceDocumentTypeDisplayLabel(
      {
        purchase_document_type: "grn",
        evaluation_status: "awaiting_classification",
        extracted_fields: { canonical_document_type: "Goods Receipt Note" },
      },
      [grnDt]
    );
    expect(label).toBe("Goods Receipt Note");
    expect(label).not.toContain("delivery docket");
  });

  it("uses stored catalogue title after classification", () => {
    expect(storedDocumentTypeCode({ document_type_code: "DT-02" })).toBe("DT-02");
    const label = invoiceDocumentTypeDisplayLabel(
      {
        document_type_code: "DT-02",
        purchase_document_type: "invoice",
        evaluation_status: "needs_review",
        extracted_fields: { canonical_document_type: "Tax Invoice" },
      },
      [nonPoInvoice]
    );
    expect(label).toBe("Non-PO vendor invoice");
  });

  it("still resolves purchase-kind DT on legacy path after evaluation", () => {
    const code = effectiveDocumentTypeCode(
      {
        purchase_document_type: "invoice",
        evaluation_status: "needs_review",
      },
      [nonPoInvoice]
    );
    expect(code).toBe("DT-02");
  });
});
