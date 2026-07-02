import type { Invoice, ValidationResult } from "@/api/types";
import { MATRIX_STAGES, type MatrixCell, type MatrixStage } from "@/lib/matrix";

/** Pull the actionable phrase from a pipeline stage detail string. */
export function parseStageFailureDetail(detail: string | null | undefined): string {
  const raw = detail?.trim();
  if (!raw || raw === "—") return "Stage failed";
  const parts = raw
    .split("·")
    .map((part) => part.trim())
    .filter(Boolean);
  if (parts.length > 1) return parts[parts.length - 1]!;
  return raw;
}

export type MatrixIssueSummary = {
  stage: MatrixStage | null;
  message: string;
};

export function matrixIssueSummary(
  cells: Record<MatrixStage, MatrixCell>,
  flagReason?: string | null
): MatrixIssueSummary | null {
  for (const stage of MATRIX_STAGES) {
    const cell = cells[stage];
    if (cell?.state === "fail") {
      return {
        stage,
        message: parseStageFailureDetail(cell.detail),
      };
    }
  }
  const trimmed = flagReason?.trim();
  if (trimmed) {
    return { stage: null, message: trimmed };
  }
  return null;
}

export function failedValidationResults(inv: Invoice): ValidationResult[] {
  const rules = inv.validation_results ?? [];
  return rules.filter((rule) => !rule.skipped && !rule.passed);
}

export function matrixStageFailures(
  cells: Record<MatrixStage, MatrixCell>
): { stage: MatrixStage; message: string; detail: string }[] {
  return MATRIX_STAGES.flatMap((stage) => {
    const cell = cells[stage];
    if (cell?.state !== "fail") return [];
    return [
      {
        stage,
        message: parseStageFailureDetail(cell.detail),
        detail: cell.detail?.trim() || "—",
      },
    ];
  });
}
