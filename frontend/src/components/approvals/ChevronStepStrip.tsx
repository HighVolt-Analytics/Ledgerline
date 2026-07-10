import { cn } from "@/lib/cn";

export type ChevronStepItem = {
  id: string;
  label: string;
};

export function ChevronStepStrip({
  items,
  activeId,
  onSelect,
  className,
}: {
  items: ChevronStepItem[];
  activeId?: string | null;
  onSelect?: (id: string) => void;
  className?: string;
}) {
  if (items.length === 0) return null;

  const interactive = Boolean(onSelect);

  return (
    <div
      className={cn("approvals-step-strip", className)}
      role={interactive ? "tablist" : "list"}
      data-testid="chevron-step-strip"
    >
      {items.map((item, index) => {
        const isStart = index === 0;
        const isEnd = index === items.length - 1;
        const isOnly = items.length === 1;
        const isActive = activeId === item.id;
        const Tag = interactive ? "button" : "div";

        return (
          <Tag
            key={item.id}
            type={interactive ? "button" : undefined}
            role={interactive ? "tab" : "listitem"}
            aria-selected={interactive ? isActive : undefined}
            onClick={interactive ? () => onSelect?.(item.id) : undefined}
            className={cn(
              "approvals-step-tag",
              isOnly && "approvals-step-tag--only",
              !isOnly && isStart && "approvals-step-tag--start",
              !isOnly && isEnd && "approvals-step-tag--end",
              !isOnly && !isStart && !isEnd && "approvals-step-tag--middle",
              isActive && "approvals-step-tag--active",
              interactive && "approvals-step-tag--interactive"
            )}
          >
            <span className="approvals-step-tag__label">{item.label}</span>
          </Tag>
        );
      })}
    </div>
  );
}
