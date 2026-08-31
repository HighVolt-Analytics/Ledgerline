import { describe, expect, it } from "vitest";
import type { InvoiceDetails } from "@/api/types";
import type { DocumentTypeDefinition } from "@/lib/v5DocumentTypes";
import {
  approvalFailureMessage,
  canRequestInfo,
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

  it("allows approve when VR03 is disabled even if starred fields are missing", () => {
    const vr03OffTypes = [
      {
        code: "DT-08",
        requiredFields: ["vendor", "total", "due_date"],
        validationRules: [{ code: "VR03", enabled: false, severity: "block" as const }],
      },
    ] as unknown as DocumentTypeDefinition[];

    const result = validateInvoiceReadyForApproval(
      {
        document_type_code: "DT-08",
        vendor: null,
        total: "100",
        due_date: null,
      },
      vr03OffTypes
    );
    expect(result).toEqual({ ok: true });
  });

  it("blocks Team Expenses approve when amount is missing, even if VR03 is off", () => {
    const vr03OffTypes = [
      {
        code: "DT-09",
        requiredFields: ["total"],
        validationRules: [{ code: "VR03", enabled: false, severity: "block" as const }],
      },
    ] as unknown as DocumentTypeDefinition[];

    const missing = validateInvoiceReadyForApproval(
      {
        document_type_code: "DT-09",
        route_target: "Team Expenses",
        vendor: "R&B",
        total: null,
      },
      vr03OffTypes
    );
    expect(missing.ok).toBe(false);
    if (!missing.ok) {
      expect(missing.message).toMatch(/missing or zero/i);
    }

    const zero = validateInvoiceReadyForApproval(
      {
        document_type_code: "DT-09",
        route_target: "Team Expenses",
        total: "0",
      },
      vr03OffTypes
    );
    expect(zero.ok).toBe(false);

    const funded = validateInvoiceReadyForApproval(
      {
        document_type_code: "DT-09",
        route_target: "Team Expenses",
        total: "20000",
      },
      vr03OffTypes
    );
    expect(funded).toEqual({ ok: true });
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
    ).toContain("payments queue");
  });
});

describe("approvalFailureMessage", () => {
  it("prefers a control-account hint over the generic needs-review toast", () => {
    expect(
      approvalFailureMessage({
        status: "exception",
        evaluation_status: "needs_review",
        resolution_hint:
          "Rule Book → Posting → Team expense posting — select the advance parent ledger from the chart of accounts, then reprocess",
      } as InvoiceDetails)
    ).toContain("chart of accounts");
  });

  it("uses Posted stage when the hint is the generic drawer line", () => {
    expect(
      approvalFailureMessage({
        status: "exception",
        evaluation_status: "needs_review",
        resolution_hint:
          "Needs manual review — open document and check Fields, Audit, or Lines",
        current_stage: "Posted",
        current_stage_state: "fail",
      } as InvoiceDetails)
    ).toContain("chart of accounts");
  });
});

describe("canRequestInfo", () => {
  it("hides request-approval for posted and already-queued documents", () => {
    expect(canRequestInfo("processed")).toBe(false);
    expect(canRequestInfo("exception")).toBe(false);
    expect(canRequestInfo("rejected")).toBe(false);
    expect(canRequestInfo("duplicate_skipped")).toBe(false);
    expect(canRequestInfo("pending")).toBe(true);
  });
});
