import { useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { AlertTriangle } from "lucide-react";
import type { Invoice } from "@/api/types";
import { StatusPill, pillTones } from "@/components/StatusPill";
import { cn } from "@/lib/cn";
import {
  matrixIssueFixHint,
  matrixIssueSummary,
} from "@/lib/matrixIssue";
import type { MatrixCell, MatrixStage } from "@/lib/matrix";

type MatrixIssueCellProps = {
  inv: Invoice;
  cells: Record<MatrixStage, MatrixCell>;
  /** When false, hide flag_reason so Clean rows with informational reasons stay blank. */
  flagged?: boolean;
  flagReason?: string | null;
  testId?: string;
  className?: string;
};

function IssueHoverCard({
  message,
  fixHint,
  anchor,
  tooltipId,
}: {
  message: string;
  fixHint: string;
  anchor: HTMLElement;
  tooltipId: string;
}) {
  const [pos, setPos] = useState<{
    top: number;
    left: number;
    above: boolean;
    width: number;
  } | null>(null);

  useLayoutEffect(() => {
    const rect = anchor.getBoundingClientRect();
    const width = Math.min(280, window.innerWidth - 16);
    const left = Math.min(
      Math.max(8, rect.left + rect.width / 2 - width / 2),
      window.innerWidth - width - 8
    );
    const preferAbove = rect.top > 160;
    setPos({
      top: preferAbove ? rect.top - 8 : rect.bottom + 8,
      left,
      above: preferAbove,
      width,
    });
  }, [anchor]);

  if (!pos) return null;

  return createPortal(
    <div
      id={tooltipId}
      role="tooltip"
      className="fixed z-[100] rounded-md border border-border bg-popover px-2.5 py-2 text-left text-[11px] font-normal leading-snug text-popover-foreground shadow-md"
      style={{
        top: pos.top,
        left: pos.left,
        width: pos.width,
        transform: pos.above ? "translateY(-100%)" : undefined,
      }}
    >
      <span className="block text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
        Issue
      </span>
      <span className="mt-0.5 block">{message}</span>
      {fixHint ? (
        <>
          <span className="mt-2 block text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
            How to fix
          </span>
          <span className="mt-0.5 block">{fixHint}</span>
        </>
      ) : null}
    </div>,
    document.body
  );
}

export function MatrixIssueCell({
  inv,
  cells,
  flagged = false,
  flagReason,
  testId,
  className,
}: MatrixIssueCellProps) {
  const tooltipId = useId();
  const wrapRef = useRef<HTMLElement | null>(null);
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

  const issue = matrixIssueSummary(cells, flagged ? flagReason : null, inv);
  if (!issue) {
    return (
      <span className={cn("text-xs text-muted-foreground inline-block w-14 text-center", className)}>
        —
      </span>
    );
  }

  const fixHint = matrixIssueFixHint(inv, issue);
  const aria = `Issue: ${issue.message}. How to fix: ${fixHint}`;

  return (
    <span
      ref={(el) => {
        wrapRef.current = el;
      }}
      className={cn("inline-flex", className)}
      data-testid={testId}
      aria-label={aria}
      onMouseEnter={() => setHovering(true)}
      onMouseLeave={() => setHovering(false)}
      onFocus={() => setHovering(true)}
      onBlur={() => setHovering(false)}
      aria-describedby={hovering ? tooltipId : undefined}
    >
      <StatusPill className={cn(pillTones.amber, "w-14 justify-center")}>
        <AlertTriangle className="h-3 w-3 shrink-0 ds-warning-icon" />
        Issue
      </StatusPill>
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
