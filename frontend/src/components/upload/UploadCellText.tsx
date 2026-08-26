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
      <col style={{ width: "5.5rem" }} />
      <col style={{ width: "7rem" }} />
      <col style={{ width: "7.5rem" }} />
      <col style={{ width: "5.5rem" }} />
      <col style={{ width: "5.5rem" }} />
      <col style={{ width: "5.5rem" }} />
      <col style={{ width: "6rem" }} />
      <col style={{ width: "5.5rem" }} />
    </colgroup>
  );
}
