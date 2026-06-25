import type { Invoice, InvoiceStatus } from "@/api/types";

export const MATRIX_STAGES = [
  "Received",
  "Parsed",
  "Validated",
  "Mapped",
  "Approved",
  "Posted",
] as const;

export type MatrixStage = (typeof MATRIX_STAGES)[number];
export type MatrixCellState = "done" | "pending" | "fail";

export type MatrixCell = {
  state: MatrixCellState;
  ts: string;
  actor: string;
};

const STAGE_ACTORS: Record<MatrixStage, string> = {
  Received: "Email capture",
  Parsed: "OCR engine",
  Validated: "Validator",
  Mapped: "Rule engine",
  Approved: "Approver",
  Posted: "Ledger",
};

export function invoiceRoutedToSuspense(inv: Invoice): boolean {
  const account = inv.account_name?.toLowerCase() ?? "";
  return account.includes("suspense");
}

export function validationHasFailure(inv: Invoice): boolean {
  const rules = inv.validation_results;
  if (!rules?.length) return inv.status === "exception";
  return rules.some((r) => !r.skipped && !r.passed);
}

/** Completed stage count before the current in-progress pipeline step. */
export function completedStageCount(status: InvoiceStatus): number {
  switch (status) {
    case "pending":
      return 0;
    case "parsing":
      return 1;
    case "validating":
      return 2;
    case "mapping":
      return 3;
    case "journaling":
      return 4;
    case "reconciling":
      return 5;
    case "processed":
      return 6;
    case "exception":
    case "duplicate_skipped":
      return 0;
    case "rejected":
      return 1;
    default:
      return 0;
  }
}

export function buildMatrixCells(inv: Invoice): Record<MatrixStage, MatrixCell> {
  const cells = {} as Record<MatrixStage, MatrixCell>;

  if (inv.status === "duplicate_skipped") {
    for (const stage of MATRIX_STAGES) {
      cells[stage] = { state: stage === "Received" ? "fail" : "pending", ts: "—", actor: "—" };
    }
    return cells;
  }

  if (inv.status === "rejected") {
    cells.Received = { state: "done", ts: "—", actor: "—" };
    cells.Parsed = { state: "fail", ts: "—", actor: "—" };
    for (const stage of MATRIX_STAGES.slice(2)) {
      cells[stage] = { state: "pending", ts: "—", actor: "—" };
    }
    return cells;
  }

  if (inv.status === "processed") {
    for (const stage of MATRIX_STAGES) {
      cells[stage] = { state: "done", ts: "—", actor: "—" };
    }
    return cells;
  }

  if (inv.status === "exception" || invoiceRoutedToSuspense(inv)) {
    cells.Received = { state: "done", ts: "—", actor: "—" };
    cells.Parsed = { state: "done", ts: "—", actor: "—" };
    if (validationHasFailure(inv)) {
      cells.Validated = { state: "fail", ts: "—", actor: "—" };
      cells.Mapped = { state: "pending", ts: "—", actor: "—" };
    } else {
      cells.Validated = { state: "done", ts: "—", actor: "—" };
      cells.Mapped = { state: "fail", ts: "—", actor: "—" };
    }
    cells.Approved = { state: "pending", ts: "—", actor: "—" };
    cells.Posted = { state: "pending", ts: "—", actor: "—" };
    return cells;
  }

  const doneThrough = completedStageCount(inv.status);
  MATRIX_STAGES.forEach((stage, i) => {
    cells[stage] = { state: i < doneThrough ? "done" : "pending", ts: "—", actor: "—" };
  });
  return cells;
}

/** Attach v4-style timestamps and actors to pipeline cells (v4 `kW`). */
export function enrichMatrixCells(
  inv: Invoice,
  cells: Record<MatrixStage, MatrixCell>,
  rowIndex: number
): Record<MatrixStage, MatrixCell> {
  const date =
    inv.invoice_date?.slice(0, 10) ?? inv.created_at?.slice(0, 10) ?? "2026-01-01";
  const enriched = {} as Record<MatrixStage, MatrixCell>;

  for (const stage of MATRIX_STAGES) {
    const base = cells[stage];
    const actor =
      stage === "Posted"
        ? "Ledger sync"
        : stage === "Approved" && rowIndex % 3 === 0 && base.state === "done"
          ? "Marcus Webb"
          : STAGE_ACTORS[stage];

    if (base.state === "pending") {
      enriched[stage] = { state: "pending", ts: "—", actor };
    } else if (base.state === "fail") {
      enriched[stage] = { state: "fail", ts: `${date} 09:00`, actor };
    } else {
      const min = (10 + rowIndex) % 60;
      enriched[stage] = {
        state: "done",
        ts: `${date} 09:${String(min).padStart(2, "0")}`,
        actor,
      };
    }
  }

  if (inv.status === "processed") {
    enriched.Approved = {
      state: "done",
      ts: enriched.Approved.ts,
      actor: "Marcus Webb",
    };
    enriched.Posted = {
      state: "done",
      ts: enriched.Posted.ts,
      actor: "Ledger sync",
    };
  }

  return enriched;
}
