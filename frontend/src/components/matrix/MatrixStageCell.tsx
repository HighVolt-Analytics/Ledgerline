import { Ban, Check, Clock, Minus } from "lucide-react";
import type { MatrixCell, MatrixCellState, MatrixStage } from "@/lib/matrix";
import { parseStageFailureDetail } from "@/lib/matrixIssue";
import type { MatrixFlagType } from "@/lib/v4MatrixMockData";
import { cn } from "@/lib/cn";

function MatrixCellIcon({ state }: { state: MatrixCellState }) {
  if (state === "done") {
    return (
      <Check
        className="matrix-ok-icon h-4 w-4 shrink-0"
        aria-label="done"
      />
    );
  }
  if (state === "fail") {
    return <Ban className="h-4 w-4 text-destructive" aria-label="failed" />;
  }
  if (state === "skipped") {
    return <Minus className="h-4 w-4 text-muted-foreground/70" aria-label="skipped" />;
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
  const failureMessage =
    cell.state === "fail" ? parseStageFailureDetail(cell.detail) : null;
  const skippedMessage =
    cell.state === "skipped" ? parseStageFailureDetail(cell.detail) : null;

  const tooltip = blocked
    ? `Blocked — clear the ${flag} flag before this document can progress to ${stage}.`
    : failureMessage
      ? `${stage} failed: ${failureMessage}`
      : skippedMessage
        ? `${stage} skipped: ${skippedMessage}`
        : `${cell.state} · ${stage}\n${cell.ts}\n${cell.detail}`;

  return (
    <span
      className="inline-flex justify-center w-full py-1 group relative cursor-default"
      title={tooltip}
      onClick={(e) => e.stopPropagation()}
    >
      {blocked ? (
        <Ban className="h-4 w-4 text-muted-foreground/40" aria-label="blocked" />
      ) : (
        <MatrixCellIcon state={cell.state} />
      )}
      <span
        role="tooltip"
        className={cn(
          "pointer-events-none absolute bottom-full left-1/2 z-20 mb-1.5 hidden w-max max-w-[min(280px,70vw)] -translate-x-1/2 rounded-md border px-2.5 py-2 text-left text-xs shadow-md group-hover:block",
          cell.state === "fail" && !blocked
            ? "border-destructive/30 bg-destructive/10 text-destructive"
            : cell.state === "skipped" && !blocked
              ? "border-border bg-muted/80 text-muted-foreground"
              : "border-border bg-popover text-popover-foreground"
        )}
      >
        {blocked ? (
          <>
            Blocked — clear the {flag} flag before this document can progress to {stage}.
          </>
        ) : cell.state === "fail" && failureMessage ? (
          <>
            <span className="font-semibold">{stage} failed</span>
            <p className="mt-1 text-[11px] leading-snug">{failureMessage}</p>
            {cell.detail && cell.detail !== failureMessage ? (
              <p className="mt-1 text-[10px] opacity-80">{cell.detail}</p>
            ) : null}
          </>
        ) : cell.state === "skipped" && skippedMessage ? (
          <>
            <span className="font-semibold">{stage} skipped</span>
            <p className="mt-1 text-[11px] leading-snug">{skippedMessage}</p>
            {cell.detail && cell.detail !== skippedMessage ? (
              <p className="mt-1 text-[10px] opacity-80">{cell.detail}</p>
            ) : null}
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
