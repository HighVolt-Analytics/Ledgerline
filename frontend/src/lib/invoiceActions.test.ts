import { describe, expect, it } from "vitest";
import type { DocumentTypeDefinition } from "@/lib/v5DocumentTypes";
import {
  compulsoryFieldsForInvoice,
  postApprovalSettlement,
  settlementApprovalHint,
  settlementFieldsForApproval,
  validateInvoiceFieldsForApproval,
  validateInvoiceReadyForApproval,
} from "@/lib/invoiceActions";

const documentTypes = [
  {
    code: "DT-08",
    requiredFields: ["vendor", "total", "due_date"],
  },
] as unknown as DocumentTypeDefinition[];

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
        due_date: "2026-08-01",
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

describe("postApprovalSettlement", () => {
  const base = {
    vendor: "Acme",
    total: "100.00",
    due_date: "2026-08-01",
    purchase_document_type: null,
    sales_document_type: null,
    gl_posting_applicable: true,
  };

  it("expects payment for purchase route", () => {
    expect(
      postApprovalSettlement({ ...base, route_target: "Purchase Management" })
    ).toBe("payment");
  });

  it("expects collection for sales route", () => {
    expect(
      postApprovalSettlement({ ...base, route_target: "Sales Management" })
    ).toBe("collection");
  });

  it("expects none for team expenses", () => {
    expect(
      postApprovalSettlement({ ...base, route_target: "Team Expenses" })
    ).toBe("none");
  });

  it("expects none for sales route without due date", () => {
    expect(
      postApprovalSettlement({
        ...base,
        route_target: "Sales Management",
        due_date: null,
      })
    ).toBe("none");
  });
});

describe("settlementFieldsForApproval", () => {
  it("requires vendor total due_date for purchase route", () => {
    expect(
      settlementFieldsForApproval({
        route_target: "Purchase Management",
        vendor: "Acme",
        total: "100",
        due_date: "2026-08-01",
        purchase_document_type: null,
        sales_document_type: null,
        gl_posting_applicable: true,
      })
    ).toEqual(["vendor", "total", "due_date"]);
  });
});

describe("validateInvoiceReadyForApproval settlement", () => {
  it("blocks when document type requires due_date", () => {
    const result = validateInvoiceReadyForApproval(
      {
        document_type_code: "DT-08",
        route_target: "Purchase Management",
        vendor: "Acme",
        total: "100",
        due_date: null,
        purchase_document_type: null,
        sales_document_type: null,
        gl_posting_applicable: true,
      },
      documentTypes
    );
    expect(result.ok).toBe(false);
  });

  it("allows approve when route has no starred compulsory fields", () => {
    const result = validateInvoiceReadyForApproval(
      {
        document_type_code: null,
        route_target: "Purchase Management",
        vendor: "Acme",
        total: "100",
        due_date: null,
        purchase_document_type: null,
        sales_document_type: null,
        gl_posting_applicable: true,
      },
      undefined
    );
    expect(result).toEqual({ ok: true });
  });
});

describe("settlementApprovalHint", () => {
  it("returns payment hint for purchase", () => {
    expect(
      settlementApprovalHint({
        route_target: "Purchase Management",
        vendor: "Acme",
        total: "100",
        due_date: "2026-08-01",
        purchase_document_type: null,
        sales_document_type: null,
        gl_posting_applicable: true,
      })
    ).toContain("Payments queue");
  });
});
