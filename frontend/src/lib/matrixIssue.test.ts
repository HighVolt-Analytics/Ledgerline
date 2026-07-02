import { describe, expect, it } from "vitest";
import type { Invoice } from "@/api/types";
import { MATRIX_STAGES, matrixStageSettled, type MatrixCell, type MatrixStage } from "@/lib/matrix";
import {
  matrixIssueSummary,
  parseStageFailureDetail,
  failedValidationResults,
} from "@/lib/matrixIssue";

function emptyCells(): Record<MatrixStage, MatrixCell> {
  return Object.fromEntries(
    MATRIX_STAGES.map((stage) => [stage, { state: "pending", ts: "—", detail: "—" }])
  ) as Record<MatrixStage, MatrixCell>;
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

  it("falls back to flag reason when no failed stage", () => {
    const issue = matrixIssueSummary(emptyCells(), "Vendor could not be matched confidently");
    expect(issue).toEqual({
      stage: null,
      message: "Vendor could not be matched confidently",
    });
  });
});

describe("failedValidationResults", () => {
  it("returns only failed non-skipped rules", () => {
    const inv = {
      validation_results: [
        { rule: "VR01", passed: true, message: "ok", skipped: false },
        { rule: "VR02", passed: false, message: "GST mismatch", skipped: false },
        { rule: "VR03", passed: false, message: "skipped", skipped: true },
      ],
    } as Invoice;
    expect(failedValidationResults(inv)).toHaveLength(1);
    expect(failedValidationResults(inv)[0]?.rule).toBe("VR02");
  });
});

describe("matrixStageSettled", () => {
  it("treats skipped as settled for progress counts", () => {
    expect(matrixStageSettled("skipped")).toBe(true);
    expect(matrixStageSettled("done")).toBe(true);
    expect(matrixStageSettled("pending")).toBe(false);
  });
});
