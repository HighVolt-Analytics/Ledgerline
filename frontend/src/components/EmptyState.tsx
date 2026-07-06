import { Card } from "@/components/ui/card";
import { cn } from "@/lib/cn";

export function EmptyState({
  title,
  hint,
  action,
  className,
}: {
  title: string;
  hint: string;
  action?: React.ReactNode;
  className?: string;
}) {
  return (
    <Card
      className={cn(
        "empty-state flex flex-col items-center justify-center text-center w-full gap-3 p-5",
        className
      )}
    >
      <h3 className="empty-state__title">{title}</h3>
      <p className="empty-state__hint">{hint}</p>
      {action}
    </Card>
  );
}
