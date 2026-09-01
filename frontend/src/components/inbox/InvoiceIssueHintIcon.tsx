import { useEffect, useId, useRef, useState, type MouseEvent, type ReactNode } from "react";
import { Info } from "lucide-react";
import type { Invoice } from "@/api/types";
import { IssueHoverCard } from "@/components/inbox/IssueHoverCard";
import { cn } from "@/lib/cn";
import {
  invoiceListIssueSummary,
  matrixIssueFixHint,
  type MatrixIssueSummary,
} from "@/lib/matrixIssue";
import type { MatrixCell, MatrixStage } from "@/lib/matrix";

type InvoiceIssueHintIconProps = {
  inv: Invoice;
  cells?: Record<MatrixStage, MatrixCell> | null;
  flagReason?: string | null;
  issue?: MatrixIssueSummary | null;
  className?: string;
  testId?: string;
  empty?: ReactNode;
};

function stopRowActivation(event: MouseEvent) {
  event.stopPropagation();
}

export function InvoiceIssueHintIcon({
  inv,
  cells,
  flagReason,
  issue: issueOverride,
  className,
  testId,
  empty = null,
}: InvoiceIssueHintIconProps) {
  const tooltipId = useId();
  const wrapRef = useRef<HTMLSpanElement | null>(null);
  const [hovering, setHovering] = useState(false);

  useEffect(() => {
    if (!hovering) return;
    const hide = () => setHovering(false);
    window.addEventListener("scroll", hide, true);
    window.addEventListener("resize", hide);
    return () => {
      window.removeEventListener("scroll", hide, true);
      window.removeEventListener("resize", hide);
    };
  }, [hovering]);

  const issue =
    issueOverride ??
    invoiceListIssueSummary(inv, {
      cells: cells ?? undefined,
      flagReason,
    });
  if (!issue) {
    return (
      <span
        className={cn("inline-flex w-7 justify-center text-xs text-muted-foreground", className)}
        data-testid={testId}
      >
        {empty}
      </span>
    );
  }

  const fixHint = matrixIssueFixHint(inv, issue);
  const aria = `Issue: ${issue.message}. How to resolve: ${fixHint}`;

  return (
    <span
      ref={wrapRef}
      className={cn("inline-flex w-7 justify-center", className)}
      data-testid={testId}
      aria-label={aria}
      onMouseEnter={() => setHovering(true)}
      onMouseLeave={() => setHovering(false)}
      onFocus={() => setHovering(true)}
      onBlur={() => setHovering(false)}
      onClick={stopRowActivation}
      onMouseDown={stopRowActivation}
      aria-describedby={hovering ? tooltipId : undefined}
    >
      <button
        type="button"
        className="inline-flex h-6 w-6 items-center justify-center rounded-full border border-amber-500/40 bg-amber-500/10 text-amber-700 hover:bg-amber-500/20 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring dark:text-amber-300"
        tabIndex={0}
        aria-hidden={false}
      >
        <Info className="h-3.5 w-3.5 shrink-0" aria-hidden />
      </button>
      {hovering && wrapRef.current ? (
        <IssueHoverCard
          message={issue.message}
          fixHint={fixHint}
          anchor={wrapRef.current}
          tooltipId={tooltipId}
        />
      ) : null}
    </span>
  );
}
