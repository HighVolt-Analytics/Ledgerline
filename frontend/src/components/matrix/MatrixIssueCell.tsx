import type { ReactNode } from "react";
import type { Invoice } from "@/api/types";
import { InvoiceIssueHintIcon } from "@/components/inbox/InvoiceIssueHintIcon";
import { cn } from "@/lib/cn";
import { matrixIssueSummary } from "@/lib/matrixIssue";
import type { MatrixCell, MatrixStage } from "@/lib/matrix";

type MatrixIssueCellProps = {
  inv: Invoice;
  cells: Record<MatrixStage, MatrixCell>;
  /** When false, hide flag_reason so Clean rows with informational reasons stay blank. */
  flagged?: boolean;
  flagReason?: string | null;
  testId?: string;
  className?: string;
  empty?: ReactNode;
};

/** Matrix/list issue affordance — Info icon with Issue + How to resolve hover card. */
export function MatrixIssueCell({
  inv,
  cells,
  flagged = false,
  flagReason,
  testId,
  className,
  empty = "—",
}: MatrixIssueCellProps) {
  const issue = matrixIssueSummary(cells, flagged ? flagReason : null, inv);

  return (
    <InvoiceIssueHintIcon
      inv={inv}
      cells={cells}
      flagReason={flagged ? flagReason : null}
      issue={issue}
      testId={testId}
      className={cn(className)}
      empty={empty}
    />
  );
}
