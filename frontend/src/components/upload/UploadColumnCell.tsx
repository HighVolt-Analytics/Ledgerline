import type { ReactNode } from "react";
import { cn } from "@/lib/cn";
import type { ColumnDisplayMode } from "@/lib/uploadColumnState";

export function UploadColumnProcessingIndicator({ className }: { className?: string }) {
  return (
    <span
      className={cn("upload-col-processing inline-flex shrink-0", className)}
      role="status"
      aria-label="Processing"
    >
      <span className="upload-col-processing__ring" aria-hidden />
    </span>
  );
}

export function UploadColumnCell({
  mode,
  children,
  emptyFallback = "—",
  align = "left",
  className,
}: {
  mode: ColumnDisplayMode;
  children: ReactNode;
  emptyFallback?: ReactNode;
  align?: "left" | "right";
  className?: string;
}) {
  if (mode === "processing") {
    return (
      <span
        className={cn(
          "inline-flex items-center gap-1.5 min-h-[1.25rem]",
          align === "right" && "justify-end w-full",
          className
        )}
      >
        <UploadColumnProcessingIndicator />
      </span>
    );
  }

  if (mode === "empty") {
    return (
      <span
        className={cn(
          "text-muted-foreground text-xs inline-flex min-h-[1.25rem] items-center",
          align === "right" && "justify-end w-full",
          className
        )}
      >
        {emptyFallback}
      </span>
    );
  }

  return <>{children}</>;
}
