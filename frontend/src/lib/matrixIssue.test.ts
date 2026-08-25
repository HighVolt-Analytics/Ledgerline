import { describe, expect, it } from "vitest";
import type { Invoice } from "@/api/types";
import { MATRIX_STAGES, matrixStageSettled, type MatrixCell, type MatrixStage } from "@/lib/matrix";
import {
  clarifyMatrixIssueTitle,
  matrixIssueFixHint,
  matrixIssueSummary,
  parseStageFailureDetail,
  failedValidationResults,
} from "@/lib/matrixIssue";

function emptyCells(): Record<MatrixStage, MatrixCell> {
  return Object.fromEntries(
    MATRIX_STAGES.map((stage) => [stage, { state: "pending", ts: "—", detail: "—" }])
  ) as Record<MatrixStage, MatrixCell>;
}

function inv(extra: Partial<Invoice> = {}): Invoice {
  return {
    id: 1,
    status: "exception",
    created_at: "2026-01-01T00:00:00Z",
    currency: "AUD",
    ...extra,
  } as Invoice;
}

describe("parseStageFailureDetail", () => {
  it("extracts the message after the stage prefix", () => {
    expect(parseStageFailureDetail("Tax & totals checked · Subtotal and GST required")).toBe(
      "Subtotal and GST required"
    );
  });

  it("returns the full detail when no separator", () => {
    expect(parseStageFailureDetail("Duplicate file skipped")).toBe("Duplicate file skipped");
  });
});

describe("matrixIssueSummary", () => {
  it("prefers the first failed stage", () => {
    const cells = emptyCells();
    cells.Validated = {
      state: "fail",
      ts: "2h ago",
      detail: "Tax & totals checked · Subtotal and GST required",
    };
    const issue = matrixIssueSummary(cells, "Routed to exception review");
    expect(issue).toEqual({
      stage: "Validated",
      message: "Subtotal and GST required",
    });
  });

  it("clarifies vague Routed to review using invoice context", () => {
    const cells = emptyCells();
    cells.Validated = {
      state: "fail",
      ts: "5d ago",
      detail: "Tax & totals checked · Routed to review",
    };
    const issue = matrixIssueSummary(
      cells,
      "Routed to exception review",
      inv({ evaluation_status: "awaiting_classification", llm_suggested_dt: "DT-11" })
    );
    expect(issue?.stage).toBe("Validated");
    expect(issue?.message).toContain("Document type not classified");
    expect(issue?.message).toContain("DT-11");
  });

  it("falls back to flag reason when no failed stage", () => {
    const issue = matrixIssueSummary(emptyCells(), "Vendor could not be matched confidently");
    expect(issue).toEqual({
      stage: null,
      message: "Vendor could not be matched confidently",
    });
  });

  it("returns null when clean with no failure", () => {
    expect(matrixIssueSummary(emptyCells(), null)).toBeNull();
  });
});

describe("clarifyMatrixIssueTitle", () => {
  it("uses failed validation message first", () => {
    expect(
      clarifyMatrixIssueTitle(
        inv({
          validation_results: [
            { rule: "VR03", passed: false, message: "GST does not reconcile", skipped: false },
          ],
        })
      )
    ).toBe("GST does not reconcile");
  });

  it("maps pending_vendor on sales to customer wording", () => {
    expect(
      clarifyMatrixIssueTitle(
        inv({
          evaluation_status: "pending_vendor",
          route_target: "Sales Management",
          vendor: "Acme",
          total: "100",
        })
      )
    ).toBe("Customer not in master");
  });

  it("distinguishes ungrounded amount from generic header review", () => {
    expect(
      clarifyMatrixIssueTitle(
        inv({
          evaluation_status: "vision_header_review",
          extracted_fields: { amount_ungrounded: "true" },
          vendor: "Acme",
          total: "100",
        })
      )
    ).toBe("Amount could not be verified against document text");
  });

  it("distinguishes amount inconsistency from generic header review", () => {
    expect(
      clarifyMatrixIssueTitle(
        inv({
          evaluation_status: "vision_header_review",
          extracted_fields: { amount_inconsistency: "true" },
          vendor: "Acme",
          total: "100",
        })
      )
    ).toBe("Amounts do not add up");
  });

  it("prefers missing currency over suspense GL", () => {
    expect(
      clarifyMatrixIssueTitle(
        inv({
          evaluation_status: "needs_review",
          document_type_code: "DT-11",
          route_target: "Purchase Management",
          account_name: "Suspense Account",
          account_code: "9999",
          currency: "",
          total: null,
          vendor: "Acme",
          gl_posting_applicable: true,
          document_type_extraction_fields: ["vendor", "total", "currency"],
        })
      )
    ).toMatch(/currency|financial fields incomplete/i);
  });
});

