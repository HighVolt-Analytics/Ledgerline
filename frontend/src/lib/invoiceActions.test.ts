import { describe, expect, it } from "vitest";
import {
  compulsoryFieldsForInvoice,
  validateInvoiceFieldsForApproval,
  validateInvoiceReadyForApproval,
} from "@/lib/invoiceActions";

const documentTypes = [
  {
    code: "DT-08",
    requiredFields: ["vendor", "total"],
  },
];

describe("validateInvoiceFieldsForApproval", () => {
  it("allows approve when no compulsory fields are configured", () => {
    const result = validateInvoiceFieldsForApproval(
      { vendor: "Acme", total: "100", due_date: null },
      undefined
    );
    expect(result).toEqual({ ok: true });
  });

  it("checks only configured compulsory fields", () => {
    const result = validateInvoiceFieldsForApproval(
      { vendor: "Acme", total: "100", due_date: null },
      ["vendor", "due_date"]
    );
    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.message).toContain("due_date");
    }
  });
});

describe("validateInvoiceReadyForApproval", () => {
  it("uses rule book compulsory fields for the invoice document type", () => {
    const result = validateInvoiceReadyForApproval(
      {
        document_type_code: "DT-08",
        vendor: "Acme",
        total: "100",
        due_date: null,
      },
      documentTypes
    );
    expect(result).toEqual({ ok: true });
  });

  it("blocks when starred compulsory fields are missing", () => {
    const result = validateInvoiceReadyForApproval(
      {
        document_type_code: "DT-08",
        vendor: null,
        total: "100",
      },
      documentTypes
    );
    expect(result.ok).toBe(false);
  });
});

describe("compulsoryFieldsForInvoice", () => {
  it("returns empty when document type is unknown", () => {
    expect(
      compulsoryFieldsForInvoice({ document_type_code: null }, documentTypes)
    ).toEqual([]);
  });
});
