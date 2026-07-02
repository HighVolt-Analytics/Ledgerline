import { Ban, Check, Clock, Minus } from "lucide-react";
import { MATRIX_STAGES, type MatrixCell, type MatrixStage } from "@/lib/matrix";
import { parseStageFailureDetail } from "@/lib/matrixIssue";
import { cn } from "@/lib/cn";

function StageStateIcon({ state }: { state: MatrixCell["state"] }) {
  if (state === "done") {
    return <Check className="h-3.5 w-3.5 text-[hsl(var(--chart-1))]" aria-hidden />;
  }
  if (state === "fail") {
    return <Ban className="h-3.5 w-3.5 text-destructive" aria-hidden />;
  }
  if (state === "skipped") {
    return <Minus className="h-3.5 w-3.5 text-muted-foreground/70" aria-hidden />;
  }
  return <Clock className="h-3.5 w-3.5 text-muted-foreground" aria-hidden />;
}

export function MatrixPipelineBreakdown({
  cells,
}: {
  cells: Record<MatrixStage, MatrixCell>;
}) {
  return (
    <div>
      <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wide mb-2">
        Pipeline stages
      </p>
      <ol className="space-y-1.5">
        {MATRIX_STAGES.map((stage) => {
          const cell = cells[stage];
          const failed = cell.state === "fail";
          const skipped = cell.state === "skipped";
          const issue = failed ? parseStageFailureDetail(cell.detail) : null;
          const skipNote = skipped ? parseStageFailureDetail(cell.detail) : null;
          return (
            <li
              key={stage}
              className={cn(
                "rounded-md border px-2.5 py-2 text-xs",
                failed
                  ? "border-destructive/30 bg-destructive/5"
                  : skipped
                    ? "border-border/60 bg-muted/30"
                    : "border-border/60 bg-muted/20"
              )}
            >
              <div className="flex items-center gap-2">
                <StageStateIcon state={cell.state} />
                <span className="font-medium">{stage}</span>
                <span className="ml-auto text-[10px] text-muted-foreground tnum capitalize">
                  {cell.state}
                </span>
              </div>
              {failed && issue ? (
                <p className="mt-1 pl-5 text-[11px] text-destructive">{issue}</p>
              ) : skipped && skipNote ? (
                <p className="mt-1 pl-5 text-[11px] text-muted-foreground">{skipNote}</p>
              ) : cell.detail && cell.detail !== "—" ? (
                <p className="mt-1 pl-5 text-[11px] text-muted-foreground">{cell.detail}</p>
              ) : null}
              {cell.ts && cell.ts !== "—" ? (
                <p className="mt-0.5 pl-5 text-[10px] text-muted-foreground tnum">{cell.ts}</p>
              ) : null}
            </li>
          );
        })}
      </ol>
    </div>
  );
}