describe("matrixIssueFixHint", () => {
  it("pairs awaiting_classification to Fields confirm DT", () => {
    const invoice = inv({
      evaluation_status: "awaiting_classification",
      llm_suggested_dt: "DT-02",
      vendor: "Acme",
      total: "100",
    });
    const issue = matrixIssueSummary(emptyCells(), "Document type not classified — review required");
    const hint = matrixIssueFixHint(invoice, issue);
    expect(hint).toContain("confirm document type");
    expect(hint).toContain("DT-02");
    expect(hint).not.toBe(issue!.message);
  });

  it("pairs duplicate_skipped to document actions", () => {
    const invoice = inv({ status: "duplicate_skipped", evaluation_status: null, total: "100", vendor: "Acme" });
    const issue = matrixIssueSummary(emptyCells(), "Duplicate document skipped");
    const hint = matrixIssueFixHint(invoice, issue);
    expect(hint.toLowerCase()).toMatch(/unique|duplicate/);
    expect(hint).not.toBe(issue!.message);
  });

  it("pairs pending_vendor to Contacts → Vendors", () => {
    const invoice = inv({
      evaluation_status: "pending_vendor",
      route_target: "Purchase Management",
      vendor: "Acme",
      total: "100",
    });
    const issue = matrixIssueSummary(emptyCells(), "Vendor could not be matched confidently");
    const hint = matrixIssueFixHint(invoice, issue);
    expect(hint).toContain("Vendors");
    expect(hint).not.toBe(issue!.message);
  });

  it("pairs suspense / GL unresolved flag reason to Lines when fields are complete", () => {
    const invoice = inv({
      evaluation_status: "auto_coded",
      account_name: "Suspense",
      vendor: "Acme",
      total: "250",
      currency: "AUD",
      gl_posting_applicable: true,
    });
    const issue = matrixIssueSummary(emptyCells(), "GL mapping unresolved — routed to suspense");
    const hint = matrixIssueFixHint(invoice, issue);
    expect(hint.toLowerCase()).toContain("lines");
    expect(hint.toLowerCase()).toMatch(/gl|suspense/);
    expect(hint).not.toBe(issue!.message);
  });

  it("prefers Fields over Suspense when currency/total are missing", () => {
    const cells = emptyCells();
    cells.Validated = {
      state: "fail",
      ts: "5d ago",
      detail: "Tax & totals checked · Suspense / unmapped GL — assign account on Lines",
    };
    const invoice = inv({
      evaluation_status: "needs_review",
      document_type_code: "DT-11",
      route_target: "Purchase Management",
      account_name: "Suspense Account",
      account_code: "9999",
      currency: "",
      total: null,
      vendor: "Acme",
      gl_posting_applicable: true,
      document_type_extraction_fields: ["vendor", "total", "currency"],
      resolution_hint: "Open document drawer — check Fields, Audit, or Lines",
    });
    const issue = matrixIssueSummary(cells, "Suspense / unmapped GL — assign account on Lines", invoice);
    expect(issue?.message.toLowerCase()).toMatch(/currency|financial fields incomplete/);
    expect(issue?.message.toLowerCase()).not.toContain("suspense");
    const hint = matrixIssueFixHint(invoice, issue);
    expect(hint.toLowerCase()).toContain("fields");
    expect(hint.toLowerCase()).toMatch(/currency|total/);
    expect(hint.toLowerCase()).not.toContain("lines tab");
    expect(hint.toLowerCase()).not.toContain("open document drawer");
  });

  it("pairs failed Validated stage to Audit tab", () => {
    const cells = emptyCells();
    cells.Validated = {
      state: "fail",
      ts: "1h ago",
      detail: "Tax & totals checked · Subtotal and GST required",
    };
    const invoice = inv({ evaluation_status: null, vendor: "Acme", total: "100" });
    const issue = matrixIssueSummary(cells, null);
    const hint = matrixIssueFixHint(invoice, issue);
    expect(hint).toContain("Audit");
    expect(hint).not.toBe(issue!.message);
  });

  it("pairs vague Routed to review with missing DT to Fields", () => {
    const cells = emptyCells();
    cells.Validated = {
      state: "fail",
      ts: "1h ago",
      detail: "Tax & totals checked · Routed to review",
    };
    const invoice = inv({
      evaluation_status: null,
      document_type_code: null,
      llm_suggested_dt: "DT-04",
      resolution_hint: null,
      vendor: "Acme",
      total: "100",
      currency: "AUD",
    });
    const issue = matrixIssueSummary(cells, "Routed to exception review", invoice);
    expect(issue?.message.toLowerCase()).toContain("document type");
    const hint = matrixIssueFixHint(invoice, issue);
    expect(hint).toContain("confirm document type");
    expect(hint).toContain("DT-04");
  });

  it("pairs awaiting_po to Purchase register", () => {
    const invoice = inv({ evaluation_status: "awaiting_po", vendor: "Acme", total: "100" });
    const issue = matrixIssueSummary(emptyCells(), "Awaiting PO linkage");
    const hint = matrixIssueFixHint(invoice, issue);
    expect(hint.toLowerCase()).toContain("purchase");
    expect(hint.toLowerCase()).toContain("po");
    expect(hint).not.toBe(issue!.message);
  });

  it("pairs needs_rescan to clearer scan request", () => {
    const invoice = inv({ evaluation_status: "needs_rescan", vendor: "Acme", total: "100" });
    const issue = matrixIssueSummary(emptyCells(), "Poor image quality — rescan required");
    const hint = matrixIssueFixHint(invoice, issue);
    expect(hint.toLowerCase()).toMatch(/scan|pdf|reprocess/);
    expect(hint).not.toBe(issue!.message);
  });

  it("pairs rejected / quarantined to reprocess or delete", () => {
    const invoice = inv({ status: "rejected", vendor: "Acme", total: "100" });
    const issue = matrixIssueSummary(emptyCells(), "Invoice rejected and quarantined");
    const hint = matrixIssueFixHint(invoice, issue);
    expect(hint.toLowerCase()).toMatch(/reprocess|delete/);
    expect(hint).not.toBe(issue!.message);
  });

  it("never returns empty when an issue is shown", () => {
    const invoice = inv({ evaluation_status: null, resolution_hint: null, vendor: "Acme", total: "100" });
    const issue = matrixIssueSummary(emptyCells(), "Routed to exception review", invoice);
    expect(matrixIssueFixHint(invoice, issue).trim().length).toBeGreaterThan(0);
  });

  it("uses API resolution_hint only after stronger pairings miss", () => {
    const invoice = inv({
      evaluation_status: null,
      resolution_hint: "Fields tab — confirm document type",
      vendor: "Acme",
      total: "100",
      currency: "AUD",
    });
    expect(matrixIssueFixHint(invoice, null)).toBe("Fields tab — confirm document type");
  });
});

describe("failedValidationResults", () => {
  it("returns only failed non-skipped rules", () => {
    const row = {
      validation_results: [
        { rule: "VR01", passed: true, message: "ok", skipped: false },
        { rule: "VR02", passed: false, message: "GST mismatch", skipped: false },
        { rule: "VR03", passed: false, message: "skipped", skipped: true },
      ],
    } as Invoice;
    expect(failedValidationResults(row)).toHaveLength(1);
    expect(failedValidationResults(row)[0]?.rule).toBe("VR02");
  });
});

describe("matrixStageSettled", () => {
  it("treats skipped as settled for progress counts", () => {
    expect(matrixStageSettled("skipped")).toBe(true);
    expect(matrixStageSettled("done")).toBe(true);
    expect(matrixStageSettled("pending")).toBe(false);
  });
});
