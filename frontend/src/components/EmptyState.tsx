import { Card } from "@/components/ui/card";

export function EmptyState({
  title,
  hint,
  action,
}: {
  title: string;
  hint: string;
  action?: React.ReactNode;
}) {
  return (
    <Card className="p-8 flex flex-col items-center text-center max-w-lg mx-auto mt-8">
      <h3 className="text-sm font-semibold mb-2">{title}</h3>
      <p className="text-sm text-muted-foreground mb-4">{hint}</p>
      {action}
    </Card>
  );
}
