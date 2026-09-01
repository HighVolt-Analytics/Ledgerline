import { useLayoutEffect, useState } from "react";
import { createPortal } from "react-dom";

export function IssueHoverCard({
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
    const width = Math.min(300, window.innerWidth - 16);
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
            How to resolve
          </span>
          <span className="mt-0.5 block">{fixHint}</span>
        </>
      ) : null}
    </div>,
    document.body
  );
}
