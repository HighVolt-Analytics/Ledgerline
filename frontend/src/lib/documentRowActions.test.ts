import { describe, expect, it } from "vitest";
import type { Invoice } from "@/api/types";
import type { DocumentTypeDefinition } from "@/lib/v5DocumentTypes";
import {
  advanceBalanceDisplay,
  budgetUtilizationDisplay,
  documentRowActions,
} from "@/lib/documentRowActions";

function baseInvoice(overrides: Partial<Invoice> = {}): Invoice {
  return {
    id: 1,
    vendor: "Acme",
    abn: null,
    invoice_no: "INV-1",
    po_reference: null,
    cost_centre: null,
    invoice_date: "2026-01-01",
    due_date: null,
    currency: "MMK",
    subtotal: "100",
    gst: "0",
    gst_rate: null,
    total: "100",
    status: "exception",
    file_hash: null,
    raw_file_path: null,
    email_sender: null,
    capture_source: "upload",
    connected_mailbox_id: null,
    storage_vendor_slug: null,
    account_code: null,
    account_name: "Marketing Expenses",
    route_target: "Team Expenses",
    team_expense_kind: "expense_claim",
    linked_advance_invoice_id: null,
    matched_rule_ids: null,
    vendor_confidence: null,
    evaluation_status: "pending_approval",
    validation_results: null,
    document_type_code: "DT-TE",
    has_stored_file: true,
    created_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

const documentTypes = [
  {
    code: "DT-TE",
    requiredFields: [],
  },
] as unknown as DocumentTypeDefinition[];

describe("documentRowActions", () => {
  it("Classify when no mapped DT", () => {
    const result = documentRowActions(
      baseInvoice({ document_type_code: null, evaluation_status: "awaiting_classification" }),
      documentTypes
    );
    expect(result.primary).toEqual({
      kind: "classify",
      label: "Classify",
      drawerTab: "fields",
    });
  });

  it("Classify when awaiting_classification even with a code", () => {
    const result = documentRowActions(
      baseInvoice({ evaluation_status: "awaiting_classification" }),
      documentTypes
    );
    expect(result.primary.kind).toBe("classify");
  });

  it("Approve when gating passes on Team Expenses", () => {
    const result = documentRowActions(baseInvoice(), documentTypes);
    expect(result.primary).toEqual({ kind: "approve", label: "Approve" });
    expect(result.overflow).toEqual([{ kind: "reject", label: "Reject" }]);
  });

  it("hides Approve when no stored file", () => {
    const result = documentRowActions(
      baseInvoice({ has_stored_file: false }),
      documentTypes
    );
    expect(result.primary.kind).toBe("reject");
  });

  it("shows Approve for without-document claims with no stored file", () => {
    const result = documentRowActions(
      baseInvoice({
        has_stored_file: false,
        extracted_fields: { without_document: "true", manual_entry: "true" },
      }),
      documentTypes
    );
    expect(result.primary).toEqual({ kind: "approve", label: "Approve" });
  });

  it("hides Approve when Team Expenses amount is zero", () => {
    const result = documentRowActions(baseInvoice({ total: "0" }), documentTypes);
    expect(result.primary.kind).not.toBe("approve");
    expect(result.primary.kind).toBe("reject");
  });

  it("Approve when gating passes on Expenses Management", () => {
    const result = documentRowActions(
      baseInvoice({
        route_target: "Expenses Management",
        team_expense_kind: null,
        evaluation_status: "pending_approval",
      }),
      documentTypes
    );
    expect(result.primary).toEqual({ kind: "approve", label: "Approve" });
  });

  it("hides Approve when Expenses Management amount is zero", () => {
    const result = documentRowActions(
      baseInvoice({
        route_target: "Expenses Management",
        total: "0",
        evaluation_status: "pending_approval",
      }),
      documentTypes
    );
    expect(result.primary.kind).not.toBe("approve");
  });

  it("Match when purchase awaiting_po", () => {
    const result = documentRowActions(
      baseInvoice({
        route_target: "Purchase Management",
        evaluation_status: "awaiting_po",
        purchase_document_type: "invoice",
        po_reference: "PO-1",
      }),
      documentTypes
    );
    expect(result.primary).toEqual({
      kind: "match",
      label: "Match",
      drawerTab: "po",
    });
  });

  it("Match when purchase invoice missing po_reference", () => {
    const result = documentRowActions(
      baseInvoice({
        route_target: "Purchase Management",
        evaluation_status: "auto_coded",
        purchase_document_type: "invoice",
        po_reference: null,
        status: "exception",
      }),
      documentTypes
    );
    expect(result.primary.kind).toBe("match");
  });

  it("Match when purchase needs_review", () => {
    const result = documentRowActions(
      baseInvoice({
        route_target: "Purchase Management",
        evaluation_status: "needs_review",
        purchase_document_type: "invoice",
        po_reference: "PO-9",
      }),
      documentTypes
    );
    expect(result.primary.kind).toBe("match");
  });

  it("Approve purchase invoice when Match does not apply", () => {
    const result = documentRowActions(
      baseInvoice({
        route_target: "Purchase Management",
        evaluation_status: "pending_approval",
        purchase_document_type: "invoice",
        po_reference: "PO-100",
        status: "exception",
      }),
      documentTypes
    );
    expect(result.primary.kind).toBe("approve");
  });

  it("Match when sales document type is SO", () => {
    const result = documentRowActions(
      baseInvoice({
        route_target: "Sales Management",
        evaluation_status: "auto_coded",
        sales_document_type: "so",
        status: "processed",
      }),
      documentTypes
    );
    expect(result.primary.kind).toBe("match");
  });

  it("Match when sales awaiting_so", () => {
    const result = documentRowActions(
      baseInvoice({
        route_target: "Sales Management",
        evaluation_status: "awaiting_so",
        sales_document_type: "invoice",
        so_reference: "SO-1",
      }),
      documentTypes
    );
    expect(result.primary.kind).toBe("match");
  });

  it("Reject on Sales when Match does not apply and Approve cannot run", () => {
    const result = documentRowActions(
      baseInvoice({
        route_target: "Sales Management",
        evaluation_status: "auto_coded",
        sales_document_type: "invoice",
        so_reference: "SO-22",
        status: "exception",
        has_stored_file: false,
      }),
      documentTypes
    );
    expect(result.primary.kind).toBe("reject");
  });

  it("none when status cannot approve or reject", () => {
    const result = documentRowActions(
      baseInvoice({
        status: "pending",
        evaluation_status: "auto_coded",
      }),
      documentTypes
    );
    expect(result.primary.kind).toBe("none");
  });
});

describe("budgetUtilizationDisplay", () => {
  it("returns missing when allocated is zero or absent", () => {
    expect(budgetUtilizationDisplay(0, 10)).toEqual({
      kind: "missing",
      message: "No budget configured",
    });
    expect(budgetUtilizationDisplay(null, 10)).toEqual({
      kind: "missing",
      message: "No budget configured",
    });
  });

  it("returns consumed fill for configured budget", () => {
    expect(budgetUtilizationDisplay(12000, 2520)).toEqual({
      kind: "configured",
      used: 2520,
      total: 12000,
      pct: 21,
    });
  });
});

describe("advanceBalanceDisplay", () => {
  it("returns missing when unmatched", () => {
    expect(advanceBalanceDisplay(false, 25)).toEqual({
      kind: "missing",
      message: "No advance on file",
    });
  });

  it("returns missing when balance is null", () => {
    expect(advanceBalanceDisplay(true, null)).toEqual({
      kind: "missing",
      message: "No advance on file",
    });
  });

  it("treats confirmed 0 as a real remaining amount", () => {
    expect(advanceBalanceDisplay(true, 0)).toEqual({
      kind: "remaining",
      remaining: 0,
    });
  });

  it("uses consumed fill when float is known", () => {
    expect(advanceBalanceDisplay(true, 25, 100)).toEqual({
      kind: "consumed",
      used: 75,
      total: 100,
      pct: 75,
      remaining: 25,
    });
  });
});
