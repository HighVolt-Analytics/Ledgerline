import type { ReactNode } from "react";
import { cn } from "@/lib/cn";

const BASE =
  "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-medium whitespace-nowrap";

export const pillTones = {
  amber:
    "border-[rgb(var(--system-yellow-rgb)/0.35)] bg-[rgb(var(--system-yellow-rgb)/0.12)] text-[var(--system-yellow-text)]",
  blue: "border-[hsl(200_50%_50%/0.35)] bg-[hsl(200_50%_50%/0.08)] text-[hsl(200_45%_40%)] dark:text-[hsl(200_50%_65%)]",
  muted: "border-border bg-muted/50 text-muted-foreground",
  ok: "border-[hsl(var(--success)/0.4)] bg-[hsl(var(--success)/0.08)] text-[hsl(var(--success))]",
  bad: "border-destructive/40 bg-destructive/5 text-destructive",
  whatsapp:
    "bg-[hsl(145_63%_42%/0.16)] text-[hsl(145_55%_34%)] dark:text-[hsl(145_55%_60%)] border-transparent",
} as const;

export function StatusPill({ className, children }: { className?: string; children: ReactNode }) {
  return <span className={cn(BASE, className)}>{children}</span>;
}
