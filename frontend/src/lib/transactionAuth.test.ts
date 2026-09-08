import { describe, expect, it } from "vitest";
import type { Invoice, MatrixRow } from "@/api/types";
import { MATRIX_STAGES, type MatrixCell, type MatrixStage } from "@/lib/matrix";
import { buildTransactionAuthView } from "@/lib/transactionAuth";

function inv(overrides: Partial<Invoice> = {}): Invoice {
  return {
    id: 1,
    status: "exception",
    vendor: "Acme",
    invoice_no: "INV-1",
    document_ref: "DOC-1",
    currency: "USD",
    total: "100",
    capture_source: "upload",
    route_target: "Team Expenses",
    evaluation_status: "pending_approval",
    gl_posting_applicable: true,
    ...overrides,
  } as Invoice;
}

function cells(overrides: Partial<Record<MatrixStage, MatrixCell>> = {}): Record<MatrixStage, MatrixCell> {
  const base = Object.fromEntries(
    MATRIX_STAGES.map((stage) => [stage, { state: "pending", ts: "—", detail: "—" }])
  ) as Record<MatrixStage, MatrixCell>;
  return { ...base, ...overrides };
}

function row(overrides: Partial<MatrixRow> & { invoice?: Invoice } = {}): MatrixRow {
  return {
    invoice: overrides.invoice ?? inv(),
    stages: [],
    flag: "Clean",
    payment_status: "—",
    conflict_with: null,
    line_item_count: 0,
    advance_auth: "—",
    budget_auth: "—",
    acc_sync: "—",
    ...overrides,
  };
}

describe("buildTransactionAuthView", () => {
  it("shows NA when no auth steps apply", () => {
    const view = buildTransactionAuthView({
      inv: inv({
        route_target: "Vault",
        evaluation_status: "auto_coded",
        gl_posting_applicable: false,
      }),
      matrixRow: row({
        invoice: inv({
          route_target: "Vault",
          evaluation_status: "auto_coded",
          gl_posting_applicable: false,
        }),
        advance_auth: "—",
        budget_auth: "—",
      }),
      cells: cells({ Approved: { state: "skipped", ts: "—", detail: "—" } }),
      nature: "Non-transactional",
    });
    expect(view.applicable).toBe(false);
    expect(view.displayStatus).toBe("NA");
    expect(view.actionableSteps).toHaveLength(0);
  });

  it("orders pending Privilege before Advance and Budget", () => {
    const invoice = inv({ evaluation_status: "pending_approval" });
    const view = buildTransactionAuthView({
      inv: invoice,
      matrixRow: row({
        invoice,
        advance_auth: "Pending",
        budget_auth: "Pending",
      }),
      cells: cells(),
      nature: "Transactional",
    });
    expect(view.applicable).toBe(true);
    expect(view.primaryPending?.kind).toBe("privilege");
    expect(view.displayStatus).toBe("Pending");
    expect(view.actionableSteps.map((s) => s.kind)).toEqual([
      "privilege",
      "advance",
      "budget",
    ]);
    expect(view.primaryPending?.actionNeeded.length).toBeGreaterThan(10);
  });

  it("falls through to Advance when Privilege is cleared", () => {
    const invoice = inv({ evaluation_status: "auto_coded", status: "processed" });
    const view = buildTransactionAuthView({
      inv: invoice,
      matrixRow: row({
        invoice,
        advance_auth: "Pending",
        budget_auth: "Done",
      }),
      cells: cells({ Approved: { state: "done", ts: "—", detail: "—" } }),
      nature: "Transactional",
    });
    expect(view.primaryPending?.kind).toBe("advance");
    expect(view.actionableSteps).toHaveLength(1);
  });
});
