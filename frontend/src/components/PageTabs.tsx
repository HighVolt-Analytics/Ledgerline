import type { ReactNode } from "react";
import { cn } from "@/lib/cn";

export function PageTabs({
  tabs,
  value,
  onChange,
  className,
  variant = "underline",
  "data-testid": testId,
}: {
  tabs: { value: string; label: ReactNode; testid?: string }[];
  value: string;
  onChange: (value: string) => void;
  className?: string;
  variant?: "underline" | "pill";
  "data-testid"?: string;
}) {
  if (variant === "pill") {
    return (
      <div
        data-testid={testId}
        className={cn(
          "flex h-auto min-h-10 w-full max-w-full flex-wrap items-center gap-1 rounded-md bg-muted p-1 text-muted-foreground",
          className
        )}
      >
        {tabs.map((tab) => (
          <button
            key={tab.value}
            type="button"
            data-testid={tab.testid}
            onClick={() => onChange(tab.value)}
            className={cn(
              "inline-flex items-center justify-center gap-1.5 whitespace-nowrap rounded-sm px-3 py-1.5 text-sm font-medium transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
              value === tab.value
                ? "bg-background text-foreground shadow-sm"
                : "text-muted-foreground hover:text-foreground"
            )}
          >
            {tab.label}
          </button>
        ))}
      </div>
    );
  }

  return (
    <div
      data-testid={testId}
      className={cn("flex flex-wrap gap-1 border-b border-border", className)}
    >
      {tabs.map((tab) => (
        <button
          key={tab.value}
          type="button"
          data-testid={tab.testid}
          onClick={() => onChange(tab.value)}
          className={cn(
            "relative px-3 py-2 text-sm font-medium transition-colors -mb-px",
            value === tab.value
              ? "text-foreground border-b-2 border-primary"
              : "text-muted-foreground hover:text-foreground"
          )}
        >
          {tab.label}
        </button>
      ))}
    </div>
  );
}

export function PageTabPanel({
  value,
  active,
  children,
  className,
}: {
  value: string;
  active: string;
  children: ReactNode;
  className?: string;
}) {
  if (value !== active) return null;
  return <div className={className}>{children}</div>;
}
