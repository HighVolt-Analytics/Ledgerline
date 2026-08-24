import type { ReactNode } from "react";
import { cn } from "@/lib/cn";

/** Ellipsis in a fixed table column; full value on hover. */
export function UploadCellText({
  value,
  className,
}: {
  value: string | null | undefined;
  className?: string;
}) {
  const text = (value ?? "").trim() || "—";
  return (
    <span
      className={cn("all-docs-clip", className)}
      title={text === "—" ? undefined : text}
    >
      {text}
    </span>
  );
}

export function UploadCellClip({
  title,
  children,
  className,
}: {
  title?: string | null;
  children: ReactNode;
  className?: string;
}) {
  const tip = (title ?? "").trim();
  return (
    <span className={cn("all-docs-clip-wrap", className)} title={tip || undefined}>
      {children}
    </span>
  );
}

export function UploadSummaryColGroup({ showSource }: { showSource: boolean }) {
  return (
    <colgroup>
      <col className="all-docs-col all-docs-col--doc" />
      {showSource ? <col className="all-docs-col all-docs-col--source" /> : null}
      <col className="all-docs-col all-docs-col--type" />
      <col className="all-docs-col all-docs-col--party" />
      <col className="all-docs-col all-docs-col--nature" />
      <col className="all-docs-col all-docs-col--date" />
      <col className="all-docs-col all-docs-col--ledger" />
      <col className="all-docs-col all-docs-col--amount" />
      <col className="all-docs-col all-docs-col--status" />
      <col className="all-docs-col all-docs-col--status" />
      <col className="all-docs-col all-docs-col--pay" />
      <col className="all-docs-col all-docs-col--action" />
      <col className="all-docs-col all-docs-col--vault" />
    </colgroup>
  );
}

export function UploadDetailedColGroup({ showSource }: { showSource: boolean }) {
  return (
    <colgroup>
      <col style={{ width: "5.5rem" }} />
      {showSource ? <col style={{ width: "6rem" }} /> : null}
      <col style={{ width: "6.5rem" }} />
      <col style={{ width: "7rem" }} />
      <col style={{ width: "7.5rem" }} />
      <col style={{ width: "7rem" }} />
      <col style={{ width: "6.5rem" }} />
      <col style={{ width: "8.5rem" }} />
      <col style={{ width: "5.5rem" }} />
      <col style={{ width: "7rem" }} />
      <col style={{ width: "4.5rem" }} />
      <col style={{ width: "7.5rem" }} />
      <col style={{ width: "5.5rem" }} />
      <col style={{ width: "5.5rem" }} />
      <col style={{ width: "5.5rem" }} />
      <col style={{ width: "6rem" }} />
      <col style={{ width: "5.5rem" }} />
    </colgroup>
  );
}
