import type { LucideIcon } from "lucide-react";
import { cn } from "@/lib/cn";

export function RuleBookEmptyPanel({
  icon: Icon,
  title,
  hint,
  className,
}: {
  icon?: LucideIcon;
  title: string;
  hint?: string;
  className?: string;
}) {
  return (
    <div className={cn("rule-book-empty-panel", className)}>
      {Icon ? (
        <div className="rule-book-empty-panel__icon" aria-hidden>
          <Icon className="h-8 w-8" />
        </div>
      ) : null}
      <p className="rule-book-empty-panel__title">{title}</p>
      {hint ? <p className="rule-book-empty-panel__hint">{hint}</p> : null}
    </div>
  );
}
