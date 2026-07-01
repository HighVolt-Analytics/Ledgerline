import { Ban, Check, Clock } from "lucide-react";
import type { MatrixCell, MatrixCellState, MatrixStage } from "@/lib/matrix";
import type { MatrixFlagType } from "@/lib/v4MatrixMockData";

function MatrixCellIcon({ state }: { state: MatrixCellState }) {
  if (state === "done") {
    return (
      <Check
        className="h-4 w-4 text-[hsl(var(--chart-1))]"
        aria-label="done"
      />
    );
  }
  if (state === "fail") {
    return <Ban className="h-4 w-4 text-destructive" aria-label="failed" />;
  }
  return <Clock className="h-4 w-4 text-muted-foreground" aria-label="pending" />;
}

export function MatrixStageCell({
  stage,
  cell,
  blocked,
  flag,
}: {
  stage: MatrixStage;
  cell: MatrixCell;
  blocked: boolean;
  flag: MatrixFlagType;
}) {
  const tooltip = blocked
    ? `Blocked — clear the ${flag} flag before this document can progress to ${stage}.`
    : `${cell.state} · ${stage}\n${cell.ts}\n${cell.detail}`;

  return (
    <span
      className="inline-flex justify-center w-full py-1 group relative cursor-default"
      title={tooltip}
    >
      {blocked ? (
        <Ban className="h-4 w-4 text-muted-foreground/40" aria-label="blocked" />
      ) : (
        <MatrixCellIcon state={cell.state} />
      )}
      <span
        role="tooltip"
        className="pointer-events-none absolute bottom-full left-1/2 z-20 mb-1.5 hidden w-max max-w-[200px] -translate-x-1/2 rounded-md border border-border bg-popover px-2 py-1.5 text-left text-xs text-popover-foreground shadow-md group-hover:block"
      >
        {blocked ? (
          <>
            Blocked — clear the {flag} flag before this document can progress to {stage}.
          </>
        ) : (
          <>
            <span className="font-medium capitalize">{cell.state}</span>
            <span className="text-muted-foreground"> · {stage}</span>
            <br />
            <span className="text-[11px] text-muted-foreground tnum">
              {cell.ts}
              {cell.detail !== "—" ? (
                <>
                  <br />
                  {cell.detail}
                </>
              ) : null}
            </span>
          </>
        )}
      </span>
    </span>
  );
}
